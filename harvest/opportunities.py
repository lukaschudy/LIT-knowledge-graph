"""Public funding and rare-disease target/drug metadata harvesters."""
from __future__ import annotations
import hashlib, json, re, time
from collections import defaultdict
from pathlib import Path
import requests
from harvest import core

GRANTS='https://api.grants.gov/v1/api/search2'
GRANTS_DETAIL='https://api.grants.gov/v1/api/fetchOpportunity'
OT='https://api.platform.opentargets.org/api/v4/graphql'
TERMS=('rare disease','rare diseases','orphan disease','orphan diseases','orphan drug','orphan products','rare disorder','rare disorders','GRIN2A','GRIN2B')

def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def _slug(text): return re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')

def grants_search_body(keyword, offset, rows=100, statuses='forecasted|posted'):
    return {'keyword':keyword,'rows':rows,'startRecordNum':offset,'oppStatuses':statuses}

def _id_number(row):
    return str(row.get('id') or row.get('oppId') or '')

def harvest_grants_gov(page_size=100):
    """Page every current forecasted/posted Grants.gov result for each rare/orphan phrase."""
    source='grants_gov'; unique={}; searches=[]; detail_probe=None
    for term in TERMS:
        offset=0; expected=None; pages=0; returned=0; identifiers=set(); reported_counts=set()
        while expected is None or offset < expected:
            gene_query=term in ('GRIN2A','GRIN2B')
            statuses='forecasted|posted|closed|archived' if gene_query else 'forecasted|posted'
            body=grants_search_body(term,offset,page_size,statuses)
            filename=f"search-{_slug(term)}-{_slug(statuses)}-offset-{offset:08d}.json"
            p=core.download(source,GRANTS,filename,license_name='U.S. federal public opportunity metadata',version='search2-current',method='POST',json_body=body)
            obj=_json(p)
            if obj.get('errorcode') not in (None,0): raise RuntimeError(f"Grants.gov search error for {term}: {obj.get('msg')}")
            data=obj.get('data') or {}; hits=data.get('oppHits') or []
            reported_counts.add(int(data.get('hitCount') or 0))
            if expected is None: expected=int(data.get('hitCount') or 0)
            for hit in hits:
                ident=_id_number(hit)
                if not ident: continue
                identifiers.add(ident)
                if ident not in unique: unique[ident]=dict(hit,query_membership=[])
                entry={'term':term,'status_filter':statuses}
                if entry not in unique[ident]['query_membership']: unique[ident]['query_membership'].append(entry)
            pages+=1; returned+=len(hits)
            if not hits: break
            next_offset=int(data.get('startRecord',offset))+len(hits)
            if next_offset<=offset:raise RuntimeError('Grants.gov pagination did not advance; acquisition is incomplete')
            offset=next_offset
            if offset>=expected: break
            time.sleep(.1)
        searches.append({'term':term,'status_filter':statuses,'hit_count_reported':expected,
                         'reported_counts':sorted(reported_counts),'records_received':returned,
                         'unique_records_received':len(identifiers),'pages':pages,
                         'complete':returned==expected and len(identifiers)==expected and len(reported_counts)==1})
    if not unique: raise RuntimeError('Grants.gov returned no opportunities for rare/orphan search terms')
    # The detailed endpoint is documented and public. Probe it once because its
    # backend can be unavailable independently from the working search service.
    first=next(iter(unique.values())); detail_path=core.download(source,GRANTS_DETAIL,'fetchOpportunity-probe.json',license_name='U.S. federal public opportunity metadata',version='current',method='POST',json_body={'oppId':_id_number(first)})
    detail_probe=_json(detail_path)
    detail_available=not bool((detail_probe.get('data') or {}).get('message'))
    details=[]
    if detail_available:
        for ident in unique:
            p=core.download(source,GRANTS_DETAIL,f"detail-{ident}.json",license_name='U.S. federal public opportunity metadata',version='current',method='POST',json_body={'oppId':ident})
            response=_json(p)
            if response.get('errorcode') not in (None,0) or (response.get('data') or {}).get('message'):
                details.append({'opp_id':ident,'response':response,'detail_available':False})
            else:
                details.append({'opp_id':ident,'response':response,'detail_available':True})
    out=core.emit_records(source,'opportunities',unique.values(),input_paths=[core.RAW/source],description='Acquired union of paged Grants.gov search2 results for rare/orphan disease, orphan product and rare disorder terms, restricted to current forecasted/posted opportunities. Native search result fields and every matching query are retained; manifest coverage records count and uniqueness gaps.')
    if details:
        core.emit_records(source,'opportunity_details',details,input_paths=[core.RAW/source],description='fetchOpportunity endpoint responses for each matching opportunity ID; full provider envelopes retained.')
    detail_record={'opp_id':_id_number(first),'detail_available':detail_available,'response':detail_probe}
    core.emit_records(source,'opportunity_detail_endpoint_probe',[detail_record],input_paths=[detail_path],description='One public fetchOpportunity endpoint health response. Search2 has no human-readable opportunity detail records; the current details backend probe determined whether detailed expansion was possible.')
    problems=[x for x in searches if not x['complete']]
    status='partial' if (not detail_available or problems) else 'complete'
    core.update_manifest(source,status=status,search_terms=list(TERMS),coverage={'unique_opportunities':len(unique),'searches':searches,'statuses':{'rare_orphan_phrases':['forecasted','posted'],'gene_symbol_queries':['forecasted','posted','closed','archived']},'detail_endpoint_available':detail_available,'detail_endpoint_message':(detail_probe.get('data') or {}).get('message'),'incomplete_searches':problems,'limitation':'Search2 metadata is the complete result summary for each paged query; phrase indexing limits recall. The documented fetchOpportunity detail endpoint was probed once; search results remain metadata-only while its backend is unavailable.'})
    return out

def rare_disease_mondo_ids(raresource_path=None, mondo_path=None):
    rare=Path(raresource_path or core.PROCESSED/'raresource/diseases.jsonl.gz')
    mondo=Path(mondo_path or core.PROCESSED/'mondo/obo_stanzas.jsonl.gz')
    if not rare.exists() or not mondo.exists(): raise FileNotFoundError('RareSource disease and MONDO ontology harvests are required')
    xrefs=defaultdict(set)
    for row in core.read_records(mondo):
        tags=row.get('tags') or {}
        if row.get('stanza_type')!='Term': continue
        mondo_id=(tags.get('id') or [''])[0].replace(':','_')
        if not mondo_id.startswith('MONDO_'): continue
        for xref in tags.get('xref',[]):
            token=xref.split()[0]
            if token.startswith(('OMIM:','Orphanet:')): xrefs[token].add(mondo_id)
    disease_membership=defaultdict(list)
    for row in core.read_records(rare):
        for db in ('OMIM','Orphanet'):
            for native_id in (row.get(db) or '').split('//'):
                native_id=native_id.strip()
                if not native_id: continue
                for mondo_id in xrefs.get(f'{db}:{native_id}',()):
                    rec={'rare_disease_name':row.get('Rare Disease Name'),'identifier_namespace':db,'identifier':native_id}
                    if rec not in disease_membership[mondo_id]: disease_membership[mondo_id].append(rec)
    return disease_membership

def grin_disease_mondo_ids():
    """Curated MONDO IDs for GRIN2A/B from exact gene assertions and model sources."""
    result=defaultdict(list); hgnc={'HGNC:4585':'GRIN2A','HGNC:4586':'GRIN2B'}
    xrefs=defaultdict(set)
    for row in core.read_records(core.PROCESSED/'mondo/obo_stanzas.jsonl.gz'):
        tags=row.get('tags') or {}; mondo=(tags.get('id') or [''])[0].replace(':','_')
        for xref in tags.get('xref',[]):
            token=xref.split()[0]
            if token.startswith(('OMIM:','Orphanet:')): xrefs[token].add(mondo)
    def add(mondo,gene,provider,native_id):
        mid=str(mondo or '').replace(':','_')
        if mid.startswith('MONDO_'):
            item={'gene':gene,'provider':provider,'native_disease_id':native_id}
            if item not in result[mid]: result[mid].append(item)
    for dataset in ('gene_disease_validity','gene_disease_validity_lumping_splitting'):
        p=core.PROCESSED/'clingen'/(dataset+'.jsonl.gz')
        for row in core.read_records(p):
            gene=hgnc.get(row.get('GENE ID (HGNC)'))
            if gene: add(row.get('DISEASE ID (MONDO)'),gene,'clingen',row.get('DISEASE ID (MONDO)'))
    for row in core.read_records(core.PROCESSED/'gencc/assertions.jsonl.gz'):
        gene=hgnc.get(row.get('gene_curie'))
        if not gene: continue
        native=row.get('disease_curie') or row.get('disease_original_curie')
        if str(native).startswith('MONDO:'): add(native,gene,'gencc',native)
        elif native:
            for mondo in xrefs.get(str(native),()): add(mondo,gene,'gencc',native)
    for row in core.read_records(core.PROCESSED/'hpo/genes_to_disease.jsonl.gz'):
        gene=row.get('gene_symbol')
        if gene not in ('GRIN2A','GRIN2B'): continue
        native=row.get('disease_id')
        for mondo in xrefs.get(str(native),()): add(mondo,gene,'hpo',native)
    # Orphanet gene–disorder table carries explicit disease IDs and gene symbol.
    def walk(node):
        if isinstance(node,dict):
            yield node
            for child in node.get('children',[]): yield from walk(child)
        elif isinstance(node,list):
            for child in node: yield from walk(child)
    for row in core.read_records(core.PROCESSED/'orphadata/genes.jsonl.gz'):
        nodes=list(walk(row)); symbols={str(n.get('text','')).upper() for n in nodes if n.get('tag')=='Symbol'}
        found=symbols.intersection({'GRIN2A','GRIN2B'})
        if not found: continue
        code=next((str(n.get('text','')).strip() for n in row.get('children',[]) if n.get('tag')=='OrphaCode'),None)
        if code:
            for gene in found:
                for mondo in xrefs.get('Orphanet:'+code,()): add(mondo,gene,'orphadata','Orphanet:'+code)
    return result

def _type_leaf(type_ref):
    while type_ref and type_ref.get('ofType'): type_ref=type_ref['ofType']
    return type_ref or {}

def _evidence_selection():
    """Use all scalar Evidence fields plus one level of nested scalar fields."""
    shallow='kind name ofType { kind name ofType { kind name ofType { kind name } } }'
    fields_query=f'query {{ __type(name:"Evidence") {{ fields {{ name args {{ name type {{ {shallow} }} defaultValue }} type {{ {shallow} }} }} }} }}'
    schema_path=core.download('open_targets',OT,'evidence-schema.json',license_name='Open Targets GraphQL schema',version='current GraphQL schema (unversioned API)',method='POST',json_body={'query':fields_query})
    schema=_json(schema_path); evidence_fields=schema.get('data',{}).get('__type',{}).get('fields') or []
    nested_names=[]
    for field in evidence_fields:
        leaf=_type_leaf(field.get('type'))
        if leaf.get('kind')=='OBJECT' and leaf.get('name') not in nested_names: nested_names.append(leaf['name'])
    aliases=[f't{i}: __type(name:"{name}") {{ fields {{ name args {{ name type {{ {shallow} }} defaultValue }} type {{ {shallow} }} }} }}' for i,name in enumerate(nested_names)]
    nested_path=core.download('open_targets',OT,'evidence-nested-schema.json',license_name='Open Targets GraphQL schema',version='current GraphQL schema (unversioned API)',method='POST',json_body={'query':'query {'+' '.join(aliases)+'}'})
    nested=_json(nested_path).get('data') or {}
    def valid_field(f):
        if any(a.get('type',{}).get('kind')=='NON_NULL' and a.get('defaultValue') is None for a in f.get('args',[])): return False
        return _type_leaf(f.get('type')).get('kind') in ('SCALAR','ENUM')
    selections=[]
    for field in evidence_fields:
        leaf=_type_leaf(field.get('type'))
        if valid_field(field): selections.append(field['name'])
        elif leaf.get('kind')=='OBJECT':
            i=nested_names.index(leaf['name']); fields=nested.get(f't{i}',{}).get('fields') or []
            children=[f['name'] for f in fields if valid_field(f)]
            if children: selections.append(f"{field['name']} {{ {' '.join(children)} }}")
    return ' '.join(selections)

def harvest_grin_evidence(page_size=100):
    """Exhaust Open Targets evidence cursors for curated GRIN2A/B disease IDs."""
    source='open_targets'; evidence_ids=grin_disease_mondo_ids(); selection=_evidence_selection()
    if not evidence_ids: raise RuntimeError('No curated GRIN2A/GRIN2B disease IDs mapped to Open Targets MONDO IDs')
    genes=[('ENSG00000183454','GRIN2A','HGNC:4585'),('ENSG00000273079','GRIN2B','HGNC:4586')]
    all_rows=[]; coverage={}; artifacts=[]
    query=f'''query geneEvidence($id:String!,$diseases:[String!]!,$size:Int!,$cursor:String) {{ target(ensemblId:$id) {{ id approvedSymbol evidences(efoIds:$diseases,size:$size,cursor:$cursor) {{ count cursor rows {{ {selection} }} }} }} }}'''
    for ensembl,symbol,hgnc_id in genes:
        mondo_ids=sorted(mid for mid,items in evidence_ids.items() if any(x['gene']==symbol for x in items))
        cursor=None; page=0; total=None; count=0; visited_cursors={None}; evidence_keys=set(); reported_counts=set()
        while True:
            body={'query':query,'variables':{'id':ensembl,'diseases':mondo_ids,'size':page_size,'cursor':cursor}}
            filename=f'grin-evidence-{symbol}-page-{page:05d}.json'
            p=core.download(source,OT,filename,license_name='Open Targets Platform data; CC BY 4.0, confirm release terms',version='current GraphQL API (release ID not exposed)',method='POST',json_body=body)
            payload=_json(p)
            if payload.get('errors'): raise RuntimeError(f'Open Targets evidence query failed for {symbol} page {page}: {payload["errors"][:1]}')
            response=(payload.get('data') or {}).get('target') or {}; page_data=response.get('evidences') or {}
            reported_counts.add(int(page_data.get('count') or 0))
            if total is None: total=int(page_data.get('count') or 0)
            rows=page_data.get('rows') or []
            for row in rows:
                evidence_keys.add(row.get('id') or hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest())
                row['_focus']={'hgnc_id':hgnc_id,'approved_symbol':symbol,'ensembl_id':ensembl,'disease_identifiers':evidence_ids.get(row.get('disease',{}).get('id'),[])}
                all_rows.append(row)
            count+=len(rows); page+=1; artifacts.append(str(p.relative_to(core.ROOT)))
            cursor=page_data.get('cursor')
            if not cursor or not rows: break
            if not isinstance(cursor,str) or cursor in visited_cursors:
                raise RuntimeError('Open Targets evidence cursor repeated or is invalid; acquisition is incomplete')
            visited_cursors.add(cursor)
        coverage[symbol]={'hgnc_id':hgnc_id,'ensembl_id':ensembl,'linked_disease_ids':mondo_ids,
                          'reported_evidence_count':total,'reported_counts':sorted(reported_counts),
                          'records_acquired':count,'unique_records_acquired':len(evidence_keys),'pages':page,
                          'complete':count==total and len(evidence_keys)==total and len(reported_counts)==1}
    input_paths=[core.PROCESSED/'hgnc/hgnc_complete_set.jsonl.gz',core.PROCESSED/'clingen/gene_disease_validity.jsonl.gz',core.PROCESSED/'clingen/gene_disease_validity_lumping_splitting.jsonl.gz',core.PROCESSED/'gencc/assertions.jsonl.gz',core.PROCESSED/'hpo/genes_to_disease.jsonl.gz',core.PROCESSED/'orphadata/genes.jsonl.gz',core.PROCESSED/'mondo/obo_stanzas.jsonl.gz']
    if all_rows:
        core.emit_records(source,'grin_gene_disease_evidence',all_rows,input_paths=input_paths,description='Acquired cursor-paginated Open Targets source-native evidence records for MONDO diseases asserted/linked to GRIN2A or GRIN2B by ClinGen, GenCC, HPO or Orphadata. Evidence model scalar fields and nested first-level scalar fields were selected from the current GraphQL schema; manifest coverage records count and uniqueness gaps.')
    core.update_manifest(source,status='partial',focused_grin_evidence=coverage,focused_disease_identifiers=evidence_ids,provider_release='Current GraphQL API; release ID not exposed in response (captured 2026-10-03)',evidence_dataset={'records':len(all_rows),'pages':artifacts,'complete_for_selected_diseases':all(item['complete'] for item in coverage.values()),'selection':'All Evidence scalar fields plus nested objects\' direct scalar fields; paged until provider cursor exhausted. Per-gene coverage verifies stable provider counts and unique evidence records for the selected disease IDs.'},rights='Open Targets Platform data; provider documentation describes CC BY 4.0; review current release terms')
    return coverage

def _ot_query_batch(ids):
    fields='''id name description dbXRefs associatedTargets(page:{index:0,size:100}) { count rows { score datatypeScores { id score } datasourceScores { id score } target { id approvedSymbol } } } drugAndClinicalCandidates { count rows { id maxClinicalStage drug { id name drugType tradeNames { label source } crossReferences { ids source } description } } }'''
    aliases=[]
    for i,ident in enumerate(ids): aliases.append(f'd{i}: disease(efoId:"{ident}") {{ {fields} }}')
    return 'query rareDiseaseOpenTargets { '+' '.join(aliases)+' }'

def harvest_open_targets(batch_size=32, delay=.08):
    """Query Open Targets only for MONDO diseases joined from the rare-disease catalog."""
    source='open_targets'; membership=rare_disease_mondo_ids(); ids=sorted(membership)
    if not ids: raise RuntimeError('No rare-source diseases mapped to MONDO identifiers')
    diseases=[]; associations=[]; drugs=[]; requests_log=[]; absent=[]; errors=[]; truncated=[]; drug_truncated=[]; total_batches=(len(ids)+batch_size-1)//batch_size
    for batch_number,start in enumerate(range(0,len(ids),batch_size),1):
        batch=ids[start:start+batch_size]; query=_ot_query_batch(batch); body={'query':query}
        filename=f'graphql-rare-mondo-p100-b{batch_size}-{batch_number:05d}.json'
        try:
            p=core.download(source,OT,filename,license_name='Open Targets Platform data; CC BY 4.0, confirm release terms',version='current GraphQL API (release ID not exposed)',method='POST',json_body=body)
            payload=_json(p)
            if payload.get('errors'):
                errors.append({'batch':batch_number,'identifiers':batch,'error':payload['errors'][:2]});continue
        except Exception as e:
            errors.append({'batch':batch_number,'identifiers':batch,'error':f'{type(e).__name__}: {e}'});continue
        result=payload.get('data') or {}
        for i,ident in enumerate(batch):
            disease=result.get(f'd{i}')
            if not disease:
                absent.append(ident); continue
            disease['rare_source_identifiers']=membership[ident]
            diseases.append(disease)
            assoc=disease.get('associatedTargets') or {}
            if int(assoc.get('count') or 0)>len(assoc.get('rows') or []): truncated.append({'disease_id':ident,'reported_count':assoc.get('count'),'captured':len(assoc.get('rows') or [])})
            for row in assoc.get('rows') or []:
                associations.append({'disease_id':disease.get('id'),'disease_name':disease.get('name'),'target_association':row,'reported_association_count':assoc.get('count'),'rare_source_identifiers':membership[ident]})
            candidate=disease.get('drugAndClinicalCandidates') or {}
            if int(candidate.get('count') or 0)>len(candidate.get('rows') or []): drug_truncated.append({'disease_id':ident,'reported_count':candidate.get('count'),'captured':len(candidate.get('rows') or [])})
            for row in candidate.get('rows') or []:
                drugs.append({'disease_id':disease.get('id'),'disease_name':disease.get('name'),'clinical_candidate':row,'rare_source_identifiers':membership[ident]})
        requests_log.append({'batch':batch_number,'identifiers':len(batch),'returned_diseases':sum(1 for i in range(len(batch)) if result.get(f'd{i}')),'sha256':core.digest(p)})
        if batch_number%25==0: print(json.dumps({'event':'open_targets_progress','batch':batch_number,'total_batches':total_batches,'diseases':len(diseases),'associations':len(associations)}),flush=True)
        time.sleep(delay)
    source_paths=[core.PROCESSED/'raresource/diseases.jsonl.gz',core.PROCESSED/'mondo/obo_stanzas.jsonl.gz']
    core.emit_records(source,'rare_diseases',diseases,input_paths=source_paths,description='Open Targets disease descriptions, xrefs, initial associated-target page and drug/clinical candidate metadata for MONDO IDs cross-linked from RareSource OMIM/Orphanet identifiers. The target_associations dataset separately contains reconciled aggregate association rows.')
    if associations: core.emit_records(source,'target_associations',associations,input_paths=[core.RAW/source],description='Open Targets aggregate target-disease association scores and per-datatype/per-datasource score contributions; these are platform aggregates, not full underlying source assertions.')
    if drugs: core.emit_records(source,'drug_candidates',drugs,input_paths=[core.RAW/source],description='Open Targets clinical candidate records exposed on each matched rare disease, with native drug identifiers, cross-references and clinical-stage metadata.')
    version='current GraphQL API; release ID not exposed in API response'
    core.update_manifest(source,status='partial',provider_release=version,coverage={'rare_source_rows':7200,'mondo_diseases_queried':len(ids),'diseases_returned':len(diseases),'diseases_not_found':absent,'target_associations_captured':len(associations),'diseases_with_over_100_target_associations':truncated,'drug_candidates_captured':len(drugs),'diseases_with_truncated_drug_candidates':drug_truncated,'batches':requests_log,'failed_batches':errors,'limitation':'Partial targeted slice of Open Targets: aggregate associated-target top 100 per disease only (provider full counts preserved), plus candidate drugs exposed by the API. Source-native evidence records are harvested separately for GRIN2A/GRIN2B. Disease coverage depends on MONDO xref links from RareSource OMIM/Orphanet identifiers.'},rights='Open Targets Platform data; provider documentation describes CC BY 4.0; review current release terms')
    return diseases

def _association_page_query(ids,index,page_size=100):
    fields='''id name associatedTargets(page:{index:%d,size:%d}) { count rows { score datatypeScores { id score } datasourceScores { id score } target { id approvedSymbol } } }'''%(index,page_size)
    aliases=[f'd{i}: disease(efoId:"{ident}") {{ {fields} }}' for i,ident in enumerate(ids)]
    return 'query rareDiseaseAssociationPage { '+' '.join(aliases)+' }'

def _association_full_query(entries):
    fields='''associatedTargets(page:{index:0,size:%d},orderByScore:"score desc") { count rows { score datatypeScores { id score } datasourceScores { id score } target { id approvedSymbol } } }'''
    aliases=[f'd{i}: disease(efoId:"{ident}") {{ id {fields % max(1,int(size))} }}' for i,(ident,size) in enumerate(entries)]
    return 'query rareDiseaseAssociationFull { '+' '.join(aliases)+' }'

def _association_prefix_query(entries,page_size=3000):
    fields='''associatedTargets(page:{index:0,size:%d},BFilter:"%s",orderByScore:"score desc") { count rows { score datatypeScores { id score } datasourceScores { id score } target { id approvedSymbol } } }'''
    aliases=[f'd{i}: disease(efoId:"{ident}") {{ id {fields % (page_size,prefix)} }}' for i,(ident,prefix) in enumerate(entries)]
    return 'query rareDiseaseAssociationPrefix { '+' '.join(aliases)+' }'

def _initial_association_records(disease_rows):
    """Flatten immutable provider page-zero rows embedded in disease records."""
    for disease in disease_rows:
        ident=disease.get('id')
        if not ident: continue
        assoc=disease.get('associatedTargets') or {}; reported=assoc.get('count')
        for row in assoc.get('rows') or []:
            yield {'disease_id':ident,'disease_name':disease.get('name'),'target_association':row,'reported_association_count':reported,'page_index':0,'rare_source_identifiers':disease.get('rare_source_identifiers')}

def _association_audit_complete(row_count,expected_count,audit):
    mismatches=(audit or {}).get('distinct_target_count_mismatches',(audit or {}).get('diseases_with_distinct_target_count_mismatch'))
    return bool(audit and mismatches==0 and audit.get('duplicate_rows')==0 and row_count==expected_count)

def _association_prefix_children(prefix,count,page_size=3000):
    """Return disjoint digit-prefix partitions when a filtered page is capped."""
    return [prefix+str(digit) for digit in range(10)] if int(count)>page_size else []

def _prefix_partition_complete(parent_count,child_counts):
    return sum(int(x) for x in child_counts)==int(parent_count)

def harvest_open_targets_uniqueness_repair(batch_size=8,page_size=3000,delay=.05):
    """Replace tie-unstable offset pages with complete single-page/prefix partitions."""
    source='open_targets'; root=core.PROCESSED/source; by_id={}
    for r in core.read_records(root/'rare_diseases.jsonl.gz'):
        if r.get('id'): by_id[r['id']]={'id':r['id'],'name':r.get('name'),'rare_source_identifiers':r.get('rare_source_identifiers'),'associatedTargets':{'count':(r.get('associatedTargets') or {}).get('count')}}
    unique_by_disease=defaultdict(set); original_rows=0
    for row in core.read_records(root/'target_associations.jsonl.gz'):
        original_rows+=1
        association=row.get('target_association') or {}; target=association.get('target') or {}
        if row.get('disease_id') and target.get('id'): unique_by_disease[row['disease_id']].add(target['id'])
    original_distinct=sum(len(targets) for targets in unique_by_disease.values())
    original_audit={'rows':original_rows,'distinct_disease_target_pairs':original_distinct,'duplicate_rows':original_rows-original_distinct,'diseases_audited':len(by_id)}
    affected=[]
    for ident,disease in by_id.items():
        expected=int((disease.get('associatedTargets') or {}).get('count') or 0)
        if len(unique_by_disease.get(ident,set()))!=expected: affected.append((ident,expected))
    del unique_by_disease
    if not affected:
        expected=sum(int((r.get('associatedTargets') or {}).get('count') or 0) for r in by_id.values())
        audit={'rows':original_rows,'distinct_disease_target_pairs':original_distinct,'duplicate_rows':original_rows-original_distinct,'diseases_audited':len(by_id),'distinct_target_count_mismatches':0,'diseases_with_distinct_target_count_mismatch':0,'initial_offset_page_audit':(core.manifest(source).get('coverage') or {}).get('original_offset_page_overlap_audit',original_audit),'current_pre_repair_audit':original_audit,'repair':{'affected_diseases':0,'repaired_diseases':0,'requests':0,'root_partitions_verified':0,'parent_prefix_partitions':0,'parent_prefix_partitions_verified':0,'query_failures':[]}}
        manifest=core.manifest(source); coverage=manifest.get('coverage') or {}; coverage['target_association_uniqueness_audit']=audit
        complete=_association_audit_complete(original_rows,expected,audit); coverage['target_association_coverage_complete']=complete
        core.update_manifest(source,status='partial',coverage=coverage,association_dataset={'records_expected':expected,'records_emitted':original_rows,'unique_disease_target_pairs':original_distinct,'duplicate_rows':original_rows-original_distinct,'distinct_target_count_mismatches':0,'complete_for_returned_diseases':complete})
        return {'rows':original_rows,'distinct_pairs':original_distinct,'duplicates':original_rows-original_distinct,'repaired_diseases':0,'mismatches':0,'failures':[],'calls':0}
    repaired={}; failures=[]; raw_paths=[]; calls=0
    def raw_name(prefix,body):
        digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
        return f'{prefix}-{digest}.json'
    def fetch_body(filename_prefix,query):
        nonlocal calls
        body={'query':query}; filename=raw_name(filename_prefix,body)
        # Reuse an earlier artifact only on exact request-body match and a valid
        # recorded checksum. This safely migrates the first live run's indexed
        # filenames without replacing its provenance or issuing duplicate calls.
        prior=core.manifest(source).get('artifacts') or {}
        for old_name,metadata in prior.items():
            if metadata.get('url')==core.safe_url(OT) and metadata.get('method','GET')=='POST' and metadata.get('request_body')==body:
                old_path=core.RAW/source/old_name
                if old_path.exists() and core.digest(old_path)==metadata.get('sha256'):
                    calls+=1; raw_paths.append(str(old_path.relative_to(core.ROOT)))
                    return _json(old_path),old_name
        calls+=1
        p=core.download(source,OT,filename,license_name='Open Targets Platform data; CC BY 4.0, confirm release terms',version='current GraphQL API (release ID not exposed)',method='POST',json_body=body)
        raw_paths.append(str(p.relative_to(core.ROOT)))
        return _json(p),filename
    # One response per disease fits in one page when provider count <= 3,000.
    small=[x for x in affected if x[1]<=page_size]
    def process_full(group):
        if not group: return
        try:
            payload,filename=fetch_body('target-associations-unique-full',_association_full_query(group))
            if payload.get('errors'):
                if len(group)>1:
                    midpoint=len(group)//2; process_full(group[:midpoint]); process_full(group[midpoint:]); return
                retry_query=_association_full_query(group)+'\n# bounded retry to bypass cached GraphQL error'
                payload,filename=fetch_body('target-associations-unique-full-retry',retry_query)
                if payload.get('errors'):
                    failures.append({'disease_ids':[x[0] for x in group],'error':payload['errors'][:2],'file':filename}); return
            data=payload.get('data') or {}
            for i,(ident,expected) in enumerate(group):
                disease=data.get(f'd{i}') or {}; assoc=disease.get('associatedTargets') or {}; rows=assoc.get('rows') or []
                targets=[((r.get('target') or {}).get('id')) for r in rows]; distinct=set(x for x in targets if x)
                if disease.get('id')!=ident or int(assoc.get('count') or -1)!=expected or len(rows)!=expected or len(distinct)!=expected:
                    failures.append({'disease_id':ident,'expected':expected,'provider_count':assoc.get('count'),'rows':len(rows),'distinct_targets':len(distinct),'file':filename})
                else: repaired[ident]=[(filename,f'd{i}',None)]
        except Exception as e:
            if len(group)>1:
                midpoint=len(group)//2; process_full(group[:midpoint]); process_full(group[midpoint:]); return
            failures.append({'disease_ids':[x[0] for x in group],'error':f'{type(e).__name__}: {e}'})
        if calls%25==0: print(json.dumps({'event':'open_targets_uniqueness_progress','calls':calls,'repaired':len(repaired),'affected':len(affected),'failures':len(failures)}),flush=True)
        time.sleep(delay)
    for offset in range(0,len(small),batch_size): process_full(small[offset:offset+batch_size])
    # Larger disease sets are partitioned on target ID prefixes until every
    # response fits in one page, avoiding unstable score-tie boundaries.
    large=[(ident,count) for ident,count in affected if count>page_size]
    pending=[(ident,f'ENSG00000{i}',count) for ident,count in large for i in range(4)]
    root_counts=defaultdict(int); prefix_counts=defaultdict(int); parent_counts={}; child_counts=defaultdict(int); large_failed=set()
    def process_prefix(group):
        if not group: return
        try:
            payload,filename=fetch_body('target-associations-unique-prefix',_association_prefix_query([(d,pref) for d,pref,_ in group],page_size))
            if payload.get('errors'):
                if len(group)>1:
                    midpoint=len(group)//2; process_prefix(group[:midpoint]); process_prefix(group[midpoint:]); return
                retry_query=_association_prefix_query([(d,pref) for d,pref,_ in group],page_size)+'\n# bounded retry to bypass cached GraphQL error'
                payload,filename=fetch_body('target-associations-unique-prefix-retry',retry_query)
                if payload.get('errors'):
                    failures.append({'disease_prefixes':[(x[0],x[1]) for x in group],'error':payload['errors'][:2],'file':filename}); large_failed.update(x[0] for x in group); return
            data=payload.get('data') or {}
            for i,(ident,prefix,parent_count) in enumerate(group):
                disease=data.get(f'd{i}') or {}; assoc=disease.get('associatedTargets') or {}; rows=assoc.get('rows') or []; count=int(assoc.get('count') or 0)
                if disease.get('id')!=ident or len(rows)!=min(page_size,count):
                    failures.append({'disease_id':ident,'prefix':prefix,'provider_count':count,'rows':len(rows),'error':'prefix page count mismatch','file':filename}); large_failed.add(ident); continue
                if len(rows)>page_size: failures.append({'disease_id':ident,'prefix':prefix,'error':'API exceeded single-page size','file':filename}); large_failed.add(ident); continue
                if prefix in ('ENSG000000','ENSG000001','ENSG000002','ENSG000003'): root_counts[ident]+=count
                if len(prefix)>len('ENSG00000')+1:
                    parent=prefix[:-1]
                    child_counts[(ident,parent)]+=count
                if count>page_size:
                    parent_counts[(ident,prefix)]=count
                    children=_association_prefix_children(prefix,count,page_size)
                    process_prefix([(ident,child,count) for child in children])
                else:
                    for row in rows:
                        target=((row.get('target') or {}).get('id'))
                        if not target or not target.startswith(prefix): failures.append({'disease_id':ident,'prefix':prefix,'target_id':target,'error':'returned target does not match prefix','file':filename}); large_failed.add(ident)
                    prefix_counts[ident]+=count
                    repaired.setdefault(ident,[]).append((filename,f'd{i}',prefix))
        except Exception as e:
            if len(group)>1:
                midpoint=len(group)//2; process_prefix(group[:midpoint]); process_prefix(group[midpoint:]); return
            failures.append({'disease_prefixes':[(x[0],x[1]) for x in group],'error':f'{type(e).__name__}: {e}'})
            large_failed.update(x[0] for x in group)
        if calls%25==0: print(json.dumps({'event':'open_targets_uniqueness_progress','calls':calls,'repaired':len(repaired),'affected':len(affected),'failures':len(failures)}),flush=True)
        time.sleep(delay)
    for offset in range(0,len(pending),batch_size): process_prefix(pending[offset:offset+batch_size])
    for (ident,prefix),count in parent_counts.items():
        if not _prefix_partition_complete(count,[child_counts.get((ident,prefix),0)]):
            failures.append({'disease_id':ident,'parent_prefix':prefix,'parent_count':count,'child_count_sum':child_counts.get((ident,prefix),0),'error':'child prefix counts do not sum to parent prefix count'})
            large_failed.add(ident)
    for ident,count in large:
        if root_counts.get(ident)!=count or prefix_counts.get(ident)!=count:
            failures.append({'disease_id':ident,'provider_count':count,'root_prefix_count':root_counts.get(ident,0),'leaf_prefix_count':prefix_counts.get(ident,0),'error':'target-prefix counts do not sum to provider count'})
            large_failed.add(ident)
    for ident in large_failed: repaired.pop(ident,None)
    # Keep the original page artifacts intact; replace only disease rows in the
    # normalized data with validated one-page responses or disjoint prefixes.
    def repaired_records():
        for ident,parts in repaired.items():
            for filename,alias,prefix in parts:
                payload=_json(core.RAW/source/filename); sub=(payload.get('data') or {}).get(alias) or {}
                if sub.get('id')!=ident: continue
                for assoc in (sub.get('associatedTargets') or {}).get('rows') or []:
                    yield {'disease_id':ident,'disease_name':by_id[ident].get('name'),'target_association':assoc,'reported_association_count':int((by_id[ident].get('associatedTargets') or {}).get('count') or 0),'page_index':0,'partition_prefix':prefix}
    repaired_ids=set(repaired)
    def all_rows():
        for row in core.read_records(root/'target_associations.jsonl.gz'):
            if row.get('disease_id') not in repaired_ids: yield row
        yield from repaired_records()
    expected_total=sum(int((r.get('associatedTargets') or {}).get('count') or 0) for r in by_id.values())
    out=core.emit_records(source,'target_associations',all_rows(),input_paths=[root/'rare_diseases.jsonl.gz',core.RAW/source],description='All Open Targets aggregate target-disease associations for returned RareSource-mapped MONDO diseases. Tie-unstable offset pages were replaced for audited discrepancies using a single full page (<=3,000) or disjoint target-ID prefix partitions; score/source components are retained.')
    # Final exact uniqueness audit, distinct target count compared with provider.
    final_pairs=defaultdict(set); final_rows=0
    for row in core.read_records(out):
        final_rows+=1; target=((row.get('target_association') or {}).get('target') or {}).get('id')
        if target: final_pairs[row['disease_id']].add(target)
    mismatch=[]
    for ident,disease in by_id.items():
        reported=int((disease.get('associatedTargets') or {}).get('count') or 0); distinct=len(final_pairs.get(ident,set()))
        if reported!=distinct: mismatch.append({'disease_id':ident,'provider_count':reported,'distinct_targets':distinct,'delta':distinct-reported})
    manifest=core.manifest(source); coverage=manifest.get('coverage') or {}
    distinct_pairs=sum(map(len,final_pairs.values())); duplicate_rows=final_rows-distinct_pairs
    original_page_audit=coverage.get('original_offset_page_overlap_audit',original_audit)
    audit={'rows':final_rows,'distinct_disease_target_pairs':distinct_pairs,'duplicate_rows':duplicate_rows,'diseases_audited':len(by_id),'distinct_target_count_mismatches':len(mismatch),'diseases_with_distinct_target_count_mismatch':len(mismatch),'mismatch_details':mismatch,'initial_offset_page_audit':original_page_audit,'current_pre_repair_audit':original_audit,'repair':{'affected_diseases':len(affected),'repaired_diseases':len(repaired_ids),'requests':calls,'root_partitions':4,'root_partitions_verified':len(large)-sum(1 for ident,count in large if root_counts.get(ident)!=count or prefix_counts.get(ident)!=count),'parent_prefix_partitions_verified':len(parent_counts)-sum(1 for (ident,prefix),count in parent_counts.items() if child_counts.get((ident,prefix),0)!=count),'parent_prefix_partitions':len(parent_counts),'parent_prefix_count_mismatches':[{'disease_id':ident,'prefix':prefix,'parent_count':count,'children_sum':child_counts.get((ident,prefix),0)} for (ident,prefix),count in parent_counts.items() if child_counts.get((ident,prefix),0)!=count],'root_partition_count_mismatches':[{'disease_id':ident,'provider_count':count,'root_sum':root_counts.get(ident,0),'leaf_sum':prefix_counts.get(ident,0)} for ident,count in large if root_counts.get(ident)!=count or prefix_counts.get(ident)!=count],'root_prefixes':['ENSG000000','ENSG000001','ENSG000002','ENSG000003'],'query_failures':failures}}
    coverage['target_association_uniqueness_audit']=audit
    coverage['target_associations_captured']=final_rows
    coverage['target_association_coverage_complete']=_association_audit_complete(final_rows,expected_total,audit) and not failures
    core.update_manifest(source,status='partial',coverage=coverage,association_dataset={'path':str(out.relative_to(core.ROOT)),'records_expected':expected_total,'records_emitted':final_rows,'unique_disease_target_pairs':audit['distinct_disease_target_pairs'],'duplicate_rows':audit['duplicate_rows'],'distinct_target_count_mismatches':len(mismatch),'failed_repair_queries':failures,'complete_for_returned_diseases':coverage['target_association_coverage_complete']})
    return {'rows':final_rows,'distinct_pairs':audit['distinct_disease_target_pairs'],'duplicates':audit['duplicate_rows'],'repaired_diseases':len(repaired_ids),'mismatches':len(mismatch),'failures':failures,'calls':calls}

def harvest_open_targets_association_pages(batch_size=32,page_size=100,delay=.08):
    """Fetch every remaining aggregate association page for all resolved rare diseases."""
    source='open_targets'; disease_rows=list(core.read_records(core.PROCESSED/source/'rare_diseases.jsonl.gz'))
    by_id={r['id']:r for r in disease_rows if r.get('id')}
    work=[]
    for ident,row in by_id.items():
        count=int((row.get('associatedTargets') or {}).get('count') or 0)
        for index in range(1,(count+page_size-1)//page_size): work.append((index,ident,count))
    pages=defaultdict(list)
    for index,ident,count in work: pages[index].append((ident,count))
    failed=[];completed=[];received=0;total_calls=sum((len(v)+batch_size-1)//batch_size for v in pages.values())
    call_no=0
    for index in sorted(pages):
        eligible=pages[index]
        for offset in range(0,len(eligible),batch_size):
            group=eligible[offset:offset+batch_size]; ids=[x[0] for x in group]; query=_association_page_query(ids,index,page_size)
            filename=f'target-associations-page-{index:03d}-batch-{offset//batch_size:04d}.json'
            call_no+=1; body={'query':query}
            try:
                p=core.download(source,OT,filename,license_name='Open Targets Platform data; CC BY 4.0, confirm release terms',version='current GraphQL API (release ID not exposed)',method='POST',json_body=body)
                payload=_json(p)
                if payload.get('errors'): raise RuntimeError(str(payload['errors'][:1]))
                data=payload.get('data') or {}; page_counts={}
                for i,(ident,total_count) in enumerate(group):
                    item=data.get(f'd{i}')
                    if not item: failed.append({'disease_id':ident,'page_index':index,'expected':min(page_size,max(0,total_count-index*page_size)),'error':'No disease returned'});continue
                    result=item.get('associatedTargets') or {}; rows=result.get('rows') or []
                    expected=min(page_size,max(0,total_count-index*page_size))
                    page_counts[ident]={'expected':expected,'received':len(rows),'reported_total':result.get('count')}
                    received+=len(rows)
                    if len(rows)!=expected or int(result.get('count') or -1)!=total_count:
                        failed.append({'disease_id':ident,'page_index':index,**page_counts[ident]})
                completed.append({'page_index':index,'offset':offset,'disease_count':len(group),'path':str(p.relative_to(core.ROOT)),'records_received':sum(v['received'] for v in page_counts.values()),'record_counts':page_counts})
            except Exception as e:
                failed.append({'page_index':index,'offset':offset,'disease_ids':ids,'error':f'{type(e).__name__}: {e}'})
            if call_no%50==0: print(json.dumps({'event':'open_targets_associations_progress','calls':call_no,'total_calls':total_calls,'records_received':received,'failed_pages':len(failed)}),flush=True)
            time.sleep(delay)
    # Rebuild the flattened association dataset from the original first pages and
    # every successfully downloaded continuation page, streaming into gzip JSONL.
    def all_associations():
        yield from _initial_association_records(disease_rows)
        for call in completed:
            p=core.ROOT/call['path']; payload=_json(p); data=payload.get('data') or {}
            # group indices match the serialized alias order for this page/call.
            group=pages[call['page_index']][call['offset']:call['offset']+batch_size]
            for i,(ident,total_count) in enumerate(group):
                disease=by_id[ident]; sub=data.get(f'd{i}')
                if not sub: continue
                result=sub.get('associatedTargets') or {}
                for association in result.get('rows') or []:
                    yield {'disease_id':ident,'disease_name':disease.get('name'),'target_association':association,'reported_association_count':total_count,'page_index':call['page_index'],'rare_source_identifiers':disease.get('rare_source_identifiers')}
    count=sum(int((row.get('associatedTargets') or {}).get('count') or 0) for row in disease_rows)
    first_page_count=sum(len((row.get('associatedTargets') or {}).get('rows') or []) for row in disease_rows)
    expected_continuation=count-first_page_count
    continuation_complete=not failed and received==expected_continuation
    out=core.emit_records(source,'target_associations',all_associations(),input_paths=[core.PROCESSED/source/'rare_diseases.jsonl.gz',core.RAW/source],description='All Open Targets aggregate target-disease association pages for every returned MONDO disease in the RareSource-mapped query set. Each association retains provider overall score, datatype scores, datasource scores, target ID/symbol, disease ID/name, reported count and page index.')
    manifest=core.manifest(source); coverage=manifest.get('coverage') or {}
    coverage.update({'target_associations_expected_total':count,'target_associations_first_page_records':first_page_count,'target_association_continuation_expected_records':expected_continuation,'target_association_continuation_records':received,'target_association_continuation_calls':len(completed),'target_association_expected_calls':total_calls,'target_association_failed_pages':failed,'target_association_page_size':page_size,'target_association_continuation_complete':continuation_complete,'target_association_coverage_complete':False,'target_association_uniqueness_audit':{'required_before_complete':True,'invalidated_by_continuation_rerun':True},'resolved_disease_ids':len(by_id),'mapped_mondo_ids_not_returned':len(coverage.get('diseases_not_found') or []),'limitation':'All aggregate association pages are acquired for returned disease IDs only. Completeness requires exact distinct-target uniqueness audit; offset pages can overlap when score ties occur, so discrepant diseases require full-page/prefix repair. The 1,342 MONDO IDs in the input crosswalk that did not resolve remain unknown for Open Targets; full source-native evidence is separately complete only for the focused GRIN2A/GRIN2B disease identifiers.'})
    core.update_manifest(source,status='partial',coverage=coverage,association_dataset={'path':str(out.relative_to(core.ROOT)),'records_expected':count,'records_emitted':first_page_count+received,'first_page_records':first_page_count,'continuation_records':received,'failed_pages':failed,'complete_for_returned_diseases':False})
    return {'expected':count,'continuation_records':received,'failed_pages':failed,'calls':len(completed),'expected_calls':total_calls}

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('source',choices=['grants_gov','open_targets','open_targets_association_pages','open_targets_uniqueness_repair','grin_evidence','all']);args=ap.parse_args()
    jobs={'grants_gov':harvest_grants_gov,'open_targets':harvest_open_targets,'open_targets_association_pages':harvest_open_targets_association_pages,'open_targets_uniqueness_repair':harvest_open_targets_uniqueness_repair,'grin_evidence':harvest_grin_evidence}
    for name in jobs if args.source=='all' else [args.source]:
        print(json.dumps({'event':'source_started','source':name}),flush=True)
        try: jobs[name]()
        except Exception as e:
            core.update_manifest(name,status='failed',failure={'type':type(e).__name__,'error':str(e)})
            print(json.dumps({'event':'source_failed','source':name,'error':str(e)}),flush=True)

if __name__=='__main__': main()

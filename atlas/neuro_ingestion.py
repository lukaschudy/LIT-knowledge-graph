"""Build a bounded, reproducible neuro identity/evidence layer over the full harvest."""
from __future__ import annotations
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import gzip
import json
from pathlib import Path
import re
import sqlite3

from .harvest_graph.source_reader import read_record
from .harvest_graph.store import HarvestGraph


def stable(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def save_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def paper_records(harvest, documents, cache_path):
    """Resolve each paper from actual PMCID fields, never by title similarity."""
    wanted = {re.search(r'/articles/(PMC\d+)', d['url']).group(1) for d in documents}
    ds = next(d for d in harvest.datasets() if d['key'] == 'europe_pmc_diseases/articles')
    signature = [ds['sha256'], ds['dataset_id'], ds['path'], sorted(wanted)]
    cache_path = Path(cache_path)
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get('signature') == signature: return cached['records']
    needles = [x.encode() for x in wanted]; records = []
    with gzip.open(harvest.source_root / ds['path'], 'rb') as stream:
        for line_number, line in enumerate(stream, 1):
            if not any(needle in line for needle in needles): continue
            record = json.loads(line)
            if record.get('pmcid') in wanted:
                records.append({'data': record, 'pointer': harvest.record(ds['dataset_id'], line_number)})
    # Missing metadata does not justify guessing DOI, PMID, or author identities.
    save_json(cache_path, {'signature': signature, 'records': records})
    return records


def prepare_neuro(root, harvest, output_directory, *, neighbor_limit=180):
    root, output_directory = Path(root), Path(output_directory)
    curated = json.loads((root / 'data/curated/neuro_bundle.json').read_text())
    documents = json.loads((root / 'data/curated/neuro_documents.json').read_text())
    config = json.loads((root / 'data/curated/neuro-identities.json').read_text())
    nodes = {n['id']: deepcopy(n) for n in curated['nodes']}
    claims, links, seeds = {}, [], []
    def node(identifier, kind, label, provenance=None):
        if identifier not in nodes:
            nodes[identifier] = {'id': identifier, 'type': kind, 'label': label, 'aliases': [], 'properties': {}}
        if provenance: nodes[identifier].setdefault('provenance', provenance)
        return identifier
    def identity(a,b,rule,proof):
        links.append({'subject':a,'object':b,'rule':rule,'provenance':proof})
    for anchor in config['anchors']:
        canonical = harvest.node(anchor['registry_id'])
        if canonical is None or canonical['type'] != anchor['type'] or canonical['label'] != anchor['registry_label']:
            raise ValueError('Registry anchor differs from checked identity: ' + anchor['registry_id'])
        nodes[canonical['id']] = canonical; seeds.append(canonical['id'])
        proof = canonical['provenance']
        identity(anchor['local_id'], canonical['id'], 'curated_identifier',
                 {'mapping':'data/curated/neuro-identities.json','record':proof})
        row = read_record(harvest.path, harvest.source_root, proof)['data']
        aliases = []
        if anchor['type'] == 'Gene':
            for field, prefix in [('ensembl_gene_id',''),('entrez_id','NCBIGene:'),('omim_id','OMIM:')]:
                for value in re.split(r'[|,;\s]+', str(row.get(field) or '')):
                    if value: aliases.append((prefix + value, field))
        else:
            # MONDO distinguishes equivalence from broad/related db crossrefs.
            for value in row.get('tags',{}).get('property_value',[]):
                match = re.match(r'skos:exactMatch (\S+)', value)
                if match:
                    identifier = match.group(1).replace('MEDGEN:', 'MedGen:').replace('MESH:', 'MeSH:')
                    aliases.append((identifier, value))
        for alias, field in aliases:
            existing = harvest.node(alias)
            if existing: nodes[alias] = existing
            else: node(alias, anchor['type'], canonical['label'], proof)
            identity(canonical['id'], alias, 'registry_same_as', {'record':proof,'field':field})
        # Seed representatives from each registry identity so disease annotations
        # attached to OMIM/Orphanet survive canonicalization.
        for identifier in [canonical['id'], *[a for a,_ in aliases]]:
            view = harvest.graph(focus=identifier,limit=neighbor_limit)
            nodes.update({n['id']:n for n in view['nodes']})
            claims.update({c['id']:c for c in view['claims'] if c['predicate'] != 'SAME_AS'})
        if anchor['type'] == 'Gene':
            # Include actual stable variants explicitly, not just the first GO/HPO
            # edges in the source ordering. Distinct ClinVar IDs stay distinct.
            with closing(sqlite3.connect(harvest.path)) as conn:
                rows = conn.execute('SELECT e.eid,s.id FROM nodes g JOIN edges e ON e.object=g.nid '
                    'JOIN nodes s ON s.nid=e.subject WHERE g.id=? AND s.type=\'Variant\' ORDER BY e.eid LIMIT 40',
                    (canonical['id'],)).fetchall()
            for eid, identifier in rows:
                nodes[identifier] = harvest.node(identifier)
                claim = harvest.claim(f'harvest:edge:{eid}'); claims[claim['id']] = claim
    records = paper_records(harvest, documents, output_directory / 'paper-records.json')
    found = {item['data']['pmcid'] for item in records}
    for doc in documents:
        pmcid = re.search(r'/articles/(PMC\d+)', doc['url']).group(1)
        if pmcid not in found:
            identifier = 'PMCID:' + pmcid
            node(identifier, 'Publication', doc['title'], {'source_id':doc['source_id'], 'url':doc['url'], 'version':doc['version'], 'field':'url'})
            nodes[identifier]['properties']['metadata_status'] = 'PMCID from supplied source URL; author and DOI metadata unavailable'
            seeds.append(identifier); doc['publication_id'] = identifier
    seeds.extend(n['id'] for n in curated['nodes'] if n['type'] in {'Asset','Mechanism'})
    metadata_claims, metadata_evidence, metadata_sources = [], [], []
    for item in records:
        row, pointer = item['data'], item['pointer']
        pmid, pmcid, doi = row.get('pmid'), row.get('pmcid'), row.get('doi')
        identifiers = ([f'PMID:{pmid}'] if pmid else []) + ([f'PMCID:{pmcid}'] if pmcid else [])
        if doi: identifiers.append('DOI:' + doi.lower().removeprefix('https://doi.org/'))
        primary = identifiers[0]; seeds.append(primary)
        for identifier in identifiers: node(identifier,'Publication',row.get('title') or identifier,pointer)
        for identifier in identifiers[1:]: identity(primary,identifier,'publication_identifiers',{'record':pointer,'fields':['pmid','pmcid','doi']})
        doc = next(d for d in documents if pmcid in d['url'])
        doc['publication_id'] = primary
        text = json.dumps(row,sort_keys=True,ensure_ascii=False)
        version = sha256(text.encode()).hexdigest(); sid='source:metadata:'+stable([pointer['sha256'],pointer['row']])
        metadata_sources.append({'id':sid,'title':row.get('title',primary)+' — publication metadata',
                                 'url':f'https://europepmc.org/article/MED/{pmid}' if pmid else doc['url'],
                                 'version':version,'kind':'database','license':'Source metadata; see record receipt',
                                 'record':pointer,'text':text})
        for index, author in enumerate(row.get('authorList',{}).get('author',[])):
            name = author.get('fullName') or ' '.join(str(author.get(k) or '') for k in ['firstName','lastName']).strip()
            if not name: continue
            aids=author.get('authorId') or []; aids=[aids] if isinstance(aids,dict) else aids
            orcid=next((str(a.get('value','')).removeprefix('https://orcid.org/') for a in aids if a.get('type','').upper()=='ORCID'),None)
            if orcid and not re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]',orcid): orcid=None
            person='ORCID:'+orcid if orcid else 'person:source:'+stable([primary,index,name])
            node(person,'Person',name,{'record':pointer,'field':f'authorList.author[{index}]'})
            nodes[person]['properties'].update({'resolution_status':'stable_identifier' if orcid else 'unresolved_source_mention',
                                               'identity_note':'ORCID identifier' if orcid else 'Paper-scoped author; equal names in other papers are not merged.'})
            quoted=json.dumps(author,sort_keys=True,ensure_ascii=False); start=text.index(quoted)
            cid='resolved:claim:'+stable([sid,person,'AUTHORED',primary])
            metadata_claims.append({'id':cid,'subject':person,'predicate':'AUTHORED','object':primary,
                                    'assertion_type':'reported','extraction_confidence':None,'context':{'method':'structured_publication_metadata'}})
            metadata_evidence.append({'id':'evidence:'+stable(cid),'claim_id':cid,'source_id':sid,'source_version':version,
                                      'locator':f'characters [{start},{start+len(quoted)})','start':start,'end':start+len(quoted),
                                      'excerpt':quoted,'stance':'supports','review_status':'unreviewed'})
    return {'nodes':list(nodes.values()),'claims':list(claims.values())+metadata_claims+curated['claims'],'links':links,
            'evidence':metadata_evidence+curated['evidence'],'sources':metadata_sources+curated['sources'],'documents':documents,'seeds':seeds,
            'harvest_snapshot':harvest.status()['stats'], 'scope':config['scope']}


def validate_projection(bundle):
    """Verify the artifact boundary, including cache reuse and curated evidence."""
    def unique(rows, kind):
        result={row['id']:row for row in rows}
        if len(result)!=len(rows): raise ValueError('Duplicate '+kind+' identifiers in resolved layer')
        return result
    nodes=unique(bundle['nodes'],'entity'); claims=unique(bundle['claims'],'claim')
    sources=unique(bundle['sources'],'source'); unique(bundle['evidence'],'evidence')
    for claim in claims.values():
        if claim['subject'] not in nodes or claim['object'] not in nodes:
            raise ValueError('Resolved relationship has a missing entity')
        if claim['id'].startswith('claim:extracted:'):
            from .entity_extraction import _PREDICATES
            endpoints=_PREDICATES.get(claim['predicate'])
            if not endpoints or nodes[claim['subject']]['type'] not in endpoints[0] or nodes[claim['object']]['type'] not in endpoints[1]:
                raise ValueError('Extracted relationship has incompatible resolved entity types')
    for row in bundle['evidence']:
        if row['claim_id'] not in claims or row['source_id'] not in sources:
            raise ValueError('Resolved evidence has a missing claim/source')
        source=sources[row['source_id']]; text=source.get('text','')
        digest=sha256(text.encode()).hexdigest()
        if (digest!=row.get('source_version') or digest!=source.get('version') or
                not row.get('excerpt') or text.count(row['excerpt'])!=1):
            raise ValueError('Resolved evidence does not match its source snapshot: '+row['id'])
    for node in nodes.values():
        proof=node.get('properties',{}).get('provenance',{})
        if node['id'].startswith('mention:'):
            source=sources.get(proof.get('source_id'),{}); text=source.get('text','')
            if (sha256(text.encode()).hexdigest()!=proof.get('source_version') or
                    not proof.get('excerpt') or text.count(proof['excerpt'])!=1):
                raise ValueError('Entity mention does not match its source snapshot: '+node['id'])
    if not set(bundle['resolution']['alias_map'].values())<=nodes.keys():
        raise ValueError('Resolved identity points to a missing entity')


def extraction_signature(document, nodes, client):
    from .ai import DEFAULT_MODEL
    return stable([document,[{k:n.get(k) for k in ('id','type','label','aliases')} for n in nodes],
                   sha256(Path(__file__).with_name('entity_extraction.py').read_bytes()).hexdigest(),
                   getattr(client,'provider',None),getattr(client,'model',None) or DEFAULT_MODEL])


def build_neuro(root, harvest_path, output, *, client=None, extract=True, progress=None):
    from .resolution import resolve_entities
    root,output=Path(root),Path(output)
    with closing(sqlite3.connect(harvest_path)) as conn:
        source_root=conn.execute("SELECT value FROM metadata WHERE key='source_root'").fetchone()[0]
        snapshot=conn.execute("SELECT value FROM metadata WHERE key='build_id'").fetchone()[0]
    harvest=HarvestGraph(harvest_path,source_root)
    prepared=prepare_neuro(root,harvest,output.parent)
    resolved=resolve_entities(prepared['nodes'],prepared['links'])
    model_runs=[]; extraction_nodes=[]; extra_claims=[]; evidence=list(prepared['evidence']); sources=list(prepared['sources'])
    if extract:
        from .entity_extraction import extract_entities_and_relationships
        from .ai import ModelClient
        client=client or ModelClient('codex')
        cache_dir=output.parent/'entity-extractions'; cache_dir.mkdir(parents=True,exist_ok=True)
        allowed=[n for n in resolved['nodes'] if n['type'] in {'Gene','Disease','Mechanism','Asset','Publication','Organization'}]
        allowed=sorted(allowed,key=lambda n:(n['id'] not in {resolved['alias_map'].get(x,x) for x in prepared['seeds']},n['id']))[:80]
        for document in prepared['documents']:
            signature=extraction_signature(document,allowed,client)
            cache=cache_dir/(signature+'.json')
            cached=cache.exists()
            if cached: result=json.loads(cache.read_text())
            else:
                if progress:progress({'stage':'extracting','source_id':document['source_id']})
                result=extract_entities_and_relationships(document,allowed,client)
                save_json(cache,result)
            extraction_nodes.extend(result['nodes']); extra_claims.extend(result['claims']); evidence.extend(result['evidence']);sources.extend(result['sources'])
            model_runs.append({'source_id':document['source_id'],'cached':cached,'metadata':result['metadata'],'claims':len(result['claims']),'entities':len(result['nodes'])})
    # Resolve again after new source-scoped entity mentions; no model proposal is
    # admitted as an identity link.
    final_nodes = {n['id']:n for n in prepared['nodes']}
    for n in extraction_nodes:
        if n['id'] in final_nodes and final_nodes[n['id']]['type'] != n['type']:
            raise ValueError('Extracted node conflicts with an existing type: ' + n['id'])
        final_nodes.setdefault(n['id'], n)
    final=resolve_entities(list(final_nodes.values()),prepared['links'])
    # Some broad association feeds bucket HPO terms as diseases. The HPO
    # namespace identifies phenotype concepts; retain the original adapter type.
    type_corrections=0
    for node in final['nodes']:
        if re.fullmatch(r'HP:\d{7}',node['id']) and node['type']!='Phenotype':
            node['properties']['type_resolution']={'source_type':node['type'],'rule':'HPO namespace identifies a phenotype term'}
            node['type']='Phenotype'; type_corrections+=1
    alias=final['alias_map']; mapped=[]
    for claim in prepared['claims']+extra_claims:
        c=deepcopy(claim);c['subject']=alias.get(c['subject'],c['subject']);c['object']=alias.get(c['object'],c['object'])
        if c['subject']!=c['object']:mapped.append(c)
    # Connect publications to entities actually discussed by grounded claims.
    # DISCUSSES describes document content; it adds no biological assertion.
    docs={d['source_id']:d for d in prepared['documents']}
    source_map={s['id']:deepcopy(s) for s in sources}
    for sid,doc in docs.items():
        source_map.setdefault(sid,{'id':sid,**{k:doc[k] for k in ('title','url','version','license')}})
        source_map[sid]['text']=doc['text']
        source_map[sid]['publication_id']=alias.get(doc['publication_id'],doc['publication_id'])
    retained={c['id']:c for c in mapped}
    evidence=[e for e in evidence if e['claim_id'] in retained]
    content_links={}; content_evidence=[]
    for row in evidence:
        if row['source_id'] not in docs: continue
        publication=source_map[row['source_id']]['publication_id']
        claim=retained[row['claim_id']]
        for target in (claim['subject'],claim['object']):
            if target==publication: continue
            cid='resolved:discussion:'+stable([row['source_id'],publication,target])
            if cid in content_links: continue
            content_links[cid]={'id':cid,'subject':publication,'predicate':'DISCUSSES','object':target,
                                'assertion_type':'reported','context':{'method':'grounded_source_membership'},'review_status':'unreviewed'}
            content_evidence.append({**row,'id':'evidence:'+stable(cid),'claim_id':cid,'stance':'supports','review_status':'unreviewed'})
    mapped.extend(content_links.values()); evidence.extend(content_evidence)
    sources=list(source_map.values())
    seeds=list(dict.fromkeys(alias.get(s,s) for s in prepared['seeds']))
    result={'schema_version':'1.0','dataset':{'id':'resolved:neuro','title':'Resolved neuro research neighborhood',
             'description':'Source-identified neuro entities, explicit identity decisions, and unreviewed evidence-backed relationships.',
             'synthetic':False,'created_at':datetime.now(timezone.utc).date().isoformat()},
            'nodes':final['nodes'],'claims':mapped,'evidence':evidence,'sources':sources,'coverage':[],
            'resolution':{'scope':'neuro','alias_map':alias,'decisions':final['decisions'],'conflicts':final['conflicts'],
                          'default_focus':'HGNC:29331','seeds':seeds,'harvest_snapshot_id':snapshot,
                          'stats':{'entities':len(final['nodes']),'type_corrections':type_corrections,'input_identities':len({n['id'] for n in prepared['nodes']+extraction_nodes}),
                                   'identity_merges':sum(k!=v for k,v in alias.items()),'conflicts':len(final['conflicts']),
                                   'extracted_claims':len(extra_claims),'claims':len(mapped),'evidence_rows':len(evidence),
                                   'source_documents':len(prepared['documents']),'unresolved_mentions':sum(n.get('properties',{}).get('resolution_status')=='unresolved_source_mention' for n in final['nodes'])},
                          'model_runs':model_runs}}
    validate_projection(result)
    save_json(output,result)
    if progress:progress({'stage':'complete',**result['resolution']['stats']})
    return result

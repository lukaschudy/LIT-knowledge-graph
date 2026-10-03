"""Offline adapters: preserve source assertions; do not infer biomedical equivalence.

The HPO adapter accepts the documented HPOA tabular representation. It preserves
negative annotations, frequency, onset, evidence codes, biocuration and references.
Labels for HPO terms require a separate ontology import; IDs remain explicit here.
"""
from __future__ import annotations
import csv
from hashlib import sha256
import io


def hpoa_to_bundle(text, *, source_url, retrieved_at, source_version, license):
    lines = text.splitlines()
    header_index = next((i for i,line in enumerate(lines)
        if line.lstrip('#').split('\t')[0].lower().replace('_','') in ('databaseid','database-id')), None)
    if header_index is None:
        raise ValueError('HPOA header missing (database_id or DatabaseID).')
    header = lines[header_index].lstrip('#').strip()
    records = [(i + 1, line) for i, line in enumerate(lines) if i > header_index and line and not line.startswith('#')]
    reader = csv.DictReader(io.StringIO('\n'.join([header] + [line for _, line in records])), delimiter='\t')
    normalize = lambda key: key.lower().replace('_','').replace('-','')
    required = {'databaseid','diseasename','qualifier','hpoid','reference','evidence'}
    if not required.issubset({normalize(k) for k in reader.fieldnames or []}):
        raise ValueError('HPOA columns missing: '+', '.join(sorted(required-{normalize(k) for k in reader.fieldnames or []})))
    source_id='source:hpoa:'+sha256((source_url+'|'+source_version).encode()).hexdigest()[:16]
    bundle={'schema_version':'1.0','dataset':{'id':'dataset:hpoa:'+source_version,'title':'HPO disease–phenotype annotations','description':'Source-reported HPOA annotations. Mechanistic equivalence and asset transfer are not inferred.','synthetic':False,'created_at':retrieved_at},'nodes':[],'sources':[{'id':source_id,'title':'HPOA '+source_version,'url':source_url,'published_at':None,'retrieved_at':retrieved_at,'kind':'database','synthetic':False,'license':license}],'claims':[],'evidence':[],'coverage':[]}
    nodes={}
    seen=set()
    for (line_number, _), raw in zip(records, reader):
        if None in raw or any(v is None for v in raw.values()):
            raise ValueError(f'Malformed HPOA row near line {line_number}.')
        row={normalize(k):v.strip() for k,v in raw.items()}
        disease,hpo=row['databaseid'],row['hpoid']
        if not disease or not row['diseasename'] or not hpo.startswith('HP:') or not hpo[3:].isdigit():
            raise ValueError(f'Invalid disease/phenotype identity near line {line_number}.')
        if row['qualifier'] not in ('','NOT'):
            raise ValueError(f'Unsupported HPOA qualifier {row["qualifier"]!r}; refusing to lose its meaning.')
        nodes.setdefault(disease,dict(id=disease,type='Disease',label=row['diseasename'],aliases=[],properties={}))
        nodes.setdefault(hpo,dict(id=hpo,type='Phenotype',label=hpo,aliases=[],properties={'label_status':'ontology_label_not_loaded'}))
        context={'negated':row['qualifier']=='NOT'}
        for k in ('onset','frequency','sex','modifier','aspect','biocuration'):
            if row.get(k): context[k]=row[k]
        if row['evidence']: context['evidence_code']=row['evidence']
        # The raw record is an annotation, not a quotation from the referenced paper.
        record='\t'.join(raw[k] for k in reader.fieldnames)
        digest=sha256((source_id+'\n'+record).encode()).hexdigest()[:24]
        if digest in seen: continue
        seen.add(digest)
        claim_id='claim:hpoa:'+digest
        bundle['claims'].append(dict(id=claim_id,subject=disease,predicate='HAS_PHENOTYPE',object=hpo,assertion_type='reported',context=context,extraction_confidence=None))
        bundle['evidence'].append(dict(id='evidence:hpoa:'+digest,claim_id=claim_id,source_id=source_id,locator=f'HPOA row {line_number}; upstream reference: {row["reference"] or "not supplied"}',excerpt=record,stance='supports',review_status='unreviewed'))
    if not nodes: raise ValueError('HPOA input contains no annotation records.')
    bundle['nodes']=list(nodes.values())
    for node in bundle['nodes']:
        if node['type']=='Disease':
            bundle['coverage'].append(dict(id='coverage:'+source_id+':'+node['id'],source_id=source_id,entity_id=node['id'],scope='Disease–phenotype rows in the supplied HPOA file only.',status='searched',searched_at=retrieved_at,notes='Imported snapshot; no literature, mechanism, organization or asset search performed.'))
    return bundle

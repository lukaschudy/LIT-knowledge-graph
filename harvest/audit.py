"""Verify all acquired bytes and normalized records; no network activity."""
import argparse, hashlib, json
from pathlib import Path
from harvest.core import ROOT, MANIFESTS, digest, read_records, atomic_json, now

REQUIRED={
 ('hpo','disease_phenotype_annotations'):['database_id','hpo_id','qualifier','reference','evidence'],
 ('hpo','genes_to_disease'):['ncbi_gene_id','disease_id','association_type'],
 ('gencc','assertions'):['sgc_id','gene_curie','disease_curie','classification_title'],
 ('reactome','ReactomePathways'):['reactome_pathway_id','pathway_name','species'],
 ('reactome','UniProt2Reactome_All_Levels'):['uniprot_accession','reactome_pathway_id','evidence_code','species'],
 ('clingen','gene_disease_validity'):['GENE ID (HGNC)','DISEASE ID (MONDO)','CLASSIFICATION'],
 ('go','human_annotations'):['db_object_id','go_id','qualifier','evidence_code','taxon'],
 ('clinvar','variant_summary'):['AlleleID','ClinicalSignificance','Assembly'],
}

def audit_source(manifest_path,deep=True):
    manifest_bytes=manifest_path.read_bytes();m=json.loads(manifest_bytes);source=m['source'];errors=[];warnings=[];datasets=[]
    if m.get('status') not in ('complete','complete_for_scope'):warnings.append('Source acquisition is not marked complete for its declared scope')
    for name,a in m.get('artifacts',{}).items():
        p=ROOT/a['path']
        if not p.exists():errors.append(f'Missing artifact {name}')
        elif p.stat().st_size!=a['bytes'] or digest(p)!=a['sha256']:errors.append(f'Artifact integrity mismatch: {name}')
    for a in m.get('derived_files',[]):
        p=ROOT/a['path']
        if not p.exists():errors.append(f'Missing derived file: {a["path"]}')
        elif p.stat().st_size!=a['bytes'] or digest(p)!=a['sha256']:errors.append(f'Derived file integrity mismatch: {a["path"]}')
    for name,d in m.get('datasets',{}).items():
        p=ROOT/d['path'];count=0;negative=0;empty_identity=0;first_error=None
        for input_path in d.get('input_paths',[]):
            if input_path==d['path']:errors.append(f'Dataset names itself as input: {name}')
            elif not (ROOT/input_path).exists():errors.append(f'Missing input for {name}: {input_path}')
        if not p.exists():errors.append(f'Missing dataset {name}');continue
        if p.stat().st_size!=d['bytes'] or digest(p)!=d['sha256']:errors.append(f'Dataset integrity mismatch: {name}')
        if deep:
            try:
                for count,row in enumerate(read_records(p),1):
                    if not isinstance(row,dict):raise ValueError(f'Non-object at record {count}')
                    if row.get('_source')!=source or row.get('_dataset')!=name or row.get('_record')!=count:raise ValueError(f'Provenance mismatch at record {count}')
                    if 'null' in row:raise ValueError(f'Unheaded overflow columns at record {count}')
                    missing=[key for key in REQUIRED.get((source,name),[]) if key not in row]
                    if missing:raise ValueError(f'Missing required keys {missing} at record {count}')
                    if 'NOT' in str(row.get('qualifier','')).split('|'):negative+=1
                if count!=d['records']:raise ValueError(f'Record count {count} != manifest {d["records"]}')
            except Exception as e:errors.append(f'{name}: {e}')
        datasets.append({'dataset':name,'records':d['records'],'bytes':d['bytes'],'verified_records':count if deep else None,'negative_qualifier_records':negative if deep else None})
    return {'source':source,'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),'manifest_updated_at':m.get('updated_at'),'status':m.get('status'),'scope':m.get('scope',m.get('coverage')),'artifacts':len(m.get('artifacts',{})),'raw_bytes':sum(x['bytes'] for x in m.get('artifacts',{}).values()),'datasets':datasets,'errors':errors,'warnings':warnings}

def run(deep=True,reuse_verified=False):
    previous={};previous_at=None
    previous_path=ROOT/'data/harvest-audit.json'
    if deep and reuse_verified and previous_path.exists():
        old=json.loads(previous_path.read_text())
        if old.get('deep_record_scan'):
            previous={s['source']:s for s in old['sources']};previous_at=old['created_at']
    results=[]
    for p in sorted(MANIFESTS.glob('*.json')):
        prior=previous.get(p.stem)
        reusable=prior and not prior['errors'] and prior.get('manifest_sha256')==digest(p)
        if reusable:
            # Rehash every artifact and dataset. Only the expensive structural
            # JSON scan may be reused, after proving the bytes are unchanged.
            result=audit_source(p,deep=False)
            if not result['errors'] and result['manifest_sha256']==prior['manifest_sha256']:
                result['datasets']=prior['datasets']
                result['structural_validation_reused_from']=prior.get('structural_validation_reused_from',previous_at)
            elif not result['errors']:
                result=audit_source(p,deep)
        else:result=audit_source(p,deep)
        results.append(result)
        print(json.dumps({'source':result['source'],'errors':result['errors'],'records':sum(x['records'] for x in result['datasets'])}),flush=True)
    report={'created_at':now(),'deep_record_scan':deep,'sources':results,'totals':{'sources':len(results),'records':sum(d['records'] for s in results for d in s['datasets']),'raw_bytes':sum(s['raw_bytes'] for s in results),'errors':sum(len(s['errors']) for s in results)},'note':'Counts aggregate different entity/assertion/ontology/retrieval record types and are not a count of unique entities. Source-level completeness is limited to declared scope.'}
    atomic_json(ROOT/'data/harvest-audit.json',report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--quick',action='store_true');p.add_argument('--reuse-verified',action='store_true');a=p.parse_args();r=run(not a.quick,a.reuse_verified)
    raise SystemExit(bool(r['totals']['errors']))

"""Merge independently recovered identifiers without overwriting raw snapshots."""
import argparse, json, sqlite3
from datetime import datetime
from urllib.parse import urlencode
from harvest.core import ROOT, RAW, PROCESSED, MANIFESTS, download, emit_records, manifest, update_manifest, atomic_json, now
from harvest.literature import ENDPOINT

def collect_and_merge():
    recheck=manifest('europe_pmc_recheck');comparison=recheck['comparison'];qid=comparison['query_id']
    recovered=[];inputs=[]
    for key in comparison['added_ids']:
        source,identifier=key.split(':',1)
        query=f'EXT_ID:{identifier} AND SRC:{source}'
        path=download('europe_pmc_recheck',ENDPOINT+'?'+urlencode({'query':query,'format':'json','resultType':'core','pageSize':1000}),f'recovered-{source}-{identifier}.json',license_name='Europe PMC metadata/abstract terms; no assumed full-text permission')
        obj=json.loads(path.read_text());rows=obj.get('resultList',{}).get('result',[])
        matches=[r for r in rows if str(r['source'])+':'+str(r['id'])==key]
        if len(matches)!=1:raise ValueError(f'Expected exactly one recovered record for {key}')
        inputs.append(path);recovered.append({'query_id':qid,'article_id':key,'native':matches[0]})
    if recovered:
        emit_records('europe_pmc_recheck','recovered_articles',recovered,input_paths=inputs,description='Core records for IDs present in the independent traversal but absent from the original query snapshot. Provider updates may contribute to snapshot differences.')
        with sqlite3.connect(PROCESSED/'europe_pmc_diseases/dedup.sqlite',timeout=60) as db:
            for row in recovered:
                db.execute('INSERT OR IGNORE INTO records VALUES (?,?)',(row['article_id'],json.dumps(row['native'],ensure_ascii=False)))
                db.execute('INSERT OR IGNORE INTO matches VALUES (?,?)',(row['query_id'],row['article_id']))
    update_manifest('europe_pmc_recheck',recovery={'merged_to_main_database_at':now(),'identifiers':[r['article_id'] for r in recovered],'main_outputs_must_be_emitted_after_merge':True})

def finalize():
    main=manifest('europe_pmc_diseases')
    if main['status']=='in_progress':raise ValueError('Wait for the main collector to finish before finalizing provenance')
    recheck=manifest('europe_pmc_recheck');comparison=recheck['comparison'];qid=comparison['query_id']
    merged_at=recheck.get('recovery',{}).get('merged_to_main_database_at')
    if merged_at:
        for name in ('articles','query_membership'):
            emitted=main.get('datasets',{}).get(name,{}).get('created_at')
            if not emitted or datetime.fromisoformat(emitted)<datetime.fromisoformat(merged_at):
                raise ValueError('Normalized outputs must be emitted after the recovery merge')
    with sqlite3.connect(PROCESSED/'europe_pmc_diseases/dedup.sqlite') as db:
        count=db.execute('SELECT COUNT(*) FROM matches WHERE query_id=?',(qid,)).fetchone()[0]
    resolved=count==comparison['reported_counts'][0] and not comparison['absent_ids']
    entry={**comparison,'normalized_query_membership':count,'recovery':recheck.get('recovery'),'recheck_manifest':'data/harvest-manifests/europe_pmc_recheck.json','resolution':'count_reconciled_with_independent_snapshot' if resolved else 'unresolved'}
    gaps=main.get('count_discrepancies',{})
    if resolved:gaps.pop(qid,None)
    update_manifest('europe_pmc_diseases',count_discrepancies=gaps,independent_rechecks={qid:entry},status='complete_with_query_gaps' if gaps or main.get('query_errors') else 'complete_for_scope')
    print(json.dumps(entry),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--finalize',action='store_true');a=p.parse_args();finalize() if a.finalize else collect_and_merge()

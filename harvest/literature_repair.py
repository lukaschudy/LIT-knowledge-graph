"""Merge independently recovered identifiers without overwriting raw snapshots."""
import argparse, json, sqlite3
from datetime import datetime
from urllib.parse import urlencode
from harvest.core import ROOT, RAW, PROCESSED, MANIFESTS, download, emit_records, manifest, update_manifest, atomic_json, now, read_records
from harvest.literature import ENDPOINT

def comparisons_and_recoveries(recheck):
    comparisons=dict(recheck.get('comparisons',{}))
    recoveries=dict(recheck.get('recoveries',{}))
    if recheck.get('comparison'):
        qid=recheck['comparison']['query_id']
        comparisons.setdefault(qid,recheck['comparison'])
        # Legacy single-query recovery predates the comparison map. Its ID set
        # identifies the recovered query even after a later comparison is added.
        legacy=recheck.get('recovery')
        if legacy and not recoveries:
            for key,comparison in comparisons.items():
                if set(legacy.get('identifiers',[]))==set(comparison['added_ids']):
                    recoveries[key]=legacy
    return comparisons,recoveries

def collect_and_merge():
    comparisons,recoveries=comparisons_and_recoveries(manifest('europe_pmc_recheck'))
    for qid,comparison in comparisons.items():
        if qid in recoveries:continue
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
            emit_records('europe_pmc_recheck','recovered_articles_'+qid,recovered,input_paths=inputs,description='Core records for IDs present in the independent traversal but absent from the original query snapshot. Provider updates may contribute to snapshot differences.')
            with sqlite3.connect(PROCESSED/'europe_pmc_diseases/dedup.sqlite',timeout=60) as db:
                for row in recovered:
                    db.execute('INSERT OR IGNORE INTO records VALUES (?,?)',(row['article_id'],json.dumps(row['native'],ensure_ascii=False)))
                    db.execute('INSERT OR IGNORE INTO matches VALUES (?,?)',(row['query_id'],row['article_id']))
        recoveries[qid]={'merged_to_main_database_at':now(),'identifiers':[r['article_id'] for r in recovered],'main_outputs_must_be_emitted_after_merge':True}
        update_manifest('europe_pmc_recheck',recoveries=recoveries)

def reconciled(comparison,count):
    return (len(comparison['reported_counts'])==1
            and count==comparison['recheck_unique_ids']==comparison['reported_counts'][0]
            and not comparison['absent_ids'])

def finalize():
    main=manifest('europe_pmc_diseases')
    if main['status']=='in_progress':raise ValueError('Wait for the main collector to finish before finalizing provenance')
    comparisons,recoveries=comparisons_and_recoveries(manifest('europe_pmc_recheck'))
    entries=dict(main.get('independent_rechecks',{}));gaps=main.get('count_discrepancies',{})
    # Database writes may happen while gzip emission is underway. Timestamps
    # alone cannot prove that an export's SQLite snapshot included a recovery.
    normalized_counts={qid:0 for qid in comparisons}
    recovered_ids={key for recovery in recoveries.values() for key in recovery.get('identifiers',[])}
    exported_recovered=set()
    for row in read_records(PROCESSED/'europe_pmc_diseases/query_membership.jsonl.gz'):
        qid=row['query_id']
        if qid in normalized_counts:normalized_counts[qid]+=1
    for row in read_records(PROCESSED/'europe_pmc_diseases/articles.jsonl.gz'):
        key=str(row['source'])+':'+str(row['id'])
        if key in recovered_ids:exported_recovered.add(key)
    if recovered_ids-exported_recovered:
        raise ValueError('Re-emit normalized outputs: recovered article IDs missing '+str(sorted(recovered_ids-exported_recovered)))
    for qid,comparison in comparisons.items():
        recovery=recoveries.get(qid,{})
        merged_at=recovery.get('merged_to_main_database_at')
        if merged_at:
            for name in ('articles','query_membership'):
                emitted=main.get('datasets',{}).get(name,{}).get('created_at')
                if not emitted or datetime.fromisoformat(emitted)<datetime.fromisoformat(merged_at):
                    raise ValueError('Normalized outputs must be emitted after the recovery merge')
        with sqlite3.connect(PROCESSED/'europe_pmc_diseases/dedup.sqlite') as db:
            count=db.execute('SELECT COUNT(*) FROM matches WHERE query_id=?',(qid,)).fetchone()[0]
        if normalized_counts[qid]!=count:
            raise ValueError(f'Re-emit normalized outputs: membership count differs for {qid}')
        resolved=reconciled(comparison,count)
        entry={**comparison,'normalized_query_membership':count,'recovery':recovery,'recheck_manifest':'data/harvest-manifests/europe_pmc_recheck.json','resolution':'count_reconciled_with_independent_snapshot' if resolved else 'unresolved'}
        entries[qid]=entry
        if resolved:gaps.pop(qid,None)
        else:gaps.setdefault(qid,entry)
        print(json.dumps(entry),flush=True)
    update_manifest('europe_pmc_diseases',count_discrepancies=gaps,independent_rechecks=entries,status='complete_with_query_gaps' if gaps or main.get('query_errors') else 'complete_for_scope')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--finalize',action='store_true');a=p.parse_args();finalize() if a.finalize else collect_and_merge()

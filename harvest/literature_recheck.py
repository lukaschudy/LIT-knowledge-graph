"""Independently re-traverse discrepant queries as date-sorted identifier lists.

Retains both snapshots. A matching set explains duplicate rows, but cannot prove
search recall. This process never mutates the main collector's live database.
"""
import argparse, hashlib, json, sqlite3
from urllib.parse import urlencode
from harvest.core import ROOT, RAW, PROCESSED, download, emit_records, update_manifest, manifest, _MANIFEST_LOCK
from harvest.literature import ENDPOINT

SOURCE = 'europe_pmc_recheck'

def run(qid):
    original = sorted((RAW/'europe_pmc_diseases').glob(qid+'-*.json'))
    query = json.loads(original[0].read_text())['request']['queryString']
    initial = set()
    initial_rows = 0
    for path in original:
        rows = json.loads(path.read_text()).get('resultList', {}).get('result', [])
        initial_rows += len(rows)
        initial.update(str(r['source'])+':'+str(r['id']) for r in rows)
    cursor='*'; seen=set(); paths=[]; raw_count=0; reported=[]; page=0
    while True:
        url=ENDPOINT+'?'+urlencode({'query':query+' sort_date:y','format':'json','resultType':'idlist','pageSize':1000,'cursorMark':cursor})
        path=download(SOURCE,url,f'{qid}-{page:05d}-{hashlib.sha256(cursor.encode()).hexdigest()[:8]}.json',license_name='Europe PMC bibliographic identifiers and metadata terms')
        paths.append(path); obj=json.loads(path.read_text()); reported.append(obj['hitCount'])
        rows=obj.get('resultList',{}).get('result',[]); raw_count+=len(rows)
        seen.update(str(r['source'])+':'+str(r['id']) for r in rows)
        nxt=obj.get('nextCursorMark'); page+=1
        if not rows or not nxt or nxt==cursor:break
        cursor=nxt
    emit_records(SOURCE,'identifiers_'+qid,({'article_id':k,'query_id':qid} for k in sorted(seen)),input_paths=paths,description='Independent date-sorted ID-only traversal of a query with duplicate core response rows.')
    report={'query_id':qid,'original_raw_rows':initial_rows,'original_unique_ids':len(initial),'recheck_raw_rows':raw_count,'recheck_unique_ids':len(seen),'reported_counts':sorted(set(reported)),'added_ids':sorted(seen-initial),'absent_ids':sorted(initial-seen),'identical_id_set':seen==initial,'pages':page}
    emit_records(SOURCE,'comparison_'+qid,[report],input_paths=original+paths,description='Snapshot set comparison; changed membership can also reflect provider updates.')
    with _MANIFEST_LOCK:
        prior=manifest(SOURCE)
        comparisons=dict(prior.get('comparisons',{}))
        if prior.get('comparison'):comparisons.setdefault(prior['comparison']['query_id'],prior['comparison'])
        comparisons[qid]=report
        update_manifest(SOURCE,status='complete_for_scope',comparison=report,comparisons=comparisons,limitations=['An independently sorted ID set can diagnose pagination gaps; it does not establish complete literature recall.','Recovery records explicitly document any later additions to the main corpus.'])
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('query_id');run(parser.parse_args().query_id)

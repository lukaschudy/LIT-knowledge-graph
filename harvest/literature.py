"""Exhaustive Europe PMC searches from the public rare-disease vocabulary.

Retrieval matches are candidates, never asserted disease/publication relations.
Uses disk-backed deduplication to keep memory bounded across large corpora.
"""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3, time, threading, os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from harvest.core import ROOT, RAW, PROCESSED, download, emit_records, read_records, update_manifest, atomic_json, now, manifest

SOURCE='europe_pmc_diseases'
ENDPOINT='https://www.ebi.ac.uk/europepmc/webservices/rest/search'
# Preserve the source vocabulary and stable batch boundaries, but do not send
# a non-discriminating alias as a standalone exact-phrase literature search.
EXCLUDED_ALIASES={'the syndrome':'Non-discriminating generic phrase; does not identify the source disease.'}

def query_for_group(group):
    included=[t['term'] for t in group if t['term'] not in EXCLUDED_ALIASES]
    return '('+' OR '.join('TITLE_ABS:"'+term+'"' for term in included)+')'

def vocabulary(rows):
    terms={}
    for row in rows:
        name=row['Rare Disease Name'].strip()
        for value in [name]+row.get('Disease Aliases','').split('//'):
            value=' '.join(value.strip().split())
            # Keep every preferred name. Exclude short/single-word aliases that
            # cannot be disambiguated safely as independent search phrases.
            if value!=name and (len(value)<10 or ' ' not in value):continue
            value=value.replace('"',' ').replace('\\',' ').strip().lower()
            if value:terms.setdefault(value,set()).add(row.get('Disease Annotations',name))
    return [{'term':k,'disease_source_ids':sorted(v)} for k,v in sorted(terms.items())]

def batches(terms,max_chars=5500):
    group=[];size=0
    for term in terms:
        added=len(term['term'])+20
        if group and size+added>max_chars:
            yield group;group=[];size=0
        group.append(term);size+=added
    if group:yield group

def run(workers=4, wait_for_rechecks=False):
    source_path=PROCESSED/'raresource/diseases.jsonl.gz'
    terms=vocabulary(read_records(source_path))
    groups=list(batches(terms))
    emit_records(SOURCE,'search_vocabulary',({**t,'query_eligible':t['term'] not in EXCLUDED_ALIASES,'exclusion_reason':EXCLUDED_ALIASES.get(t['term'])} for t in terms),input_paths=[source_path],description='All preferred names and multiword aliases of >=10 characters; exact phrase retrieval terms, not validated relationships.')
    work=RAW/SOURCE;work.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(PROCESSED/SOURCE/'dedup.sqlite')
    connection.execute('CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, data TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS matches (query_id TEXT, key TEXT, PRIMARY KEY(query_id,key))')
    progress_path=work/'progress.json'
    progress=json.loads(progress_path.read_text()) if progress_path.exists() else {'started_at':now(),'completed':{}}
    connection.execute('PRAGMA journal_mode=WAL')
    queries=[]; progress_lock=threading.RLock(); request_lock=threading.Lock(); next_request=[0.0]
    for group in groups:
        query=query_for_group(group)
        queries.append({'query_id':hashlib.sha256(query.encode()).hexdigest()[:20],'query':query,'terms':[x['term'] for x in group if x['term'] not in EXCLUDED_ALIASES],'excluded_aliases':[{'term':x['term'],'reason':EXCLUDED_ALIASES[x['term']],'disease_source_ids':x['disease_source_ids']} for x in group if x['term'] in EXCLUDED_ALIASES]})
    def harvest_group(item):
        index,group=item
        connection=sqlite3.connect(PROCESSED/SOURCE/'dedup.sqlite',timeout=60)
        query=query_for_group(group)
        qid=hashlib.sha256(query.encode()).hexdigest()[:20]
        if qid in progress['completed']:
            connection.close();return
        cursor='*';page=0;seen=set();expected=None;paths=[]
        while True:
            params={'query':query,'format':'json','resultType':'core','pageSize':1000,'cursorMark':cursor}
            url=ENDPOINT+'?'+urlencode(params)
            fname=f'{qid}-{page:05d}-{hashlib.sha256(cursor.encode()).hexdigest()[:8]}.json'
            if not (work/fname).exists():
                with request_lock:
                    delay=max(0,next_request[0]-time.monotonic())
                    next_request[0]=time.monotonic()+delay+.5
                if delay:time.sleep(delay)
            p=download(SOURCE,url,fname,license_name='Europe PMC metadata/abstract terms; article-specific licenses retained; no assumed full-text reuse permission')
            obj=json.loads(p.read_text());paths.append(str(p.relative_to(ROOT)))
            if 'hitCount' not in obj:raise ValueError('Europe PMC returned no hitCount')
            if expected is None:expected=int(obj['hitCount'])
            rows=obj.get('resultList',{}).get('result',[])
            for row in rows:
                key=str(row['source'])+':'+str(row['id']);seen.add(key)
                connection.execute('INSERT OR REPLACE INTO records VALUES (?,?)',(key,json.dumps(row,ensure_ascii=False)))
                connection.execute('INSERT OR IGNORE INTO matches VALUES (?,?)',(qid,key))
            connection.commit();page+=1
            nxt=obj.get('nextCursorMark')
            if not rows or not nxt or nxt==cursor:break
            if len(seen)>=expected:break
            cursor=nxt;time.sleep(.15)
        with progress_lock:
            status='count_verified' if len(seen)==expected else 'count_discrepancy'
            progress['completed'][qid]={'reported_hits':expected,'last_reported_hits':int(obj['hitCount']),'unique_retrieved':len(seen),'pages':page,'input_paths':paths,'completed_at':now(),'status':status}
            atomic_json(progress_path,progress)
            update_manifest(SOURCE,status='in_progress',coverage={'vocabulary_terms':len(terms),'eligible_search_terms':sum(t['term'] not in EXCLUDED_ALIASES for t in terms),'excluded_aliases':EXCLUDED_ALIASES,'total_queries':len(groups),'completed_queries':len(progress['completed']),'unique_articles':connection.execute('SELECT COUNT(*) FROM records').fetchone()[0]},scope='Exhaustive cursor results for recorded rare-disease name phrases in titles/abstracts; retrieval candidates, not biological evidence.')
            print(json.dumps({'event':'query_complete','query_index':index+1,'queries':len(groups),'hits':len(seen)}),flush=True)
        connection.close()
    errors={}
    def guarded_group(item):
        try:harvest_group(item)
        except Exception as exc:
            with progress_lock:
                errors[queries[item[0]]['query_id']]=str(exc)
                atomic_json(work/'query_errors.json',errors)
                print(json.dumps({'event':'query_error','query_index':item[0]+1,'error':str(exc)}),flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(guarded_group,enumerate(groups)))
    if wait_for_rechecks:
        # The independent worker merges recovered IDs into SQLite. Wait before
        # opening export cursors, otherwise their snapshot can miss late merges.
        job_path=RAW/'literature-recheck-job.json'
        if not job_path.exists():raise RuntimeError('No independent recheck job to wait for')
        print(json.dumps({'event':'waiting_for_independent_rechecks'}),flush=True)
        while True:
            job=json.loads(job_path.read_text())
            if job['state']=='finished':break
            if job['state']!='running':raise RuntimeError('Independent recheck job failed: '+str(job))
            try:os.kill(job['pid'],0)
            except ProcessLookupError:raise RuntimeError('Independent recheck worker exited without completion')
            time.sleep(10)
    emit_records(SOURCE,'queries',queries,input_paths=[source_path],description='Exact query definitions linking vocabulary batches to retrieval membership.')
    emit_records(SOURCE,'articles',(json.loads(r[0]) for r in connection.execute('SELECT data FROM records ORDER BY key')),description='Deduplicated complete Europe PMC core metadata per source:id; abstracts, authors, affiliations, grants, identifiers and available rights retained. Raw input artifacts and per-query progress establish provenance.')
    emit_records(SOURCE,'query_membership',({'query_id':q,'article_id':k} for q,k in connection.execute('SELECT query_id,key FROM matches ORDER BY query_id,key')),description='Search batch membership only; an article need not match every term in a batch.')
    discrepancies={k:v for k,v in progress['completed'].items() if v['reported_hits']!=v['unique_retrieved']}
    update_manifest(SOURCE,status='complete_with_query_gaps' if errors or discrepancies else 'complete_for_scope',queries=progress['completed'],query_errors=errors,count_discrepancies=discrepancies,limitations=['Preferred name and multiword alias matches are discovery candidates, not proven disease associations.','Short or single-word aliases and the non-discriminating alias the syndrome are excluded to reduce ambiguity; preferred names all included.','No source search guarantees complete recall; title/abstract search misses full-text-only mentions.','Europe PMC updates during traversal may change counts; acquired pages remain reproducible snapshots.'])
    connection.close()
    if manifest('europe_pmc_recheck').get('recovery'):
        from harvest.literature_repair import finalize
        finalize()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,choices=range(1,9),default=4);p.add_argument('--wait-for-rechecks',action='store_true');a=p.parse_args();run(a.workers,a.wait_for_rechecks)

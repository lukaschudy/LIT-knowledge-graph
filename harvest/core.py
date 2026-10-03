"""Streaming downloads and auditable JSONL datasets. No implicit clinical claims."""
from __future__ import annotations
import gzip, hashlib, json, os, shutil, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
import requests

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/harvest'
PROCESSED=ROOT/'data/processed/harvest'
MANIFESTS=ROOT/'data/harvest-manifests'
USER_AGENT='LIT-RareDiseaseHarvest/0.1 (research source acquisition)'
SESSION=requests.Session()
SESSION.headers['User-Agent']=USER_AGENT
SESSION.headers['Accept-Encoding']='identity'
DISK_FLOOR=8*1024**3


def now(): return datetime.now(timezone.utc).isoformat()

def atomic_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe_url(url):
    p=urlsplit(url)
    items=[(k,'REDACTED' if k.lower() in {'api_key','apikey','key','token','access_token'} else v) for k,v in parse_qsl(p.query,keep_blank_values=True)]
    return urlunsplit((p.scheme,p.netloc,p.path,urlencode(items),''))

def manifest(source):
    path=MANIFESTS/(source+'.json')
    return json.loads(path.read_text()) if path.exists() else {'source':source,'created_at':now(),'artifacts':{},'datasets':{},'status':'in_progress'}

def update_manifest(source, **values):
    data=manifest(source); data.update(values); data['updated_at']=now(); atomic_json(MANIFESTS/(source+'.json'),data); return data

def download(source,url,filename,*,license_name,version=None,refresh=False,method='GET',json_body=None):
    """Cache immutable acquisitions; interrupted GET downloads resume via Range.

    A cached file is reused only if its recorded SHA-256 still matches.
    One process owns a source manifest; callers must not race on the same source.
    """
    dest=RAW/source/filename; dest.parent.mkdir(parents=True,exist_ok=True)
    data=manifest(source); previous=data['artifacts'].get(filename)
    if dest.exists() and previous and not refresh and digest(dest)==previous.get('sha256'):
        return dest
    part=dest.with_suffix(dest.suffix+'.part')
    resume_info=part.with_suffix(part.suffix+'.json')
    if refresh and part.exists():part.unlink()
    last=None
    for attempt in range(4):
        try:
            start=part.stat().st_size if part.exists() and method=='GET' else 0
            resume=json.loads(resume_info.read_text()) if resume_info.exists() else {}
            if start and (resume.get('url')!=safe_url(url) or not resume.get('validator')):
                part.unlink();start=0
            headers={'Range':f'bytes={start}-'} if start else {}
            if start:headers['If-Range']=resume['validator']
            with SESSION.request(method,url,json=json_body,headers=headers,stream=True,timeout=(20,90)) as response:
                if response.status_code in (429,500,502,503,504):
                    delay=response.headers.get('Retry-After','')
                    time.sleep(min(int(delay) if delay.isdigit() else 2**(attempt+1),30))
                    response.raise_for_status()
                response.raise_for_status()
                append=start>0 and response.status_code==206
                if append and not response.headers.get('Content-Range','').startswith(f'bytes {start}-'):
                    raise ValueError('Invalid resume Content-Range')
                length=int(response.headers.get('Content-Length',0))
                if shutil.disk_usage(ROOT).free-length < DISK_FLOOR:
                    raise RuntimeError('Insufficient space above 8 GiB disk reserve')
                atomic_json(resume_info,{'url':safe_url(url),'validator':response.headers.get('ETag') or response.headers.get('Last-Modified')})
                with part.open('ab' if append else 'wb') as out:
                    written=0
                    for block in response.iter_content(1024*1024):
                        if not block:continue
                        if shutil.disk_usage(ROOT).free < DISK_FLOOR:raise RuntimeError('8 GiB disk reserve reached')
                        out.write(block);written+=len(block)
                if not written and not append:raise ValueError('Empty response')
                # Content-Length can describe compressed transfer; requests decodes it.
                if length and not response.headers.get('Content-Encoding') and written!=length:
                    raise ValueError(f'Truncated response: expected {length}, received {written}')
                part.replace(dest)
                if resume_info.exists():resume_info.unlink()
                entry={'url':safe_url(url),'final_url':safe_url(response.url),'method':method,'request_body':json_body,'path':str(dest.relative_to(ROOT)),'bytes':dest.stat().st_size,'sha256':digest(dest),'retrieved_at':now(),'license':license_name,'version':version,'http_status':response.status_code,'content_type':response.headers.get('Content-Type'),'last_modified':response.headers.get('Last-Modified'),'etag':response.headers.get('ETag')}
                data=manifest(source);data['artifacts'][filename]=entry;data['updated_at']=now();atomic_json(MANIFESTS/(source+'.json'),data)
                print(json.dumps({'event':'downloaded','source':source,'file':filename,'bytes':entry['bytes']}),flush=True)
                return dest
        except (requests.RequestException,ValueError) as e:
            last=e
            if isinstance(e,requests.HTTPError) and e.response.status_code not in (429,500,502,503,504):break
            if attempt<3:time.sleep(min(2**attempt,8))
    raise RuntimeError(f'{source} download failed: {safe_url(url)}: {last}')

def emit_records(source,name,records,*,input_paths=(),description=''):
    dest=PROCESSED/source/(name+'.jsonl.gz');dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix(dest.suffix+'.tmp');count=0
    inputs=[str(Path(p).relative_to(ROOT)) for p in input_paths]
    try:
        with gzip.open(temp,'wt',encoding='utf-8') as out:
            for count,record in enumerate(records,1):
                if not isinstance(record,dict):raise TypeError('Records must be dicts')
                record=dict(record);record['_source']=source;record['_dataset']=name;record['_record']=count
                out.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
        if count==0:raise ValueError(f'{source}/{name}: no records emitted')
        temp.replace(dest)
    except BaseException:
        if temp.exists():temp.unlink()
        raise
    data=manifest(source);data['datasets'][name]={'path':str(dest.relative_to(ROOT)),'records':count,'bytes':dest.stat().st_size,'sha256':digest(dest),'input_paths':inputs,'description':description,'created_at':now(),'format':'gzip-jsonl','parser_version':'harvest-v1'};data['updated_at']=now();atomic_json(MANIFESTS/(source+'.json'),data)
    print(json.dumps({'event':'normalized','source':source,'dataset':name,'records':count}),flush=True)
    return dest

def open_text(path):
    path=Path(path)
    return gzip.open(path,'rt',encoding='utf-8-sig') if path.suffix=='.gz' else path.open(encoding='utf-8-sig')

def read_records(path):
    with open_text(path) as f:
        for line in f:
            yield json.loads(line)

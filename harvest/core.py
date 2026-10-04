"""Streaming downloads and auditable JSONL datasets. No implicit clinical claims."""
from __future__ import annotations
import gzip, hashlib, json, os, re, shutil, tempfile, time, threading
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
_MANIFEST_LOCK=threading.RLock()


def now(): return datetime.now(timezone.utc).isoformat()

def atomic_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    body=json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,suffix='.tmp',delete=False) as out:
            temporary=Path(out.name);out.write(body);out.flush();os.fsync(out.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def _source_name(source):
    if not isinstance(source,str) or not source or source in {'.','..'} or any(c in source for c in '/\\\0'):
        raise ValueError('Source must be one nonempty path component')
    return source

def _destination(base,source,name):
    _source_name(source)
    if not isinstance(name,str) or not name or '\\' in name or '\0' in name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Acquisition filename must remain within its source directory')
    directory=(Path(base)/source).resolve();dest=(directory/name).resolve()
    if not directory.is_relative_to(ROOT.resolve()) or not dest.is_relative_to(directory) or dest==directory:
        raise ValueError('Acquisition filename must remain within its source directory')
    return dest

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe_url(url):
    p=urlsplit(url)
    items=[(k,'REDACTED' if k.lower() in {'api_key','apikey','key','token','access_token'} else v) for k,v in parse_qsl(p.query,keep_blank_values=True)]
    return urlunsplit((p.scheme,p.netloc.rsplit('@',1)[-1],p.path,urlencode(items),''))

def manifest(source):
    path=(MANIFESTS/(_source_name(source)+'.json')).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('Manifest must remain within the acquisition root')
    data=json.loads(path.read_text()) if path.exists() else {'source':source,'created_at':now(),'artifacts':{},'datasets':{},'status':'in_progress'}
    if not isinstance(data,dict) or data.get('source')!=source or not isinstance(data.get('artifacts'),dict) or not isinstance(data.get('datasets'),dict):
        raise ValueError('Manifest source identity or receipt collections are invalid')
    return data

def update_manifest(source, **values):
    with _MANIFEST_LOCK:
        data=manifest(source); data.update(values); data['updated_at']=now(); atomic_json(MANIFESTS/(source+'.json'),data); return data

def download(source,url,filename,*,license_name,version=None,refresh=False,method='GET',json_body=None):
    """Cache immutable acquisitions; interrupted GET downloads resume via Range.

    A cached file is reused only if its recorded SHA-256 still matches.
    One process owns a source manifest; callers must not race on the same source.
    """
    method=method.upper()
    request_sha256=hashlib.sha256(json.dumps({'url':url,'method':method,'body':json_body},sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()
    dest=_destination(RAW,source,filename); dest.parent.mkdir(parents=True,exist_ok=True)
    data=manifest(source); previous=data['artifacts'].get(filename)
    if (dest.exists() and previous and not refresh
            and previous.get('url')==safe_url(url)
            and previous.get('method','GET')==method
            and previous.get('request_body')==json_body
            and previous.get('version')==version
            and (previous.get('request_sha256')==request_sha256
                 or previous.get('request_sha256') is None and safe_url(url)==url)
            and digest(dest)==previous.get('sha256')):
        return dest
    update_manifest(source,status='in_progress')
    part=dest.with_suffix(dest.suffix+'.part')
    resume_info=part.with_suffix(part.suffix+'.json')
    if refresh and part.exists():part.unlink()
    last=None
    for attempt in range(4):
        try:
            start=part.stat().st_size if part.exists() and method=='GET' else 0
            try:
                resume=json.loads(resume_info.read_text()) if resume_info.exists() else {}
            except (ValueError,UnicodeError):
                resume={}
            if not isinstance(resume,dict):resume={}
            if start and (resume.get('request_sha256')!=request_sha256 or not resume.get('validator')):
                part.unlink();start=0
            headers={'Range':f'bytes={start}-'} if start else {}
            if start:headers['If-Range']=resume['validator']
            with SESSION.request(method,url,json=json_body,headers=headers,stream=True,timeout=(20,90)) as response:
                if response.status_code in (429,500,502,503,504):
                    delay=response.headers.get('Retry-After','')
                    time.sleep(min(int(delay) if delay.isdigit() else 2**(attempt+1),30))
                    response.raise_for_status()
                response.raise_for_status()
                if response.status_code not in (200,206):raise ValueError('Expected a complete download response')
                append=start>0 and response.status_code==206
                encoding=response.headers.get('Content-Encoding','identity').lower()
                validator=response.headers.get('ETag')
                if not validator or validator.startswith('W/'):validator=response.headers.get('Last-Modified')
                span=None
                if response.status_code==206:
                    match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
                    if not match:raise ValueError('Invalid resume Content-Range')
                    first,last,total=map(int,match.groups())
                    if first!=(start if append else 0) or not first<=last<total or encoding!='identity':
                        raise ValueError('Invalid resume Content-Range or encoded partial response')
                    if append and validator!=resume['validator']:
                        part.unlink(missing_ok=True);resume_info.unlink(missing_ok=True)
                        raise ValueError('Source validator changed during range resume')
                    span=(first,last,total)
                length=int(response.headers['Content-Length']) if 'Content-Length' in response.headers else None
                if length is not None and length<0:raise ValueError('Invalid negative Content-Length')
                if shutil.disk_usage(ROOT).free-(length or 0) < DISK_FLOOR:
                    raise RuntimeError('Insufficient space above 8 GiB disk reserve')
                with part.open('ab' if append else 'wb') as out:
                    # Truncate an obsolete representation before assigning its
                    # replacement validator, including across interruption.
                    atomic_json(resume_info,{'url':safe_url(url),'request_sha256':request_sha256,
                                             'validator':validator if encoding=='identity' else None})
                    written=0
                    for block in response.iter_content(1024*1024):
                        if not block:continue
                        if shutil.disk_usage(ROOT).free < DISK_FLOOR:raise RuntimeError('8 GiB disk reserve reached')
                        out.write(block);written+=len(block)
                    out.flush();os.fsync(out.fileno())
                if not written and not append:raise ValueError('Empty response')
                # Content-Length can describe compressed transfer; requests decodes it.
                if ((length is not None and encoding=='identity' and written>length)
                        or span is not None and written>span[1]-span[0]+1):
                    part.unlink(missing_ok=True);resume_info.unlink(missing_ok=True)
                    raise ValueError('Response exceeded its declared byte range or length')
                if length is not None and encoding=='identity' and written!=length:
                    raise ValueError(f'Truncated response: expected {length}, received {written}')
                if span is not None and (written!=span[1]-span[0]+1 or span[1]+1!=span[2]):
                    raise ValueError('Incomplete range response; acquisition remains resumable')
                part.replace(dest)
                if resume_info.exists():resume_info.unlink()
                entry={'url':safe_url(url),'final_url':safe_url(response.url),'method':method,'request_body':json_body,'request_sha256':request_sha256,'path':str(dest.relative_to(ROOT)),'bytes':dest.stat().st_size,'sha256':digest(dest),'retrieved_at':now(),'license':license_name,'version':version,'http_status':response.status_code,'content_type':response.headers.get('Content-Type'),'last_modified':response.headers.get('Last-Modified'),'etag':response.headers.get('ETag')}
                with _MANIFEST_LOCK:
                    data=manifest(source);data['artifacts'][filename]=entry;data['updated_at']=now();atomic_json(MANIFESTS/(source+'.json'),data)
                print(json.dumps({'event':'downloaded','source':source,'file':filename,'bytes':entry['bytes']}),flush=True)
                return dest
        except (requests.RequestException,ValueError) as e:
            last=e
            if isinstance(e,requests.HTTPError) and e.response is not None and e.response.status_code not in (429,500,502,503,504):break
            if attempt<3:time.sleep(min(2**attempt,8))
    reason=type(last).__name__
    if isinstance(last,requests.HTTPError) and last.response is not None:
        reason+=f' (HTTP {last.response.status_code})'
    # Requests exception text may echo credentials from the original URL/body.
    raise RuntimeError(f'{source} download failed: {safe_url(url)}: {reason}') from None

def emit_records(source,name,records,*,input_paths=(),description=''):
    dest=_destination(PROCESSED,source,name+'.jsonl.gz');dest.parent.mkdir(parents=True,exist_ok=True)
    temp=None;count=0
    inputs=[str(Path(p).relative_to(ROOT)) for p in input_paths]
    update_manifest(source,status='in_progress')
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.jsonl.gz.tmp',delete=False) as handle:temp=Path(handle.name)
        with gzip.open(temp,'wt',encoding='utf-8',compresslevel=6) as out:
            for count,record in enumerate(records,1):
                if not isinstance(record,dict):raise TypeError('Records must be dicts')
                record=dict(record);record['_source']=source;record['_dataset']=name;record['_record']=count
                out.write(json.dumps(record,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
        if count==0:raise ValueError(f'{source}/{name}: no records emitted')
        with temp.open('rb') as handle:os.fsync(handle.fileno())
        with _MANIFEST_LOCK:
            data=manifest(source)
            receipt={'path':str(dest.relative_to(ROOT)),'records':count,'bytes':temp.stat().st_size,'sha256':digest(temp),'input_paths':inputs,'description':description,'created_at':now(),'format':'gzip-jsonl','parser_version':'harvest-v1'}
            temp.replace(dest)
            data['datasets'][name]=receipt;data['updated_at']=now();data['status']='in_progress'
            atomic_json(MANIFESTS/(source+'.json'),data)
    except BaseException:
        if temp is not None:temp.unlink(missing_ok=True)
        raise
    print(json.dumps({'event':'normalized','source':source,'dataset':name,'records':count}),flush=True)
    return dest

def open_text(path):
    path=Path(path)
    return gzip.open(path,'rt',encoding='utf-8-sig') if path.suffix=='.gz' else path.open(encoding='utf-8-sig')

def read_records(path):
    with open_text(path) as f:
        for line in f:
            yield json.loads(line)

def import_export(source, input_path, filename, *, url, license_name, expected_records=None):
    """Register a file obtained through a provider's public export control."""
    original=Path(input_path)
    dest=_destination(RAW,source,filename); dest.parent.mkdir(parents=True,exist_ok=True)
    update_manifest(source,status='in_progress')
    temp=None
    try:
        if original.resolve()!=dest.resolve():
            with tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.import.tmp',delete=False) as out:
                temp=Path(out.name)
                with original.open('rb') as incoming:shutil.copyfileobj(incoming,out)
                out.flush();os.fsync(out.fileno())
        staged=temp or dest
        receipt={'url':safe_url(url),'method':'browser_export','path':str(dest.relative_to(ROOT)),
            'bytes':staged.stat().st_size,'sha256':digest(staged),'retrieved_at':now(),
            'license':license_name,'expected_records':expected_records}
        with _MANIFEST_LOCK:
            data=manifest(source)
            if temp is not None:temp.replace(dest)
            data['artifacts'][filename]=receipt
            data['status']='in_progress';data['updated_at']=now()
            atomic_json(MANIFESTS/(source+'.json'),data)
    finally:
        if temp is not None:temp.unlink(missing_ok=True)
    return dest

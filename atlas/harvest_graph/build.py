"""Streaming, resumable graph projection of every manifest-registered source row.

Original JSON stays in its checksummed gzip; row offsets and gzip seek points
make the entire record space addressable without copying gigabytes of payload.
"""
from __future__ import annotations
from collections import OrderedDict
from hashlib import sha256
import json
import os
import tempfile
from pathlib import Path
import shutil
import sqlite3
import struct
import time

from .store import initialize, validate_schema, _offset_stamp
from .adapters import adapt
from .source_reader import import_verified_index

VERSION = 'harvest-graph-v1'


def inventory(root):
    root = Path(root).resolve()
    result = []
    for path in sorted((root / 'data/harvest-manifests').glob('*.json')):
        manifest = json.loads(path.read_text())
        artifacts = list(manifest.get('artifacts', {}).values())
        for name, ds in manifest.get('datasets', {}).items():
            target = (root / ds['path']).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError(f'Missing or unsafe registered dataset: {path.stem}/{name}')
            meta = {'source': path.stem, 'name': name, 'description': ds.get('description', ''),
                    'manifest_path': str(path.relative_to(root)), 'bytes': target.stat().st_size,
                    'mtime_ns': target.stat().st_mtime_ns,
                    'source_urls': list(dict.fromkeys(a.get('url') for a in artifacts if a.get('url')))[:10],
                    'licenses': list(dict.fromkeys(a.get('license') for a in artifacts if a.get('license')))}
            if ds.get('bytes') != target.stat().st_size:
                raise ValueError(f'Dataset size differs from receipt: {path.stem}/{name}')
            result.append({'key': path.stem + '/' + name, 'path': ds['path'], 'sha256': ds['sha256'],
                           'expected_rows': ds['records'], 'metadata': meta})
    if not result:
        raise ValueError('No registered harvested datasets were found.')
    # Load authoritative identity/label registries before association references.
    priority = {'hgnc': 0, 'mondo': 1, 'hpo': 2, 'go': 3, 'reactome': 4, 'raresource': 5,
                'ror': 6, 'orphadata': 7, 'clingen': 8, 'gencc': 9, 'uniprot': 10}
    return sorted(result, key=lambda d: (priority.get(d['metadata']['source'], 20), d['expected_rows'], d['key']))


def digest_file(path):
    h = sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _publish_seek_index(stream, path):
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.gzidx.tmp', delete=False) as handle:
        temporary = Path(handle.name)
    try:
        stream.export_index(filename=str(temporary))
        with temporary.open('rb') as handle:
            os.fsync(handle.fileno())
        temporary.replace(path)
        return digest_file(path)
    finally:
        temporary.unlink(missing_ok=True)


def build(root, database, *, progress=None, batch_size=5000, reserve_bytes=600 * 1024**2):
    """Only one builder may advance a database's committed row cursor at once."""
    import fcntl
    if type(batch_size) is not int or not 1 <= batch_size <= 50000:
        raise ValueError('Batch size must be between 1 and 50,000 rows.')
    database = Path(database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    with open(str(database) + '.build.lock', 'a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another process is already building this harvest database.') from None
        return _build(root, database, progress=progress, batch_size=batch_size, reserve_bytes=reserve_bytes)


def _build(root, database, *, progress, batch_size, reserve_bytes):
    import indexed_gzip
    root, database = Path(root).resolve(), Path(database).resolve()
    datasets = inventory(root)
    identity = sha256(json.dumps([(d['key'], d['sha256'], d['expected_rows']) for d in datasets]).encode()).hexdigest()
    database.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(database)
    try:
        existing = validate_schema(db, allow_empty=True)
        previous = dict(db.execute('SELECT key,value FROM metadata')) if existing else {}
        if previous and (previous.get('build_id') != identity or previous.get('source_root') != str(root) or previous.get('version') != VERSION):
            raise ValueError('Graph index belongs to different source snapshots; choose a new output database.')
        if previous.get('invalid_source'):
            raise ValueError('Source changed during an earlier ingestion; choose a new output database.')
    except Exception:
        db.close()
        raise
    sources = Path(str(database) + '.sources'); sources.mkdir(exist_ok=True)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=NORMAL')
    db.execute('PRAGMA cache_size=-65536'); db.execute('PRAGMA temp_store=MEMORY')
    initialize(db)
    def meta(key, value):
        db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES (?,?)', (key, value))
    meta('build_id', identity); meta('source_root', str(root)); meta('version', VERSION)
    for d in datasets:
        db.execute('INSERT OR IGNORE INTO datasets(key,path,sha256,expected_rows,processed_rows,status,metadata) VALUES (?,?,?,?,0,?,?)',
                   (d['key'], d['path'], d['sha256'], d['expected_rows'], 'pending', json.dumps(d['metadata'])))
    db.commit()
    predicates = dict(db.execute('SELECT name,pid FROM predicates'))
    cache = OrderedDict()
    placeholder_labels = set()
    totals = {'total_nodes': db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0],
              'total_edges': db.execute('SELECT COUNT(*) FROM edges').fetchone()[0],
              'total_records': sum(d['expected_rows'] for d in datasets),
              'processed_records': db.execute('SELECT COALESCE(SUM(processed_rows),0) FROM datasets').fetchone()[0],
              'total_datasets': len(datasets), 'completed_datasets': db.execute("SELECT COUNT(*) FROM datasets WHERE status='complete'").fetchone()[0],
              'status': 'building'}
    def checkpoint():
        meta('stats', json.dumps(totals)); db.commit()
        if progress: progress(dict(totals))
        if shutil.disk_usage(database.parent).free < reserve_bytes:
            raise RuntimeError('Graph build checkpointed and paused: less than 600 MiB free. Resume on a disk with more space; source files were not removed.')
    active_source = None
    try:
        checkpoint()
        for item in datasets:
            did, done, state = db.execute('SELECT id,processed_rows,status FROM datasets WHERE key=?', (item['key'],)).fetchone()
            path = root / item['path']
            source_stamp = _offset_stamp(path.stat())
            active_source = (path, source_stamp, item['key'])
            if digest_file(path) != item['sha256']:
                raise ValueError('Source checksum differs from registered snapshot: ' + item['key'])
            if _offset_stamp(path.stat()) != source_stamp:
                raise ValueError('Source changed while checking its ingestion checksum: ' + item['key'])
            stored_path, previous_metadata = db.execute('SELECT path,metadata FROM datasets WHERE id=?', (did,)).fetchone()
            previous_metadata = json.loads(previous_metadata)
            if stored_path != item['path']:
                raise ValueError('Registered source path changed; choose a new output database.')
            if not 0 <= done <= item['expected_rows']:
                raise ValueError('Committed source row cursor exceeds the manifest.')
            # A copied identical source may have a new mtime; update its receipt
            # only after its bytes pass the registered checksum.
            metadata = dict(item['metadata'])
            previous_receipt = previous_metadata.get('offsets_sha256')
            if previous_receipt:
                metadata['offsets_sha256'] = previous_receipt
            if previous_metadata.get('gzidx_sha256'):
                metadata['gzidx_sha256'] = previous_metadata['gzidx_sha256']
            db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), did))
            db.commit()
            offsets_path = sources / f'{did}.offsets'; index_path = sources / f'{did}.gzidx'
            rebuild_offsets = bool((done or state == 'complete') and (
                not offsets_path.exists() or offsets_path.stat().st_size < done * 8
                or state != 'complete' and not previous_receipt))
            if rebuild_offsets:
                # A crash can leave a missing/truncated sidecar. Reconstruct only
                # the committed prefix without replaying adapters or graph rows.
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(dir=sources, suffix='.offsets.tmp', delete=False) as restored:
                        temporary = Path(restored.name)
                        with indexed_gzip.IndexedGzipFile(str(path)) as original:
                            for _ in range(done):
                                offset = original.tell()
                                if not original.readline():
                                    raise ValueError('Committed source cursor exceeds the source file.')
                                restored.write(struct.pack('<Q', offset))
                        restored.flush(); os.fsync(restored.fileno())
                    temporary.replace(offsets_path)
                finally:
                    if temporary is not None: temporary.unlink(missing_ok=True)
            if previous_receipt and digest_file(offsets_path) != previous_receipt:
                raise ValueError('Source offset index checksum differs from its ingestion receipt.')
            if state == 'complete':
                if done != item['expected_rows']:
                    raise ValueError('Complete dataset has an incomplete source row cursor.')
                if rebuild_offsets:
                    metadata['offsets_sha256'] = digest_file(offsets_path)
                # Never bless an existing legacy cache: its compressed-stream
                # dictionaries may have come from a different source file.
                with indexed_gzip.IndexedGzipFile(str(path), spacing=8*1024*1024) as verified:
                    if not import_verified_index(verified, index_path, metadata.get('gzidx_sha256')):
                        verified.build_full_index()
                        metadata['gzidx_sha256'] = _publish_seek_index(verified, index_path)
                current = path.stat()
                if (_offset_stamp(current) != source_stamp
                        or (current.st_size, current.st_mtime_ns) != (item['metadata']['bytes'], item['metadata']['mtime_ns'])):
                    raise ValueError('Source changed during graph ingestion: ' + item['key'])
                db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), did))
                db.commit()
                continue
            db.execute("UPDATE datasets SET status='building' WHERE id=?", (did,)); db.commit()
            with indexed_gzip.IndexedGzipFile(str(path), spacing=8*1024*1024) as stream, open(offsets_path, 'r+b' if offsets_path.exists() else 'w+b') as offsets:
                import_verified_index(stream, index_path, metadata.get('gzidx_sha256'))
                if done:
                    offsets.seek((done - 1) * 8); start = struct.unpack('<Q', offsets.read(8))[0]
                    stream.seek(start); stream.readline()
                offsets.seek(done * 8); offsets.truncate()
                row_number = done; pending_nodes = {}; pending_edges = []; batch_rows = 0
                def flush():
                    nonlocal pending_nodes, pending_edges, batch_rows
                    if not batch_rows: return
                    before = db.total_changes
                    db.executemany('INSERT OR IGNORE INTO nodes(id,type,label,dataset,record,offset) VALUES (?,?,?,?,?,?)',
                        [(n['id'],n['type'],n['label'][:300],did,line,offset) for n,line,offset in pending_nodes.values()])
                    totals['total_nodes'] += db.total_changes - before
                    ids = list(pending_nodes)
                    resolved = {}
                    for start in range(0,len(ids),800):
                        keys = ids[start:start+800]
                        for key,nid,label in db.execute('SELECT id,nid,label FROM nodes WHERE id IN ('+','.join('?' for _ in keys)+')', keys):
                            resolved[key] = nid
                            if label == key: placeholder_labels.add(key)
                    # Registered labels can improve an earlier identifier-only node.
                    db.executemany('UPDATE nodes SET label=?,dataset=?,record=?,offset=? WHERE id=? AND label=id',
                                   [(n['label'][:300],did,line,offset,key) for key,(n,line,offset) in pending_nodes.items() if n['label'] != key])
                    for key,(node,_,_) in pending_nodes.items():
                        if node['label'] != key: placeholder_labels.discard(key)
                    missing = list({key for a,_,b,_,_ in pending_edges for key in (a,b) if key not in resolved and key not in cache})
                    for start in range(0,len(missing),800):
                        keys = missing[start:start+800]
                        resolved.update(db.execute('SELECT id,nid FROM nodes WHERE id IN ('+','.join('?' for _ in keys)+')',keys))
                    cache.update(resolved)
                    edges = []
                    for a,p,b,line,offset in pending_edges:
                        aid = resolved.get(a) or cache.get(a); bid = resolved.get(b) or cache.get(b)
                        if aid is None or bid is None: raise ValueError('Adapter returned an edge without registered endpoints.')
                        if p not in predicates:
                            db.execute('INSERT OR IGNORE INTO predicates(name) VALUES (?)',(p,))
                            predicates[p]=db.execute('SELECT pid FROM predicates WHERE name=?',(p,)).fetchone()[0]
                        edges.append((aid,predicates[p],bid,did,line,offset))
                    while len(cache) > 400000:
                        evicted,_ = cache.popitem(last=False); placeholder_labels.discard(evicted)
                    db.executemany('INSERT INTO edges(subject,predicate,object,dataset,record,offset) VALUES (?,?,?,?,?,?)', edges)
                    totals['total_edges'] += len(edges); totals['processed_records'] += batch_rows
                    db.execute('UPDATE datasets SET processed_rows=? WHERE id=?', (row_number,did))
                    offsets.flush(); os.fsync(offsets.fileno())
                    totals['current_dataset'] = item['key']; checkpoint()
                    pending_nodes = {}; pending_edges = []; batch_rows = 0
                while True:
                    offset = stream.tell(); raw = stream.readline()
                    if not raw: break
                    row_number += 1
                    if row_number > item['expected_rows']:
                        raise ValueError('Record count exceeds manifest: ' + item['key'])
                    row = json.loads(raw)
                    if not isinstance(row,dict): raise ValueError(f'Non-object source row in {item["key"]}:{row_number}')
                    nodes, edges = adapt(item['metadata']['source'], item['metadata']['name'], row)
                    for node in nodes:
                        key = node['id']
                        if not isinstance(key,str) or not key or not isinstance(node.get('label'),str) or not isinstance(node.get('type'),str):
                            raise ValueError('Adapter returned malformed graph node.')
                        if key not in cache or (key in placeholder_labels and node['label'] != key):
                            existing = pending_nodes.get(key)
                            if not existing or existing[0]['label'] == key:
                                pending_nodes[key] = (node,row_number,offset)
                    for a,p,b in dict.fromkeys(edges):
                        pending_edges.append((a,p,b,row_number,offset))
                    offsets.write(struct.pack('<Q',offset)); batch_rows += 1
                    if batch_rows >= batch_size: flush()
                flush()
                if row_number != item['expected_rows']:
                    raise ValueError(f'Record count differs from manifest: {item["key"]} ({row_number} != {item["expected_rows"]})')
                metadata['gzidx_sha256'] = _publish_seek_index(stream, index_path)
            current = path.stat()
            if (_offset_stamp(current) != source_stamp
                    or (current.st_size, current.st_mtime_ns) != (item['metadata']['bytes'], item['metadata']['mtime_ns'])):
                raise ValueError('Source changed during graph ingestion: ' + item['key'])
            metadata['offsets_sha256'] = digest_file(offsets_path)
            db.execute("UPDATE datasets SET status='complete',metadata=? WHERE id=?",(json.dumps(metadata),did))
            totals['completed_datasets'] += 1; checkpoint()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        totals['status']='indexing'; checkpoint()
        for sql in ('CREATE INDEX IF NOT EXISTS nodes_label ON nodes(label COLLATE NOCASE)',
                    'CREATE INDEX IF NOT EXISTS edges_subject ON edges(subject)',
                    'CREATE INDEX IF NOT EXISTS edges_object ON edges(object)'):
            db.execute(sql); db.commit()
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if progress: progress(dict(totals))
        db.execute('ANALYZE'); totals['status']='complete'; totals.pop('current_dataset',None)
        checkpoint(); db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return totals
    except Exception:
        db.rollback()
        if active_source is not None:
            path, source_stamp, key = active_source
            try:
                unchanged = _offset_stamp(path.stat()) == source_stamp
            except OSError:
                unchanged = False
            if not unchanged:
                # Checkpoints may already contain rows read during the change.
                # Restoring the old gzip cannot prove those rows were authentic.
                meta('invalid_source', key)
        persisted = db.execute("SELECT value FROM metadata WHERE key='stats'").fetchone()
        if persisted: totals.update(json.loads(persisted[0]))
        totals['status']='paused'; meta('stats',json.dumps(totals)); db.commit()
        raise
    finally: db.close()

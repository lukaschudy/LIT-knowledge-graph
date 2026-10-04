"""Read exact original JSON using committed source identities and gzip indexes."""
from pathlib import Path
import json
import os

from .store import HarvestGraph, _file_digest, _offset_stamp


def import_verified_index(stream, index, receipt):
    """Untrusted gzip dictionaries can silently replace source bytes on seek."""
    import indexed_gzip
    if not receipt:
        return False
    try:
        stamp = _offset_stamp(index.stat())
        if _file_digest(str(index), stamp) != receipt:
            return False
        with index.open('rb') as handle:
            if _offset_stamp(os.fstat(handle.fileno())) != stamp:
                return False
            stream.import_index(fileobj=handle)
            if _offset_stamp(os.fstat(handle.fileno())) != stamp:
                raise ValueError('Source seek cache changed while importing its verified bytes.')
        return True
    except (OSError, indexed_gzip.ZranError):
        return False


def read_record(database, root, pointer):
    import indexed_gzip
    if not isinstance(pointer, dict):
        raise ValueError('Invalid source record pointer.')
    root = Path(root).resolve()
    did = pointer.get('dataset_id', pointer.get('dataset'))
    row = pointer.get('row', pointer.get('record'))
    # Supplied offsets/paths are hints, not authority to reattribute another row.
    graph = HarvestGraph(database, root)
    canonical = graph.record_pointer(did, row)
    if canonical is None or canonical['offset'] is None:
        raise ValueError('Source row has not been imported.')
    for field in ('path', 'sha256', 'offset', 'id'):
        if pointer.get(field) is not None and pointer[field] != canonical[field]:
            raise ValueError('Source pointer disagrees with the indexed record.')
    path = (root / canonical['path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Invalid source path.')
    metadata = canonical['metadata']
    stat = path.stat()
    if (metadata.get('bytes', stat.st_size) != stat.st_size
            or metadata.get('mtime_ns', stat.st_mtime_ns) != stat.st_mtime_ns):
        raise ValueError('The source file changed since graph ingestion. Rebuild before using this record.')
    if _file_digest(str(path), _offset_stamp(stat)) != canonical['sha256']:
        raise ValueError('The source checksum differs from the indexed snapshot. Rebuild before using this record.')
    directory = Path(str(database) + '.sources')
    with indexed_gzip.IndexedGzipFile(str(path), spacing=8*1024*1024) as stream:
        index = directory / f"{canonical['dataset_id']}.gzidx"
        import_verified_index(stream, index, metadata.get('gzidx_sha256'))
        if row > 1:
            preceding = graph.record_pointer(canonical['dataset_id'], row - 1)
            stream.seek(preceding['offset'])
            stream.readline()
            if stream.tell() != canonical['offset']:
                raise ValueError('The indexed source row is not consecutive with its predecessor.')
        else:
            stream.seek(canonical['offset'])
        raw = stream.readline()
    current = path.stat()
    if _offset_stamp(current) != _offset_stamp(stat):
        raise ValueError('The source file changed while reading this record.')
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('The indexed source row is not valid JSON.') from None
    if not isinstance(data, dict):
        raise ValueError('The indexed source row is not an object.')
    return {'data': data, 'provenance': {**pointer, **canonical}}

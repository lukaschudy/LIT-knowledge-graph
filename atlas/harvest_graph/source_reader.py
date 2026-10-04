"""Read exact original JSON using compact byte-offset and gzip seek indexes."""
from pathlib import Path
import json
import struct


def read_record(database, root, pointer):
    import indexed_gzip
    root=Path(root).resolve(); path=(root/pointer['path']).resolve()
    if not path.is_relative_to(root): raise ValueError('Invalid source path.')
    metadata=pointer.get('metadata') or {}
    if isinstance(metadata,str): metadata=json.loads(metadata)
    stat=path.stat()
    if metadata.get('bytes',stat.st_size)!=stat.st_size or metadata.get('mtime_ns',stat.st_mtime_ns)!=stat.st_mtime_ns:
        raise ValueError('The source file changed since graph ingestion. Rebuild before using this record.')
    did=pointer.get('dataset_id',pointer.get('dataset')); row=pointer.get('row',pointer.get('record'))
    directory=Path(str(database)+'.sources'); offset=pointer.get('offset')
    if offset is None:
        with (directory/f'{did}.offsets').open('rb') as offsets:
            offsets.seek((int(row)-1)*8); raw=offsets.read(8)
            if len(raw)!=8: raise ValueError('Source row has not been imported.')
            offset=struct.unpack('<Q',raw)[0]
    with indexed_gzip.IndexedGzipFile(str(path),spacing=8*1024*1024) as stream:
        index=directory/f'{did}.gzidx'
        if index.exists(): stream.import_index(filename=str(index))
        stream.seek(offset); raw=stream.readline()
    return {'data':json.loads(raw), 'provenance':{**pointer,'offset':offset,
        'source_urls':metadata.get('source_urls',[]),'licenses':metadata.get('licenses',[])}}

from contextlib import closing
import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

@unittest.skipUnless(importlib.util.find_spec('indexed_gzip'), 'install the graph extra for gzip indexing tests')
class HarvestBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.database=self.root/'graph.sqlite'
        self.rows=[{'GENE SYMBOL':'EPG5','GENE ID (HGNC)':'HGNC:29331','DISEASE LABEL':'Vici syndrome',
                    'DISEASE ID (MONDO)':'MONDO:0010282','CLASSIFICATION':'Definitive'},
                   {'GENE SYMBOL':'WDR45','GENE ID (HGNC)':'HGNC:28912','DISEASE LABEL':'BPAN',
                    'DISEASE ID (MONDO)':'MONDO:0018955','CLASSIFICATION':'Limited'}]
        self.add_dataset('clingen','gene_disease_validity',self.rows)
        self.add_dataset('unknown','native',[{'unmapped_metadata':'all fields must remain retrievable'}])
    def add_dataset(self,source,name,rows):
        path=self.root/f'data/processed/harvest/{source}/{name}.jsonl.gz';path.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(path,'wt') as f:
            for row in rows:f.write(json.dumps(row)+'\n')
        manifest={'artifacts':{'fixture':{'url':'https://example.org/fixture','license':'fixture'}},
                  'datasets':{name:{'path':str(path.relative_to(self.root)),'sha256':sha256(path.read_bytes()).hexdigest(),
                              'records':len(rows),'bytes':path.stat().st_size}}}
        dest=self.root/f'data/harvest-manifests/{source}.json';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(manifest))
    def test_all_rows_roundtrip_and_resume_does_not_duplicate_edges(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.source_reader import read_record
        stats=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(stats['status'],'complete');self.assertEqual(stats['processed_records'],3)
        with closing(sqlite3.connect(self.database)) as db, db:
            count=db.execute('select count(*) from edges').fetchone()[0]
            did,path,metadata=db.execute("select id,path,metadata from datasets where key='unknown/native'").fetchone()
        original=read_record(self.database,self.root,{'dataset_id':did,'path':path,'row':1,'metadata':json.loads(metadata)})
        self.assertEqual(original['data'],{'unmapped_metadata':'all fields must remain retrievable'})
        resumed=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(resumed['total_edges'],count)
        self.assertEqual(resumed['processed_records'],3)
    def test_changed_source_fails_before_its_rows_are_published(self):
        from atlas.harvest_graph.build import build
        path=next((self.root/'data/processed/harvest/clingen').glob('*.gz'))
        payload=bytearray(path.read_bytes());payload[-1]^=1;path.write_bytes(payload)
        with self.assertRaisesRegex(ValueError,'checksum'):
            build(self.root,self.database,reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertEqual(db.execute('select count(*) from nodes').fetchone()[0],0)
    def test_checkpoint_resume_preserves_row_pointer_alignment(self):
        from atlas.harvest_graph.build import build
        interrupted=[False]
        def stop(stats):
            if stats['processed_records']==1 and not interrupted[0]:
                interrupted[0]=True;raise RuntimeError('Simulated interruption')
        with self.assertRaisesRegex(RuntimeError,'Simulated'):
            build(self.root,self.database,batch_size=1,reserve_bytes=0,progress=stop)
        result=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(result['processed_records'],3)
        with closing(sqlite3.connect(self.database)) as db, db:
            rows=db.execute('select id,processed_rows from datasets').fetchall()
        for did,count in rows:self.assertEqual(Path(str(self.database)+f'.sources/{did}.offsets').stat().st_size,count*8)

    def test_cached_placeholder_label_is_upgraded_in_later_batch(self):
        from unittest.mock import patch
        from atlas.harvest_graph.build import build
        def mapping(source,dataset,row):
            if source != 'clingen': return [],[]
            node={'id':'Test:shared','type':'Gene','label':'Test:shared' if row['GENE SYMBOL']=='EPG5' else 'Readable gene'}
            return [node],[]
        with patch('atlas.harvest_graph.build.adapt',mapping):
            build(self.root,self.database,batch_size=1,reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertEqual(db.execute("select label,record from nodes where id='Test:shared'").fetchone(),('Readable gene',2))

    def test_completed_source_is_rechecked_before_resume_reports_success(self):
        from atlas.harvest_graph.build import build
        build(self.root, self.database, batch_size=1, reserve_bytes=0)
        path = next((self.root/'data/processed/harvest/clingen').glob('*.gz'))
        data = bytearray(path.read_bytes()); data[-1] ^= 1; path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            build(self.root, self.database, batch_size=1, reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertEqual(json.loads(db.execute("SELECT value FROM metadata WHERE key='stats'").fetchone()[0])['status'], 'paused')

    def test_truncated_committed_offset_sidecar_is_rebuilt_without_duplicate_edges(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        from atlas.harvest_graph.source_reader import read_record
        original = build(self.root, self.database, batch_size=1, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        ds = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        sidecar = Path(str(self.database) + f".sources/{ds['dataset_id']}.offsets")
        sidecar.write_bytes(b'partial')
        with self.assertRaisesRegex(ValueError, 'truncated|checksum'):
            graph.record_pointer(ds['dataset_id'], 2)
        restored = build(self.root, self.database, batch_size=1, reserve_bytes=0)
        self.assertEqual(restored['total_edges'], original['total_edges'])
        self.assertEqual(restored['completed_datasets'], original['completed_datasets'])
        self.assertEqual(sidecar.stat().st_size, 16)
        pointer = graph.record_pointer(ds['dataset_id'], 2)
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], self.rows[1])

    def test_uncommitted_offset_tail_is_discarded_on_resume(self):
        from unittest.mock import patch
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.adapters import adapt
        rows = [dict(self.rows[0], **{'GENE SYMBOL': 'G'+str(i), 'GENE ID (HGNC)': 'HGNC:'+str(i)}) for i in range(1, 5)]
        self.add_dataset('clingen', 'gene_disease_validity', rows)
        def interrupted(source, name, row):
            if row.get('GENE SYMBOL') == 'G4':
                raise RuntimeError('Interrupted after an uncommitted offset')
            return adapt(source, name, row)
        with patch('atlas.harvest_graph.build.adapt', interrupted):
            with self.assertRaisesRegex(RuntimeError, 'uncommitted'):
                build(self.root, self.database, batch_size=2, reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            did, done = db.execute("SELECT id,processed_rows FROM datasets WHERE key LIKE 'clingen/%'").fetchone()
            self.assertEqual(done, 2)
            before = db.execute('SELECT COUNT(*) FROM edges').fetchone()[0]
        sidecar = Path(str(self.database) + f'.sources/{did}.offsets')
        self.assertEqual(sidecar.stat().st_size, 24)
        result = build(self.root, self.database, batch_size=2, reserve_bytes=0)
        self.assertEqual(sidecar.stat().st_size, 32)
        self.assertEqual(result['total_edges'], 2 * before)
        self.assertEqual(result['processed_records'], 5)

    def test_second_builder_is_rejected_without_mutating_row_cursors(self):
        from atlas.harvest_graph.build import build
        attempted = []
        def concurrent(stats):
            if attempted:
                return
            attempted.append(True)
            with self.assertRaisesRegex(ValueError, 'already building'):
                build(self.root, self.database, batch_size=1, reserve_bytes=0)
        result = build(self.root, self.database, batch_size=1, reserve_bytes=0, progress=concurrent)
        self.assertTrue(attempted)
        self.assertEqual(result['processed_records'], 3)
        self.assertEqual(result['status'], 'complete')

    def test_unrelated_database_is_left_unchanged(self):
        from atlas.harvest_graph.build import build
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE private_fixture(value TEXT)')
            db.execute("INSERT INTO private_fixture VALUES ('keep')")
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, 'not a harvest index'):
            build(self.root, self.database, reserve_bytes=0)
        self.assertEqual(self.database.read_bytes(), before)

    def test_source_pointer_cannot_override_registered_path_row_or_offset(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        from atlas.harvest_graph.source_reader import read_record
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        pointer = graph.record_pointer(dataset['dataset_id'], 1)
        for changes in [{'offset': 1}, {'row': 999}, {'path': 'another.jsonl.gz'},
                        {'sha256': 'forged'}, {'id': 'record:forged'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                read_record(self.database, self.root, {**pointer, **changes})
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], self.rows[0])

    def test_corrupt_optional_seek_cache_does_not_hide_valid_source_rows(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        from atlas.harvest_graph.source_reader import read_record
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        index = Path(str(self.database) + f".sources/{dataset['dataset_id']}.gzidx")
        index.write_bytes(b'broken seek cache')
        pointer = graph.record_pointer(dataset['dataset_id'], 2)
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], self.rows[1])

    def test_changed_source_during_build_never_gets_complete_receipt(self):
        import os
        from atlas.harvest_graph.build import build
        changed = []
        def change_after_checkpoint(stats):
            if stats['processed_records'] == 1 and not changed:
                changed.append(True)
                path = next((self.root/'data/processed/harvest/clingen').glob('*.gz'))
                current = path.stat()
                os.utime(path, ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(ValueError, 'changed during'):
            build(self.root, self.database, batch_size=1, reserve_bytes=0, progress=change_after_checkpoint)
        with closing(sqlite3.connect(self.database)) as db, db:
            self.assertNotEqual(db.execute("SELECT status FROM datasets WHERE key LIKE 'clingen/%'").fetchone()[0], 'complete')
            self.assertEqual(json.loads(db.execute("SELECT value FROM metadata WHERE key='stats'").fetchone()[0])['status'], 'paused')

    def test_swapped_full_length_offsets_cannot_reattribute_source_rows(self):
        import struct
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        from atlas.harvest_graph.source_reader import read_record
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        pointer = graph.record_pointer(dataset['dataset_id'], 2)
        sidecar = Path(str(self.database) + f".sources/{dataset['dataset_id']}.offsets")
        first, second = struct.unpack('<QQ', sidecar.read_bytes())
        sidecar.write_bytes(struct.pack('<QQ', second, first))
        for row in (1, 2):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'inconsistent|checksum'):
                read_record(self.database, self.root, {'dataset_id': dataset['dataset_id'], 'row': row})
        with self.assertRaises(ValueError):
            read_record(self.database, self.root, pointer)

    def test_offset_receipt_is_cached_and_invalidated_when_sidecar_changes(self):
        import os
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph, _offset_digest
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        self.assertEqual(len(dataset['metadata']['offsets_sha256']), 64)
        _offset_digest.cache_clear()
        graph.record_pointer(dataset['dataset_id'], 1)
        graph.record_pointer(dataset['dataset_id'], 2)
        self.assertEqual(_offset_digest.cache_info().misses, 1)
        self.assertEqual(_offset_digest.cache_info().hits, 1)
        sidecar = Path(str(self.database) + f".sources/{dataset['dataset_id']}.offsets")
        before = sidecar.stat()
        raw = bytearray(sidecar.read_bytes()); raw[-1] ^= 1; sidecar.write_bytes(raw)
        os.utime(sidecar, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'checksum'):
            graph.record_pointer(dataset['dataset_id'], 1)
        self.assertEqual(_offset_digest.cache_info().misses, 2)
        with self.assertRaisesRegex(ValueError, 'checksum'):
            build(self.root, self.database, reserve_bytes=0)

    def test_legacy_offset_indexes_keep_bounded_checks_without_fake_receipts(self):
        import struct
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        build(self.root, self.database, reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db, db:
            did, metadata = db.execute("SELECT id,metadata FROM datasets WHERE key LIKE 'clingen/%'").fetchone()
            metadata = json.loads(metadata); metadata.pop('offsets_sha256')
            db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), did))
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['dataset_id'] == did)
        self.assertNotIn('offsets_sha256', dataset['metadata'])
        sidecar = Path(str(self.database) + f'.sources/{did}.offsets')
        first, second = struct.unpack('<QQ', sidecar.read_bytes())
        sidecar.write_bytes(struct.pack('<QQ', second, first))
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            graph.record_pointer(did, 2)

    def test_matching_table_names_with_wrong_columns_are_rejected_before_wal(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        with closing(sqlite3.connect(self.database)) as db, db:
            for name in ('datasets', 'nodes', 'predicates', 'edges', 'metadata'):
                db.execute(f'CREATE TABLE {name}(private_value TEXT)')
            db.execute("INSERT INTO nodes VALUES ('keep unchanged')")
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, 'required schema'):
            build(self.root, self.database, reserve_bytes=0)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(Path(str(self.database) + '.sources').exists())
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
        with self.assertRaisesRegex(ValueError, 'required schema'):
            HarvestGraph(self.database, self.root)

    def test_missing_unique_constraint_cannot_duplicate_resumed_rows(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import SCHEMA
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript(SCHEMA.replace('id TEXT UNIQUE NOT NULL', 'id TEXT NOT NULL'))
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, 'required schema'):
            build(self.root, self.database, reserve_bytes=0)
        self.assertEqual(self.database.read_bytes(), before)

    def test_wrong_snapshot_identity_is_rejected_before_wal(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import initialize
        with closing(sqlite3.connect(self.database)) as db, db:
            initialize(db)
            db.execute("INSERT INTO metadata VALUES ('build_id','some-other-snapshot')")
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, 'different source snapshots'):
            build(self.root, self.database, reserve_bytes=0)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse(Path(str(self.database) + '.sources').exists())

    def test_valid_seek_cache_from_another_source_cannot_replace_original_bytes(self):
        import indexed_gzip
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph
        from atlas.harvest_graph.source_reader import read_record
        # Both streams have identical row/compressed block layouts. The wrong
        # dictionary is valid and silently yields B from the A source if trusted.
        rows = [{'value': 'A' * 10000}] * 2000
        self.add_dataset('unknown', 'native', rows)
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'] == 'unknown/native')
        pointer = graph.record_pointer(dataset['dataset_id'], 1500)
        source = self.root / pointer['path']
        alternate = source.with_name('evilxx.jsonl.gz')
        with gzip.open(alternate, 'wt') as stream:
            for _ in rows:
                stream.write(json.dumps({'value': 'B' * 10000}) + '\n')
        cache = Path(str(self.database) + f".sources/{dataset['dataset_id']}.gzidx")
        with indexed_gzip.IndexedGzipFile(str(alternate), spacing=8*1024*1024) as stream:
            stream.build_full_index()
            stream.export_index(filename=str(cache))
        with indexed_gzip.IndexedGzipFile(str(source)) as unsafe:
            unsafe.import_index(filename=str(cache))
            unsafe.seek(pointer['offset'])
            self.assertEqual(json.loads(unsafe.readline())['value'], 'B' * 10000)
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], rows[1499])
        # Legacy metadata must ignore the wrong-but-valid cache as well. Explicit
        # resume regenerates it from verified source bytes, without replaying rows.
        with closing(sqlite3.connect(self.database)) as db, db:
            metadata = json.loads(db.execute('SELECT metadata FROM datasets WHERE id=?', (dataset['dataset_id'],)).fetchone()[0])
            metadata.pop('gzidx_sha256')
            db.execute('UPDATE datasets SET metadata=? WHERE id=?', (json.dumps(metadata), dataset['dataset_id']))
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], rows[1499])
        wrong_digest = sha256(cache.read_bytes()).hexdigest()
        resumed = build(self.root, self.database, reserve_bytes=0)
        updated = graph.record_pointer(dataset['dataset_id'], 1500)
        self.assertNotEqual(updated['metadata']['gzidx_sha256'], wrong_digest)
        self.assertEqual(updated['metadata']['gzidx_sha256'], sha256(cache.read_bytes()).hexdigest())
        self.assertEqual(resumed['processed_records'], 2002)
        self.assertEqual(read_record(self.database, self.root, updated)['data'], rows[1499])

    def test_interruption_after_seek_cache_publication_resumes_without_duplicates(self):
        from unittest.mock import patch
        from atlas.harvest_graph import build as module
        publish = module._publish_seek_index
        def interrupted(*args):
            publish(*args)
            raise RuntimeError('Stopped between seek cache and receipt publication')
        with patch.object(module, '_publish_seek_index', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'receipt publication'):
                module.build(self.root, self.database, batch_size=1, reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db:
            count = db.execute('SELECT COUNT(*) FROM edges').fetchone()[0]
        resumed = module.build(self.root, self.database, batch_size=1, reserve_bytes=0)
        self.assertEqual(resumed['total_edges'], count)
        self.assertEqual(resumed['processed_records'], 3)
        self.assertEqual(resumed['status'], 'complete')

    def test_empty_source_missing_offset_sidecar_can_be_recovered(self):
        from atlas.harvest_graph.build import build
        self.add_dataset('unknown', 'native', [])
        build(self.root, self.database, reserve_bytes=0)
        with closing(sqlite3.connect(self.database)) as db:
            did = db.execute("SELECT id FROM datasets WHERE key='unknown/native'").fetchone()[0]
        sidecar = Path(str(self.database) + f'.sources/{did}.offsets')
        sidecar.unlink()
        self.assertEqual(build(self.root, self.database, reserve_bytes=0)['status'], 'complete')
        self.assertEqual(sidecar.read_bytes(), b'')

    def test_source_checksum_cache_detects_same_size_restored_mtime_corruption(self):
        import os
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.store import HarvestGraph, _file_digest
        from atlas.harvest_graph.source_reader import read_record
        build(self.root, self.database, reserve_bytes=0)
        graph = HarvestGraph(self.database, self.root)
        dataset = next(d for d in graph.datasets() if d['key'].startswith('clingen/'))
        pointer = graph.record_pointer(dataset['dataset_id'], 1)
        _file_digest.cache_clear()
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], self.rows[0])
        misses = _file_digest.cache_info().misses
        self.assertEqual(read_record(self.database, self.root, pointer)['data'], self.rows[0])
        self.assertEqual(_file_digest.cache_info().misses, misses)
        source = self.root / pointer['path']
        before = source.stat()
        raw = bytearray(source.read_bytes()); raw[-1] ^= 1; source.write_bytes(raw)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(source.stat().st_size, before.st_size)
        with self.assertRaisesRegex(ValueError, 'source checksum'):
            read_record(self.database, self.root, pointer)
        self.assertGreater(_file_digest.cache_info().misses, misses)

    def test_changed_source_cannot_resume_checkpointed_rows_after_bytes_are_restored(self):
        import os
        from atlas.harvest_graph.build import build
        source = next((self.root/'data/processed/harvest/clingen').glob('*.gz'))
        original = source.read_bytes()
        before = source.stat()
        changed = []
        def change_source(stats):
            if stats['processed_records'] == 1 and not changed:
                changed.append(True)
                raw = bytearray(original); raw[4] ^= 1
                source.write_bytes(raw)
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'Source changed'):
            build(self.root, self.database, batch_size=1, reserve_bytes=0, progress=change_source)
        source.write_bytes(original)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        with closing(sqlite3.connect(self.database)) as db:
            self.assertTrue(db.execute("SELECT value FROM metadata WHERE key='invalid_source'").fetchone())
        with self.assertRaisesRegex(ValueError, 'earlier ingestion'):
            build(self.root, self.database, batch_size=1, reserve_bytes=0)

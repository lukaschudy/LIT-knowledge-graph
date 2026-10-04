"""HTTP integration checks for provenance pointers into original harvest rows."""
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
import unittest
from urllib.parse import quote
from urllib.request import urlopen

from atlas.harvest_graph.store import HarvestGraph, initialize
from atlas.server import create_server
from atlas.store import GraphStore


@unittest.skipUnless(importlib.util.find_spec('indexed_gzip'), 'install the graph extra for raw harvest API tests')
class HarvestAPITests(unittest.TestCase):
    def setUp(self):
        import indexed_gzip

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_path = self.root / 'harvest.sqlite'
        source = self.root / 'sources' / 'two-rows.jsonl.gz'
        source.parent.mkdir()
        raw_rows = [
            {'id': 'gene:1', 'symbol': 'GENE1'},
            {'source_specific_unmapped_field': 'preserved raw payload'},
        ]
        with gzip.open(source, 'wt', encoding='utf-8') as handle:
            for row in raw_rows:
                handle.write(json.dumps(row) + '\n')
        offsets_path = Path(str(self.db_path) + '.sources')
        offsets_path.mkdir(exist_ok=True)
        offsets = []
        with indexed_gzip.IndexedGzipFile(str(source), spacing=8 * 1024 * 1024) as stream:
            while True:
                offset = stream.tell()
                if not stream.readline():
                    break
                offsets.append(offset)
            stream.export_index(filename=str(self.db_path) + '.sources/3.gzidx')
        (offsets_path / '3.offsets').write_bytes(b''.join(struct.pack('<Q', x) for x in offsets))
        metadata = {'name': 'tiny fixture', 'source_urls': ['https://example.org/source'],
                    'licenses': ['CC0'], 'bytes': source.stat().st_size,
                    'mtime_ns': source.stat().st_mtime_ns}
        with sqlite3.connect(self.db_path) as db:
            initialize(db)
            db.execute('''INSERT INTO datasets(id,key,path,sha256,expected_rows,processed_rows,status,metadata)
                          VALUES(3,'fixture/unmapped','sources/two-rows.jsonl.gz','fixturehash',2,2,'complete',?)''',
                       (json.dumps(metadata),))
            db.executemany('INSERT INTO nodes(id,type,label,dataset,record,offset) VALUES(?,?,?,?,?,?)', [
                ('gene:1', 'Gene', 'GENE1', 3, 1, offsets[0]),
                ('disease:1', 'Disease', 'Fixture condition', 3, 1, offsets[0]),
            ])
            db.execute("INSERT INTO predicates(name) VALUES('ASSOCIATED_WITH')")
            predicate_id = db.execute("SELECT pid FROM predicates WHERE name='ASSOCIATED_WITH'").fetchone()[0]
            db.execute('''INSERT INTO edges(subject,predicate,object,dataset,record,offset)
                          VALUES(1,?,?,3,1,?)''', (predicate_id, 2, offsets[0]))
            db.execute("INSERT INTO metadata(key,value) VALUES('stats',?)",
                       (json.dumps({'total_nodes': 2, 'total_edges': 1, 'total_records': 2,
                                    'processed_records': 2, 'total_datasets': 1,
                                    'completed_datasets': 1, 'status': 'complete'}),))
        self.harvest = HarvestGraph(self.db_path, self.root)
        self.curated_store = GraphStore()
        fixture = Path(__file__).resolve().parents[1] / 'data' / 'fixtures' / 'atlas-demo.json'
        self.curated_store.load_bundle(json.loads(fixture.read_text(encoding='utf-8')))
        self.server = create_server(self.curated_store, port=0, harvest=self.harvest)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.curated_store.close)
        self.base = f'http://{self.server.server_address[0]}:{self.server.server_address[1]}'

    def get_json(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))

    def test_node_and_claim_expand_their_top_level_pointer_to_exact_original_row(self):
        node = self.get_json('/api/harvest/node?id=gene%3A1')
        self.assertEqual(node['provenance']['id'], 'record:3:1')
        self.assertEqual(node['record']['data'], {'id': 'gene:1', 'symbol': 'GENE1'})
        claim = self.get_json('/api/harvest/claim?id=harvest%3Aedge%3A1')
        self.assertEqual(claim['provenance']['id'], 'record:3:1')
        self.assertEqual(claim['record']['data'], {'id': 'gene:1', 'symbol': 'GENE1'})
        self.assertEqual(claim['predicate'], 'ASSOCIATED_WITH')

    def test_every_unmapped_row_remains_browsable_and_projection_has_no_fake_date(self):
        rows = self.get_json('/api/harvest/records?dataset=3&page=0&limit=2')
        self.assertEqual([item['id'] for item in rows['records']], ['record:3:1', 'record:3:2'])
        raw = self.get_json('/api/harvest/record?id=record%3A3%3A2')
        self.assertEqual(raw['record']['data'], {'source_specific_unmapped_field': 'preserved raw payload'})
        self.assertEqual(raw['record']['provenance']['licenses'], ['CC0'])
        graph = self.get_json('/api/harvest/graph?limit=100')
        self.assertNotIn('created_at', graph['dataset'])
        self.assertEqual(graph['harvest']['total_records'], 2)


if __name__ == '__main__':
    unittest.main()

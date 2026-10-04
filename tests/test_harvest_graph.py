"""Bounded read-only API tests for the harvested graph projection."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from atlas.harvest_graph.store import HarvestGraph, initialize


class HarvestGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / 'harvest.sqlite'
        source_root = root / 'sources'
        source_root.mkdir()
        (source_root / 'input.jsonl.gz').write_bytes(b'not read by the graph projection')
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            initialize(conn)
            conn.execute('''INSERT INTO datasets(id,key,path,sha256,expected_rows,processed_rows,status,metadata)
                            VALUES(3,?,?,?,?,?,?,?)''',
                         ('source-a', 'input.jsonl.gz', 'a' * 64, 3, 3, 'complete',
                          json.dumps({'name': 'Fixture source', 'source_urls': ['https://example.org/data'],
                                      'licenses': ['CC0']})))
            conn.executemany('INSERT INTO nodes(nid,id,type,label,dataset,record,offset) VALUES(?,?,?,?,?,?,?)', [
                (1, 'HGNC:123', 'Gene', 'WDR45', 3, 1, 0),
                (2, 'DO:1', 'Disease', 'Beta-propeller protein-associated neurodegeneration (BPAN)', 3, 1, 0),
                (3, 'HGNC:999', 'Gene', 'WDR45B', 3, 2, 100),
            ])
            conn.executemany('INSERT INTO predicates(pid,name) VALUES(?,?)', [(1, 'ASSOCIATED_WITH')])
            conn.executemany('INSERT INTO edges(eid,subject,predicate,object,dataset,record,offset) VALUES(?,?,?,?,?,?,?)', [
                (11, 1, 1, 2, 3, 1, 0),
                (12, 3, 1, 2, 3, 2, 100),
            ])
            conn.execute('CREATE INDEX idx_nodes_label_nocase ON nodes(label COLLATE NOCASE)')
            conn.execute('CREATE INDEX idx_edges_subject ON edges(subject)')
            conn.execute('CREATE INDEX idx_edges_object ON edges(object)')
            conn.executemany('INSERT INTO metadata(key,value) VALUES(?,?)', [
                ('stats', json.dumps({'total_nodes': 3, 'total_edges': 2, 'total_records': 3,
                                      'processed_records': 3, 'total_datasets': 1,
                                      'completed_datasets': 1, 'status': 'complete'})),
                ('source_root', str(source_root)),
                ('build_id', 'build-1'),
            ])
        offsets = Path(str(self.db_path) + '.sources')
        offsets.mkdir()
        (offsets / '3.offsets').write_bytes(struct.pack('<QQQ', 0, 100, 200))
        self.graph = HarvestGraph(self.db_path, source_root)

    def tearDown(self):
        self.temp.cleanup()

    def test_initialize_creates_agreed_tables_and_column_contract(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            initialize(conn)
            expected = {
                'datasets': ['id', 'key', 'path', 'sha256', 'expected_rows', 'processed_rows', 'status', 'metadata'],
                'nodes': ['nid', 'id', 'type', 'label', 'dataset', 'record', 'offset'],
                'predicates': ['pid', 'name'],
                'edges': ['eid', 'subject', 'predicate', 'object', 'dataset', 'record', 'offset'],
                'metadata': ['key', 'value'],
            }
            for table, columns in expected.items():
                actual = [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]
                self.assertEqual(actual, columns)
            predicate_type = next(row[2] for row in conn.execute('PRAGMA table_info(edges)') if row[1] == 'predicate')
            self.assertEqual(predicate_type.upper(), 'INTEGER')

    def test_status_uses_build_stats_and_keeps_records_distinct_from_nodes(self):
        status = self.graph.status()
        self.assertEqual(status['total_nodes'], 3)
        self.assertEqual(status['total_edges'], 2)
        self.assertEqual(status['total_records'], 3)
        self.assertEqual(status['processed_records'], 3)
        self.assertEqual(status['completed_datasets'], 1)
        self.assertFalse(status['source_rows_materialized_as_nodes'])
        self.assertEqual(status['datasets'][0]['id'], 'dataset:3')
        self.assertEqual(status['datasets'][0]['metadata']['name'], 'Fixture source')

    def test_search_is_exact_id_then_indexed_label_prefix(self):
        exact = self.graph.search('HGNC:123')
        self.assertEqual([n['id'] for n in exact['results']], ['HGNC:123'])
        prefix = self.graph.search('WDR')
        self.assertEqual([n['id'] for n in prefix['results']], ['HGNC:123', 'HGNC:999'])
        self.assertEqual(self.graph.search('R45')['results'], [])
        self.assertTrue(prefix['results'][0]['properties']['harvest'])

    def test_graph_is_bounded_and_never_fabricates_evidence_or_sources(self):
        result = self.graph.graph(limit=2, offset=0)
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(len(result['claims']), 1)
        self.assertEqual(result['evidence'], [])
        self.assertEqual(result['sources'], [])
        self.assertEqual(result['harvest']['total_nodes'], 3)
        self.assertEqual(result['harvest']['next_offset'], 2)
        self.assertTrue(result['harvest']['truncated'])
        self.assertEqual(result['claims'][0]['id'], 'harvest:edge:11')
        self.assertEqual(result['claims'][0]['context']['scope'], 'unreviewed source relationship')
        self.assertEqual(result['claims'][0]['extraction_confidence'], None)
        self.assertIn('record:3:1', json.dumps(result['claims'][0]['context']))
        self.assertEqual(set(result['nodes'][0]['provenance']), {'id', 'dataset', 'dataset_id', 'row', 'offset'})
        self.assertNotIn('source_urls', result['claims'][0]['provenance'])
        self.assertNotIn('metadata', result['claims'][0]['context']['record'])
        self.assertLessEqual(len(self.graph.graph(limit=500000)['nodes']), 3000)
        last_page = self.graph.graph(limit=2, offset=2)
        self.assertEqual(last_page['harvest']['next_offset'], None)
        self.assertFalse(last_page['harvest']['truncated'])

    def test_focus_graph_and_node_claim_provenance_use_one_based_rows(self):
        focused = self.graph.graph(limit=3, focus='HGNC:123')
        self.assertEqual({n['id'] for n in focused['nodes']}, {'HGNC:123', 'DO:1'})
        node = self.graph.node('HGNC:123')
        self.assertEqual(node['properties']['record']['id'], 'record:3:1')
        self.assertEqual(node['properties']['record']['offset'], 0)
        claim = self.graph.claim('harvest:edge:11')
        self.assertEqual(claim['context']['record']['row'], 1)
        self.assertEqual(claim['subject'], 'HGNC:123')
        self.assertEqual(claim['provenance']['source_urls'], ['https://example.org/data'])
        self.assertEqual(node['provenance']['licenses'], ['CC0'])
        self.assertIsNone(self.graph.claim('claim:forged'))

    def test_offset_sidecar_is_used_without_scanning_mapped_rows(self):
        # If lookup still probes nodes/edges first, deleting these mapped rows
        # would make the valid virtual source pointer unavailable.
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute('DELETE FROM edges')
            conn.execute('DELETE FROM nodes')
        pointer = self.graph.record_pointer(3, 3)
        self.assertEqual(pointer['offset'], 200)

    def test_focus_expansion_uses_edge_id_cursor_and_returns_next_page(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executemany('INSERT INTO nodes(nid,id,type,label,dataset,record,offset) VALUES(?,?,?,?,?,?,?)', [
                (i, f'GENE:{i}', 'Gene', f'Gene {i}', 3, 3, 200) for i in range(4, 10)
            ])
            conn.executemany('INSERT INTO edges(eid,subject,predicate,object,dataset,record,offset) VALUES(?,?,?,?,?,?,?)', [
                (eid, 1, 1, eid - 9, 3, 3, 200) for eid in range(13, 19)
            ])
        first = self.graph.graph(limit=3, focus='HGNC:123')
        self.assertEqual(first['harvest']['cursor_kind'], 'edge_id')
        last_first_eid = int(first['claims'][-1]['id'].rsplit(':', 1)[-1])
        self.assertEqual(first['harvest']['next_offset'], last_first_eid)
        self.assertTrue(first['harvest']['truncated'])
        second = self.graph.graph(limit=3, focus='HGNC:123', offset=first['harvest']['next_offset'])
        self.assertTrue(set(c['id'] for c in first['claims']).isdisjoint(c['id'] for c in second['claims']))
        self.assertGreater(second['claims'][0]['id'], first['claims'][-1]['id'])

    def test_dataset_and_virtual_records_are_paginated_even_without_mapped_edges(self):
        dataset = self.graph.dataset('dataset:3')
        self.assertEqual(dataset['type'], 'Dataset')
        page = self.graph.records('source-a', page=0, limit=2)
        self.assertEqual([r['id'] for r in page['records']], ['record:3:1', 'record:3:2'])
        self.assertEqual(page['records'][1]['offset'], 100)
        self.assertEqual(self.graph.record(3, 3)['id'], 'record:3:3')
        self.assertEqual(self.graph.record_pointer(3, 3)['offset'], 200)
        self.assertIsNone(self.graph.record_pointer(3, 4))
        self.assertEqual(len(page['records']) + len(self.graph.records(3, page=1, limit=2)['records']), 3)

    def test_focus_requires_a_usable_page_and_large_cursors_are_bounded(self):
        with self.assertRaises(ValueError):
            self.graph.graph(limit=1, focus='HGNC:123')
        self.assertEqual(self.graph.graph(offset=10**100)['nodes'], [])

    def test_uppercase_z_prefix_uses_sqlite_nocase_order(self):
        with closing(sqlite3.connect(self.db_path)) as connection, connection:
            connection.execute("INSERT INTO nodes(id,type,label,dataset,record,offset) VALUES('gene:z','Gene','ZFY',3,1,0)")
        for query in ['Z', 'z', 'ZF', 'zf']:
            with self.subTest(query=query):
                self.assertEqual([n['id'] for n in self.graph.search(query)['results']], ['gene:z'])

    def test_oversized_or_nonascii_numeric_ids_return_missing(self):
        for suffix in ['9' * 5000, str(2**63), '²', '0']:
            with self.subTest(suffix=suffix[:30]):
                self.assertIsNone(self.graph.claim('harvest:edge:' + suffix))
                self.assertIsNone(self.graph.dataset('dataset:' + suffix))
        with self.assertRaises(ValueError):
            self.graph.search('bad\ud800query')


if __name__ == '__main__':
    unittest.main()

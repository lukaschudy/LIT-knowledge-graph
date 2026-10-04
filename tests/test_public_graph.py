import gzip
import json
import unittest
from pathlib import Path
from atlas.public_graph import PublicGraphAPI

ROOT=Path(__file__).resolve().parents[1]

class PublicGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harvested=json.loads(gzip.decompress((ROOT/'data/curated/hgnc_dense_snapshot.json.gz').read_bytes()))
        reviewed=json.loads((ROOT/'data/curated/grin_atlas_bundle.json').read_text())
        cls.api=PublicGraphAPI(harvested,reviewed)

    def test_dense_page_retains_reviewed_evidence_and_has_no_dangling_edges(self):
        status,data=self.api.request('/api/harvest/graph',{'limit':['10000']})
        self.assertEqual(status,200)
        self.assertGreaterEqual(len(data['nodes']),10000)
        self.assertIsNone(data['harvest']['next_offset'])
        ids={n['id'] for n in data['nodes']}
        self.assertTrue(all(c['subject'] in ids and c['object'] in ids for c in data['claims']))
        self.assertEqual(data['evidence'],self.api.reviewed['evidence'])

    def test_page_and_focus_are_bounded(self):
        _,first=self.api.request('/api/harvest/graph',{'limit':['120']})
        self.assertEqual(first['harvest']['next_offset'],120)
        focus=self.api.harvested['claims'][0]['subject']
        _,data=self.api.request('/api/harvest/graph',{'focus':[focus],'limit':['120']})
        self.assertIn(focus,{n['id'] for n in data['nodes']})
        self.assertLessEqual(len(data['nodes']),120+len(self.api.reviewed['nodes']))

    def test_public_provenance_and_unknown_record(self):
        node=self.api.harvested['nodes'][0]
        _,data=self.api.request('/api/harvest/node',{'id':[node['id']]})
        self.assertTrue(data['provenance']['source_urls'])
        self.assertTrue(data['provenance']['licenses'])
        self.assertEqual(self.api.request('/api/harvest/record',{'id':['private:missing']})[0],404)
        self.assertEqual(self.api.request('/api/research/state',{})[0],404)

    def test_snapshot_sources_are_public_hgnc_only(self):
        self.assertTrue(all(d['key'].startswith('hgnc/') for d in self.api.datasets.values()))
        self.assertTrue(all(n['type'] in ['Gene','Protein'] for n in self.api.harvested['nodes']))
        self.assertFalse(self.api.harvested['dataset']['synthetic'])

    def test_focus_anchor_survives_small_first_page_and_unknown_focus_is_404(self):
        claim = next(c for c in self.api.harvested['claims']
                     if c['object'] > c['subject'] and c['object'] not in {n['id'] for n in self.api.reviewed['nodes']})
        status, data = self.api.request('/api/harvest/graph', {'focus': [claim['object']], 'limit': ['1']})
        self.assertEqual(status, 200)
        self.assertIn(claim['object'], {node['id'] for node in data['nodes']})
        self.assertEqual(data['harvest']['next_offset'], 1)
        self.assertEqual(self.api.request('/api/harvest/graph', {'focus': ['missing']})[0], 404)

    def test_invalid_and_ambiguous_paging_returns_specific_errors(self):
        for key in ('limit', 'offset'):
            for value in ('', 'NaN', '1.5', '9' * 5000, '²'):
                with self.subTest(key=key, value=value[:30]):
                    status, data = self.api.request('/api/harvest/graph', {key: [value]})
                    self.assertEqual(status, 400)
                    self.assertIn(key, data['error']['message'])
        for path, query in [('/api/harvest/graph', {'limit': ['1', '2']}),
                            ('/api/harvest/node', {'id': ['a', 'b']}),
                            ('/api/harvest/search', {'q': ['a', 'b']})]:
            self.assertEqual(self.api.request(path, query)[0], 400)

    def test_offset_and_limit_edges_remain_bounded(self):
        for limit, offset in [('-1', '-1'), ('9999999999', '9999999999'), ('0', '10000')]:
            status, data = self.api.request('/api/harvest/graph', {'limit': [limit], 'offset': [offset]})
            self.assertEqual(status, 200)
            self.assertGreaterEqual(data['harvest']['limit'], 1)
            self.assertLessEqual(data['harvest']['limit'], 10000)
            self.assertGreaterEqual(data['harvest']['offset'], 0)
            self.assertLessEqual(len(data['nodes']), data['harvest']['limit'] + len(self.api.reviewed['nodes']))
            node_ids = {node['id'] for node in data['nodes']}
            self.assertTrue(all(c['subject'] in node_ids and c['object'] in node_ids for c in data['claims']))

    def test_record_lookup_preserves_first_projection_and_dataset_scope(self):
        node = self.api.harvested['nodes'][0]
        identifier = node['provenance']['id']
        status, data = self.api.request('/api/harvest/record', {'id': [identifier]})
        self.assertEqual(status, 200)
        self.assertEqual(data['node'], next(n for n in self.api.harvested['nodes'] if n['provenance']['id'] == identifier))
        dataset = node['provenance']['dataset']
        status, data = self.api.request('/api/harvest/records', {'dataset': [dataset], 'limit': ['1']})
        self.assertEqual(status, 200)
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['dataset'], dataset)
        self.assertEqual(self.api.request('/api/harvest/records', {'dataset': ['missing']})[0], 404)

    def test_search_is_bounded_and_does_not_match_list_serialization(self):
        status, data = self.api.request('/api/harvest/search', {'q': ['gene']})
        self.assertEqual(status, 200)
        self.assertLessEqual(len(data['results']), 40)
        self.assertGreaterEqual(data['total'], len(data['results']))
        self.assertEqual(self.api.request('/api/harvest/search', {'q': ['x' * 1001]})[0], 400)
        empty = PublicGraphAPI({'nodes': [{'id': 'a', 'label': 'a', 'aliases': []}],
                                'claims': [], 'public_datasets': []}, {'nodes': [], 'claims': []})
        self.assertEqual(empty.request('/api/harvest/search', {'q': ['[]']})[1]['total'], 0)

    def test_grin_search_resolves_to_one_gene_with_both_relationship_sets(self):
        for symbol, hgnc, expected in [('GRIN2B', 'HGNC:4586', 8), ('GRIN2A', 'HGNC:4585', 4)]:
            canonical = 'gene:' + symbol
            for query in (symbol, hgnc):
                _, search = self.api.request('/api/harvest/search', {'q': [query]})
                genes = [n for n in search['results'] if n.get('type') == 'Gene' and n['label'] == symbol]
                self.assertEqual([n['id'] for n in genes], [canonical])
                self.assertIn(hgnc, genes[0]['aliases'])
            _, graph = self.api.request('/api/harvest/graph', {'focus': [hgnc], 'limit': ['10000']})
            self.assertEqual(graph['harvest']['focus'], canonical)
            self.assertNotIn(hgnc, {n['id'] for n in graph['nodes']})
            linked = [c for c in graph['claims'] if canonical in (c['subject'], c['object'])]
            self.assertEqual(len(linked), expected)
            self.assertTrue(any(c['predicate'] == 'AFFECTS' for c in linked))
            self.assertTrue(any(c['predicate'] == 'MERGED_INTO' for c in linked))
            self.assertEqual(len(self.api.neighbors[canonical]), expected)

    def test_legacy_id_lookup_retains_source_pointer_and_original_claim_endpoints(self):
        _, legacy = self.api.request('/api/harvest/node', {'id': ['HGNC:4586']})
        _, canonical = self.api.request('/api/harvest/node', {'id': ['gene:GRIN2B']})
        self.assertEqual(legacy, canonical)
        self.assertEqual(legacy['node']['properties']['hgnc_id'], 'HGNC:4586')
        self.assertTrue(legacy['provenance']['source_urls'])
        claim = next(c for c in self.api.harvested['claims'] if c['object'] == 'HGNC:4586')
        _, data = self.api.request('/api/harvest/claim', {'id': [claim['id']]})
        self.assertEqual(data['claim']['object'], 'gene:GRIN2B')
        self.assertEqual(data['claim']['identity_resolution']['original_object'], 'HGNC:4586')
        self.assertEqual(data['claim']['provenance'], claim['provenance'])
        _, record = self.api.request('/api/harvest/record', {'id': [legacy['node']['provenance']['id']]})
        original = next(n for n in self.api.harvested['nodes']
                        if n.get('provenance', {}).get('id') == legacy['node']['provenance']['id'])
        self.assertEqual(record['node'], original)

    def test_gene_merge_preserves_all_claim_ids_evidence_and_input_snapshots(self):
        from copy import deepcopy
        harvested, reviewed = deepcopy(self.api.harvested), deepcopy(self.api.reviewed)
        api = PublicGraphAPI(harvested, reviewed)
        _, graph = api.request('/api/harvest/graph', {'limit': ['10000']})
        self.assertEqual(len(graph['nodes']), len(harvested['nodes']) + len(reviewed['nodes']) - 2)
        self.assertEqual({c['id'] for c in graph['claims']}, {c['id'] for c in harvested['claims'] + reviewed['claims']})
        self.assertEqual(graph['evidence'], reviewed['evidence'])
        self.assertEqual(harvested, self.api.harvested)
        self.assertEqual(reviewed, self.api.reviewed)

    def test_names_types_and_ambiguous_hgnc_annotations_do_not_merge(self):
        harvested = {'nodes': [{'id': 'HGNC:1', 'label': 'SAME', 'type': 'Gene'},
                               {'id': 'HGNC:2', 'label': 'SAME', 'type': 'Protein'},
                               {'id': 'HGNC:3', 'label': 'SAME', 'type': 'Gene'}],
                     'claims': [], 'public_datasets': []}
        reviewed = {'nodes': [{'id': 'gene:a', 'label': 'SAME', 'type': 'Gene'},
                              {'id': 'gene:b', 'label': 'SAME', 'type': 'Gene', 'properties': {'hgnc_id': 'HGNC:2'}},
                              {'id': 'gene:c', 'label': 'SAME', 'type': 'Gene', 'properties': {'hgnc_id': 'HGNC:3'}},
                              {'id': 'gene:d', 'label': 'SAME', 'type': 'Gene', 'properties': {'hgnc_id': 'HGNC:3'}}], 'claims': []}
        api = PublicGraphAPI(harvested, reviewed)
        self.assertEqual(api.alias_map, {})
        self.assertEqual(len(api.nodes), 7)

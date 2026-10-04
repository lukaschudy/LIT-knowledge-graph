"""Shared handler boundaries and evidence scope, independent of HTTP hosting."""
import json
from pathlib import Path
import unittest

from atlas.cloud_bundle import reviewed_graph
from atlas.http_api import AtlasAPI

ROOT = Path(__file__).resolve().parents[1]


class APIBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        graph = json.loads((ROOT / 'data/curated/grin_atlas_bundle.json').read_text())
        cluster = json.loads((ROOT / 'data/curated/grin_cluster_demo_v2.json').read_text())
        cls.api = AtlasAPI(reviewed_graph(graph, cluster), {}, cluster)
        cls.variant = cluster['members'][0]['id']

    def test_repeated_and_empty_context_cannot_be_silently_ignored(self):
        for query in [{'q': ['What evidence?'], 'node': ['', self.variant]},
                      {'q': ['What evidence?'], 'node': [self.variant, 'missing']},
                      {'q': ['What evidence?'], 'node': ['']},
                      {'q': ['What evidence?'], 'node': ['   ']}]:
            with self.subTest(query=query):
                status, data = self.api.request('/api/ask', query)
                self.assertEqual(status, 400)
                self.assertNotIn('answer', data)

    def test_claim_followup_retains_linked_claim_scope_with_selected_variant(self):
        claim = next(iter(self.api.claims))
        status, data = self.api.request('/api/ask', {'q': ['What evidence supports this?'],
                                                   'node': [self.variant], 'claim': [claim]})
        self.assertEqual(status, 200)
        self.assertEqual(data['claim_ids'], [claim])
        self.assertIn('linked assertions', data['answer'])
        self.assertNotIn('observation_ids', data)

    def test_explicit_variant_still_takes_precedence_over_claim_followup(self):
        claim = next(iter(self.api.claims))
        status, data = self.api.request('/api/ask', {'q': ['What evidence for GRIN2B S541R?'],
                                                   'node': [self.variant], 'claim': [claim]})
        self.assertEqual(status, 200)
        self.assertEqual(data['mode'], 'source_annotation_lookup')
        self.assertTrue(data['observation_ids'])
        status, data = self.api.request('/api/ask', {'q': ['What evidence for GRIN2B R999Q?'],
                                                   'node': [self.variant], 'claim': [claim]})
        self.assertEqual(status, 200)
        self.assertIn('coverage gap', data['answer'])
        self.assertEqual(data['claim_ids'], [])

    def test_claim_context_is_validated_even_when_node_is_outside_graph(self):
        status, data = self.api.request('/api/ask', {'q': ['What evidence?'],
                                                   'node': ['missing'], 'claim': ['missing']})
        self.assertEqual(status, 400)
        self.assertEqual(data['error']['code'], 'invalid_claim_context')

    def test_query_shape_and_utf8_fail_without_uncaught_exceptions(self):
        for query in [None, [], {'q': []}, {'q': 'text'}, {'q': [42]},
                      {'q': ['\ud800']}, {None: ['value']}]:
            with self.subTest(query=repr(query)):
                self.assertEqual(self.api.request('/api/search', query)[0], 400)
        self.assertEqual(self.api.request('/api/ask', {'q': ['x'], 'claim': ['x'] * 151})[0], 400)

    def test_query_size_is_bounded_for_direct_api_users(self):
        for path in ['/api/ask', '/api/search']:
            with self.subTest(path=path):
                self.assertEqual(self.api.request(path, {'q': ['x' * 1001]})[0], 400)
                self.assertEqual(self.api.request(path, {'q': ['🧬' * 5000]})[0], 414)

    def test_ordinary_variant_annotation_lookup_is_preserved(self):
        status, data = self.api.request('/api/ask', {'q': ['What are the measurements?'], 'node': [self.variant]})
        self.assertEqual(status, 200)
        self.assertEqual(data['mode'], 'source_annotation_lookup')
        self.assertEqual(data['node_ids'], [self.variant])
        self.assertTrue(data['observation_ids'])


if __name__ == '__main__':
    unittest.main()

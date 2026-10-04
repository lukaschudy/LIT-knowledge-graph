"""Production must serve the reviewed GRIN data and cite the actual records."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from atlas.cloud_bundle import reviewed_graph
from atlas.cluster_questions import answer_cluster_question
from atlas.http_api import AtlasAPI
from atlas.model import validate_bundle

ROOT = Path(__file__).resolve().parents[1]


class CloudClusterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((ROOT / 'data/curated/grin_atlas_bundle.json').read_text())
        cls.cluster = json.loads((ROOT / 'data/curated/grin_cluster_demo_v2.json').read_text())
        cls.graph = reviewed_graph(cls.original, cls.cluster)
        cls.api = AtlasAPI(cls.graph, {}, cls.cluster)

    def test_real_graph_validates_and_retains_original_unchanged(self):
        self.assertEqual(validate_bundle(self.graph), [])
        self.assertFalse(self.graph['dataset']['synthetic'])
        self.assertEqual(self.graph['dataset']['annotation_counts']['observations'], 340)
        self.assertIn('functional_evidence', next(n for n in self.original['nodes'] if n['type'] == 'Variant')['properties'])
        self.assertTrue(all('functional_evidence' not in n['properties'] for n in self.graph['nodes'] if n['type'] == 'Variant'))

    def test_provisional_effect_is_not_promoted_to_established_loss(self):
        node = next(n for n in self.graph['nodes'] if n['label'] == 'GRIN2B p.Cys461Phe')
        claim = next(c for c in self.graph['claims'] if c['subject'] == node['id'] and c['predicate'] == 'HAS_EFFECT')
        self.assertEqual(claim['context']['effect'], 'unknown')
        self.assertIn('Possible LoF', claim['context']['source_classification'])

    def test_synthetic_data_cannot_replace_production(self):
        bad = deepcopy(self.original); bad['dataset']['synthetic'] = True
        with self.assertRaises(ValueError): reviewed_graph(bad, self.cluster)

    def test_comparison_uses_reviewed_measurements_categories_and_citations(self):
        status, answer = self.api.request('/api/ask', {'q': ['Why is GRIN2B p.Ser541Arg core while p.Cys461Phe is provisional? Compare WT measurements, predictions and conflicting evidence.']})
        self.assertEqual(status, 200)
        self.assertFalse(answer['synthetic'])
        self.assertEqual(answer['mode'], 'source_annotation_lookup')
        for text in ['Possible LoF', 'Likely LoF', '9.1 (7.2, 11)', '169 ± 9.0', 'Author-calculated predictions', 'glycine potency', 'expert review pending']:
            self.assertIn(text, answer['answer'])
        self.assertTrue(set(answer['observation_ids']) <= {o['id'] for o in self.cluster['observations']})
        self.assertTrue({s['document_id'] for s in answer['citations']} <= {s['document_id'] for s in self.cluster['sources']})
        self.assertEqual(len(answer['evidence_links']), 2)

    def test_short_alias_and_selected_variant_context(self):
        answer = answer_cluster_question(self.cluster, 'Explain S541R')
        self.assertEqual(len(answer['node_ids']), 1)
        followup = answer_cluster_question(self.cluster, 'What are the measurements?', answer['node_ids'][0])
        self.assertEqual(followup['node_ids'], answer['node_ids'])

    def test_clinical_request_retains_existing_boundary(self):
        status, answer = self.api.request('/api/ask', {'q': ['What treatment should I use for GRIN2B S541R?']})
        self.assertEqual(status, 200)
        self.assertIn('cannot determine a diagnosis or recommend treatment', answer['answer'])

    def test_cluster_and_health_agree_on_the_reference(self):
        _, health = self.api.request('/api/health', {})
        status, cluster = self.api.request('/api/cluster', {})
        self.assertEqual(status, 200)
        self.assertEqual(health['dataset']['annotation_reference_sha256'], cluster['reference_sha256'])
        self.assertEqual(cluster['counts']['claims'], 53)


if __name__ == '__main__': unittest.main()

import json
from pathlib import Path
import unittest

from atlas.demo import expand_demo
from atlas.model import validate_bundle
from atlas.reasoning import AtlasReasoner


class VisualDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
        cls.bundle = expand_demo(cls.base)

    def test_valid_reproducible_records_with_evidence(self):
        self.assertEqual(validate_bundle(self.bundle), [])
        self.assertEqual(self.bundle, expand_demo(self.base))
        self.assertEqual(len(self.bundle['nodes']), 2355)
        sizes = {}
        for node in self.bundle['nodes']:
            community = node.get('properties', {}).get('demo_community')
            if community is not None:
                sizes[community] = sizes.get(community, 0) + 1
        self.assertGreater(len(set(sizes.values())), 8)
        self.assertEqual(len(self.base['nodes']), 23)
        cited = {e['claim_id'] for e in self.bundle['evidence']}
        self.assertTrue(all(c['id'] in cited for c in self.bundle['claims'] if c['id'].startswith('demo:constellation-')))

    def test_original_reasoning_outcomes_are_preserved(self):
        for disease in ['demo:disease-a', 'demo:disease-d']:
            self.assertEqual(AtlasReasoner(self.bundle).explore(disease)['status'],
                             AtlasReasoner(self.base).explore(disease)['status'])

    def test_never_expands_real_data(self):
        with self.assertRaises(ValueError):
            expand_demo({'dataset': {'id': 'real', 'synthetic': False}})

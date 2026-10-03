import json
from pathlib import Path
import unittest
from atlas.model import validate_bundle
from atlas.reasoning import AtlasReasoner

class DemoAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle=json.loads((Path(__file__).parents[1]/'data/fixtures/atlas-demo.json').read_text())
    def test_fixture_is_explicit_and_valid(self):
        self.assertEqual(validate_bundle(self.bundle),[])
        self.assertTrue(self.bundle['dataset']['synthetic'])
        self.assertTrue(all(s['synthetic'] and s['kind']=='fixture' for s in self.bundle['sources']))
    def test_maria_journey(self):
        result=AtlasReasoner(self.bundle).explore('demo:disease-a')
        self.assertEqual(result['status'],'leads_found')
        self.assertTrue(any(o['asset']['id']=='demo:asset-registry' for o in result['opportunities']))
        statuses={c['disease']['id']:c['status'] for c in result['candidates']}
        self.assertEqual(statuses['demo:disease-b'],'supported_lead')
        self.assertEqual(statuses['demo:disease-c'],'rejected')
        self.assertNotEqual(statuses['demo:disease-e'],'supported_lead')
        self.assertNotEqual(statuses['demo:disease-f'],'supported_lead')
    def test_honest_gap(self):
        result=AtlasReasoner(self.bundle).explore('demo:disease-d')
        self.assertEqual(result['status'],'no_supported_route')
        self.assertTrue(result['coverage'])
        self.assertTrue(result['gaps'])
        self.assertTrue(result['next_questions'])

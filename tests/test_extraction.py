import json
from pathlib import Path
import unittest
from atlas.extraction import ground_proposals

class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.bundle=json.loads((Path(__file__).parents[1]/'data/fixtures/atlas-demo.json').read_text())
        self.text='Fictional Aurora involves transport.'
        self.proposal=dict(subject='demo:disease-a',predicate='INVOLVES',object='demo:mechanism-transport',assertion_type='reported',context={'effect':'loss_of_function'},start=0,end=len(self.text),excerpt=self.text)
    def extract(self,p):
        return ground_proposals(self.bundle,source_id='demo:source-mechanisms',source_text=self.text,proposals=[p])
    def test_exact_quote_and_source_hash_preserved(self):
        b=self.extract(self.proposal)
        self.assertEqual(b['evidence'][-1]['excerpt'],self.text)
        self.assertIn('sha256:',b['evidence'][-1]['locator'])
        self.assertEqual(len(b['claims']),len(self.bundle['claims'])+1)
    def test_fabricated_quote_rejected_without_mutating_input(self):
        before=json.dumps(self.bundle,sort_keys=True)
        with self.assertRaises(ValueError): self.extract(self.proposal|{'excerpt':'Invented evidence'})
        self.assertEqual(json.dumps(self.bundle,sort_keys=True),before)
    def test_unknown_identity_rejected(self):
        with self.assertRaises(ValueError): self.extract(self.proposal|{'subject':'madeup:123'})
    def test_repeated_extraction_idempotent(self):
        b=self.extract(self.proposal)
        b2=ground_proposals(b,source_id='demo:source-mechanisms',source_text=self.text,proposals=[self.proposal])
        self.assertEqual(len(b['claims']),len(b2['claims']))

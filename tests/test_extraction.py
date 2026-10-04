import json
from hashlib import sha256
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
        self.assertEqual(b['evidence'][-1]['source_version'], sha256(self.text.encode()).hexdigest())
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

    def test_registered_source_hash_mismatch_rejected_without_mutation(self):
        source = next(s for s in self.bundle['sources'] if s['id'] == 'demo:source-mechanisms')
        for prefix in ('', 'sha256:'):
            with self.subTest(prefix=prefix):
                source['version'] = prefix + sha256(b'different source bytes').hexdigest()
                before = json.dumps(self.bundle, sort_keys=True)
                with self.assertRaisesRegex(ValueError, 'registered snapshot'):
                    self.extract(self.proposal)
                self.assertEqual(json.dumps(self.bundle, sort_keys=True), before)

    def test_matching_source_hash_keeps_exact_version_identifier(self):
        source = next(s for s in self.bundle['sources'] if s['id'] == 'demo:source-mechanisms')
        for prefix in ('', 'sha256:'):
            with self.subTest(prefix=prefix):
                source['version'] = prefix + sha256(self.text.encode()).hexdigest()
                result = self.extract(self.proposal)
                self.assertEqual(result['evidence'][-1]['source_version'], source['version'])
                self.assertEqual(result['evidence'][-1]['review_status'], 'unreviewed')

    def test_extracted_claim_context_is_isolated_from_caller_mutation(self):
        self.proposal['context']['details'] = {'conditions': ['initial']}
        result = self.extract(self.proposal)
        self.proposal['context']['effect'] = 'gain_of_function'
        self.proposal['context']['details']['conditions'].append('changed')
        self.assertEqual(result['claims'][-1]['context']['effect'], 'loss_of_function')
        self.assertEqual(result['claims'][-1]['context']['details']['conditions'], ['initial'])

    def test_repeated_extraction_rejects_altered_claim_or_provenance_under_same_id(self):
        for changed in ('negation', 'excerpt', 'version', 'locator'):
            with self.subTest(changed=changed):
                bundle = self.extract(self.proposal)
                if changed == 'negation':
                    bundle['claims'][-1]['context']['negated'] = True
                else:
                    field = 'source_version' if changed == 'version' else changed
                    bundle['evidence'][-1][field] = 'altered value'
                before = json.dumps(bundle, sort_keys=True)
                with self.assertRaisesRegex(ValueError, 'collides'):
                    ground_proposals(bundle, source_id='demo:source-mechanisms', source_text=self.text, proposals=[self.proposal])
                self.assertEqual(json.dumps(bundle, sort_keys=True), before)

    def test_reviewed_extraction_remains_idempotent_without_resetting_review(self):
        bundle = self.extract(self.proposal)
        bundle['evidence'][-1]['review_status'] = 'human_reviewed'
        repeated = ground_proposals(bundle, source_id='demo:source-mechanisms', source_text=self.text,
                                    proposals=[self.proposal, self.proposal])
        self.assertEqual(repeated, bundle)

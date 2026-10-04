"""Questions must preserve the graph's evidence and uncertainty boundaries."""
import json
from pathlib import Path
import unittest
from atlas.questions import answer_question
from atlas.reasoning import AtlasReasoner

class GraphQuestionTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((Path(__file__).resolve().parents[1] / 'data/fixtures/atlas-demo.json').read_text())
        self.reasoner = AtlasReasoner(self.bundle)

    def answer(self, question, context=None):
        result = answer_question(self.bundle, self.reasoner, question, context)
        self.assertEqual(result['mode'], 'graph_lookup')
        self.assertTrue(result['synthetic'])
        self.assertTrue(set(result['claim_ids']) <= {c['id'] for c in self.bundle['claims']})
        return result

    def test_supported_comparison_cites_mechanism_paths(self):
        result = self.answer('Why are Aurora and Boreal connected?')
        self.assertIn('supported research lead', result['answer'])
        self.assertIn('demo:claim-a-effect', result['claim_ids'])
        self.assertIn('demo:claim-b-effect', result['claim_ids'])

    def test_opposite_effect_is_not_promoted_by_a_shared_mechanism(self):
        result = self.answer('How are Aurora and Cinder connected?')
        self.assertIn('unsupported route', result['answer'])
        self.assertIn('opposite directions', result['answer'])

    def test_contextual_evidence_includes_counterevidence(self):
        result = self.answer('What evidence is recorded?', 'demo:disease-f')
        self.assertIn('1 counter-evidence', result['answer'])
        self.assertIn('demo:claim-f-effect', result['claim_ids'])

    def test_missing_route_does_not_invent_an_asset(self):
        result = self.answer('What research assets can be reused?', 'demo:disease-d')
        self.assertIn('No fully evidenced', result['answer'])
        self.assertEqual(result['claim_ids'], [])

    def test_clinical_request_is_not_treated_as_a_supported_research_pair(self):
        result = self.answer('Can I use a Boreal treatment for Aurora?')
        self.assertIn('cannot determine a diagnosis or recommend treatment', result['answer'])
        self.assertEqual(result['claim_ids'], [])

    def test_unanswerable_question_admits_lookup_scope(self):
        result = self.answer('What will the weather be tomorrow?')
        self.assertIn('not a general-purpose AI', result['answer'])
        self.assertEqual(result['claim_ids'], [])

    def test_selected_disease_and_named_comparison_resolve_together(self):
        result = self.answer('Is this connected to Cinder?', 'demo:disease-a')
        self.assertIn('unsupported route', result['answer'])
        self.assertEqual(set(result['node_ids']), {'demo:disease-a', 'demo:disease-c'})

    def test_evidence_followup_preserves_prior_claim_scope(self):
        first = self.answer('Why are Aurora and Fjord connected?')
        followup = answer_question(self.bundle, self.reasoner, 'What evidence supports this?', claim_context=first['claim_ids'])
        self.assertIn('1 counter-evidence', followup['answer'])
        self.assertEqual(followup['claim_ids'], first['claim_ids'])

    def test_named_entity_takes_precedence_over_previous_answer(self):
        first = self.answer('Why are Aurora and Fjord connected?')
        followup = answer_question(self.bundle, self.reasoner, 'What evidence is recorded for Boreal?', claim_context=first['claim_ids'])
        self.assertIn('demo:claim-b-effect', followup['claim_ids'])
        self.assertNotIn('demo:claim-f-effect', followup['claim_ids'])

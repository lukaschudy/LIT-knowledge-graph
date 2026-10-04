"""Demo answering cannot inherit the broader graph or catalog's scope."""
import json
from pathlib import Path
import unittest
from atlas.assistant import AtlasAssistant
from atlas.catalog import combined_bundle
from atlas.demo_scope import DemoScope, DemoRetriever
from tests.test_assistant import FakeClient, FakeRetriever

ROOT = Path(__file__).resolve().parents[1]

class DemoScopeTests(unittest.TestCase):
    def setUp(self):
        self.bundle = combined_bundle(ROOT)
        self.scope = DemoScope(json.loads((ROOT / 'data/curated/grin_atlas_bundle.json').read_text()))
        self.client = FakeClient({'paragraphs': [{'text': '', 'insufficient': True, 'citations': [], 'claim_ids': [], 'node_ids': []}], 'suggestions': []})
        self.client.data['paragraphs'][0]['text'] = 'Insufficient evidence.'
        self.retriever = FakeRetriever([
            {'id': 'outside', 'source_id': 'outside', 'scope': 'neuro', 'text': 'NEURO_SENTINEL'},
            {'id': 'inside', 'source_id': 'inside', 'scope': 'grin', 'text': 'GRIN2B evidence.'}])
        self.assistant = AtlasAssistant(self.client, self.retriever, scope=self.scope)

    def test_off_topic_question_does_not_call_model_or_retrieval(self):
        for question in ('Tell me about EPG5', 'BRCA1 variants', 'Assets for Parkinson disease'):
            answer = self.assistant.answer(self.bundle, question)
            self.assertEqual(answer['mode'], 'demo_scope_boundary')
            self.assertIsNone(self.retriever.query)
            self.assertIsNone(self.client.prompt)

    def test_browsing_an_outside_entity_cannot_switch_chat_scope(self):
        outside = next(n['id'] for n in self.bundle['nodes'] if n['id'] not in self.scope.node_ids)
        answer = self.assistant.answer(self.bundle, 'What evidence is available?', outside)
        self.assertEqual(answer['mode'], 'demo_scope_boundary')
        self.assertIsNone(self.client.prompt)
        answer = self.assistant.answer(self.bundle, 'What evidence supports GRIN2B?', outside)
        self.assertEqual(answer['answer_scope']['id'], 'grin-reduced-function-v1')
        prompt = json.loads(self.client.prompt.split('\n\n', 1)[1])
        self.assertIsNone(prompt['selected_node'])
        self.assertNotIn('NEURO_SENTINEL', self.client.prompt)
        self.assertTrue(all(c['id'] in self.scope.claim_ids for c in prompt['graph_claims']))
        self.assertEqual(prompt['fixed_demo_scope']['id'], 'grin-reduced-function-v1')

    def test_cross_cluster_claim_followup_is_rejected(self):
        outside = next(c['id'] for c in self.bundle['claims'] if c['id'] not in self.scope.claim_ids)
        answer = self.assistant.answer(self.bundle, 'What evidence supports GRIN2B?', claim_ids=[outside])
        self.assertEqual(answer['mode'], 'demo_scope_boundary')
        self.assertIsNone(self.client.prompt)

    def test_chat_adapter_sets_fixed_scope_without_replacing_global_catalog(self):
        class Catalog:
            def search(self, query, top_k=8, *, scope=None):
                return {'scope': scope, 'query': query}
        catalog = Catalog()
        self.assertEqual(DemoRetriever(catalog).search('evidence')['scope'], 'grin')
        self.assertIsNone(catalog.search('evidence')['scope'])

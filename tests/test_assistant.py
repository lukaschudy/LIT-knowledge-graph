"""The live assistant may summarize supplied evidence, but IDs stay source-bound."""
import json
from copy import deepcopy
from pathlib import Path
import unittest

from atlas.ai import ModelError
from atlas.assistant import AtlasAssistant
from atlas.recommendations import RecommendationEngine


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.query = None
        self.top_k = None

    def search(self, query, top_k=5):
        self.query, self.top_k = query, top_k
        return {"hits": self.hits, "provider": "local", "scopes": ["demo"]}


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.prompt = None
        self.schema = None
        self.schema_name = None

    def generate_json(self, prompt, schema, schema_name):
        self.prompt, self.schema, self.schema_name = prompt, schema, schema_name
        return {"data": self.data, "metadata": {"provider": "mock", "model": "test-model", "mode": "test"}}


def fixture():
    return json.loads((Path(__file__).resolve().parents[1] / "data/fixtures/atlas-demo.json").read_text())


class AtlasAssistantTests(unittest.TestCase):
    def setUp(self):
        self.bundle = fixture()
        self.retriever = FakeRetriever([{"id": "passage-1", "source_id": "demo:source-paper",
            "title": "Paper", "url": "https://example.org/paper", "locator": "p. 3",
            "text": "Aurora has a reported mechanism in the supplied study.", "kind": "article_text",
            "review_status": "unreviewed", "claim_ids": [], "node_ids": []}])
        self.response = {"paragraphs": [{"text": "The supplied passage reports a mechanism.", "insufficient": False, "citations": [1],
                         "claim_ids": [], "node_ids": []}], "suggestions": ["What evidence supports this?"]}
        self.client = FakeClient(self.response)
        self.assistant = AtlasAssistant(self.client, self.retriever)

    def test_returns_numbered_citation_and_full_source_record(self):
        result = self.assistant.answer(self.bundle, "What does the paper report?")
        self.assertEqual(result["mode"], "live")
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["answer"], "The supplied passage reports a mechanism. [1]")
        self.assertEqual(result["sources"][0]["citation_id"], "[1]")
        self.assertEqual(result["sources"][0]["excerpt"], self.retriever.hits[0]["text"])
        self.assertEqual(result["sources"][0]["url"], "https://example.org/paper")
        self.assertEqual(result["sources"][0]["classification"], "unreviewed_discovery")
        self.assertEqual(result["metadata"]["retrieval"]["scopes"], ["demo"])
        self.assertEqual(self.retriever.top_k, 8)
        self.assertIn("does not establish a reviewed graph claim", self.client.prompt)
        self.assertEqual(self.client.schema_name, "atlas_answer")
        self.assertEqual(self.client.schema["properties"]["paragraphs"]["items"]["properties"]["citations"]["items"]["enum"], [1])

    def test_passage_number_is_enforced_locally(self):
        self.client.data["paragraphs"][0]["citations"] = [2]
        with self.assertRaises(ModelError) as ctx:
            self.assistant.answer(self.bundle, "What does the paper report?")
        self.assertEqual(ctx.exception.code, "invalid_response")

    def test_unknown_graph_claim_is_rejected(self):
        self.client.data["paragraphs"][0]["claim_ids"] = ["invented-claim"]
        with self.assertRaises(ModelError) as ctx:
            self.assistant.answer(self.bundle, "What does the paper report?")
        self.assertIn("graph claim", str(ctx.exception))

    def test_inferred_claim_without_a_valid_source_is_not_offered_or_allowed(self):
        unsupported = "demo:claim-d-hypothesis"
        claim = next(c for c in self.bundle["claims"] if c["id"] == unsupported)
        self.client.data["paragraphs"][0]["claim_ids"] = [unsupported]
        analysis = {"request": {}, "recommendations": [{"asset_id": "asset-x", "asset_label": "Example",
            "decision_claim_ids": [unsupported], "status": "needs_clarification", "next_action": "Review",
            "gates": [{"code": "anchor", "state": "unknown", "reason": "No source", "claim_ids": [unsupported]}]}]}
        with self.assertRaises(ModelError) as ctx:
            self.assistant.answer(self.bundle, "Question", node_id=claim["subject"],
                                  claim_ids=[], analysis=analysis)
        self.assertIn("graph claim", str(ctx.exception))
        self.assertNotIn(unsupported, self.client.prompt)
        claim_items = self.client.schema["properties"]["paragraphs"]["items"]["properties"]["claim_ids"]
        self.assertNotIn(unsupported, claim_items["items"].get("enum", []))
        self.assertNotIn(unsupported, self.client.prompt)

    def test_unavailable_model_is_not_replaced_with_a_local_answer(self):
        class Unavailable:
            def generate_json(self, *_):
                raise ModelError("not_configured", "No live provider is configured.")
        assistant = AtlasAssistant(Unavailable(), self.retriever)
        with self.assertRaises(ModelError) as ctx:
            assistant.answer(self.bundle, "Question")
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_selected_node_and_analysis_are_context_not_promotion(self):
        node = self.bundle["nodes"][0]["id"]
        analysis = {"recommendations": [{"status": "needs_review", "action": "inspect", "debug": "omit"}], "summary": "A review is required."}
        self.assistant.answer(self.bundle, "What next?", node_id=node, analysis=analysis)
        self.assertIn(node, self.client.prompt)
        self.assertIsNone(json.loads(self.client.prompt.split('\n\n', 1)[1])['deterministic_assessment'])
        self.assertNotIn("debug", self.client.prompt)

    def test_node_alias_expansion_keeps_retrieval_query_within_catalog_limit(self):
        bundle = json.loads(json.dumps(self.bundle))
        node = bundle["nodes"][0]
        node["aliases"] = ["Alias" + str(i) for i in range(500)]
        self.assistant.answer(bundle, "Q" * 2000, node_id=node["id"])
        self.assertLessEqual(len(self.retriever.query), 2000)
        self.assertIn(node["label"], self.retriever.query)

    def test_passage_is_bounded_and_sources_only_include_used_citations(self):
        self.retriever.hits = [dict(self.retriever.hits[0], text="X" * 100_000),
                               dict(self.retriever.hits[0], id="passage-2", text="Y" * 100)]
        self.client.data["paragraphs"][0]["citations"] = [1]
        result = self.assistant.answer(self.bundle, "Question")
        self.assertLessEqual(len(self.client.prompt), 32_000)
        self.assertEqual(len(result["sources"][0]["excerpt"]), 4000)
        self.assertEqual(len(result["sources"][0]["text"]), 100_000)
        self.assertTrue(result["sources"][0]["truncated"])
        self.assertEqual(len(result["sources"]), 1)

    def test_bad_input_node_fails_before_model_call(self):
        with self.assertRaises(ValueError):
            self.assistant.answer(self.bundle, "Question", node_id="missing")
        self.assertIsNone(self.client.prompt)

    def test_no_evidence_returns_explicit_deterministic_insufficiency(self):
        bundle = dict(self.bundle, claims=[], evidence=[])
        self.retriever.hits = []
        result = self.assistant.answer(bundle, "What does this establish?")
        self.assertEqual(result["mode"], "deterministic_insufficient")
        self.assertIn("do not establish", result["answer"])
        self.assertIsNone(self.client.prompt)

    def test_blank_passages_cannot_be_cited_as_evidence(self):
        bundle = dict(self.bundle, claims=[], evidence=[])
        self.retriever.hits[0]['text'] = '   \n '
        result = self.assistant.answer(bundle, 'What does this establish?')
        self.assertEqual(result['mode'], 'deterministic_insufficient')
        self.assertIsNone(self.client.prompt)

    def test_graph_context_exposes_stale_or_retracted_review_status(self):
        evidence = self.bundle['evidence'][0]
        source = next(s for s in self.bundle['sources'] if s['id'] == evidence['source_id'])
        evidence['review_status'] = 'human_reviewed'
        evidence['source_version'] = 'prior-v1'
        source['version'] = 'current-v2'
        source['status'] = 'retracted'
        self.assistant.answer(self.bundle, 'What does the graph establish?', claim_ids=[evidence['claim_id']])
        prompt_data = json.loads(self.client.prompt.split('\n\n', 1)[1])
        claim = next(c for c in prompt_data['graph_claims'] if c['id'] == evidence['claim_id'])
        row = next(e for e in claim['evidence'] if e['source_id'] == source['id'])
        self.assertEqual(row['classification'], 'graph_assertion_needs_review')
        self.assertEqual(row['source_status'], 'retracted')
        self.assertEqual(row['source_version'], 'current-v2')
        self.assertEqual(row['evidence_source_version'], 'prior-v1')

    def test_bounded_graph_context_keeps_counterevidence_after_multiple_supporters(self):
        evidence = self.bundle['evidence'][0]
        self.bundle['evidence'].extend([
            dict(evidence, id='second-support'),
            dict(evidence, id='opposing-source', stance='contradicts', excerpt='The reported mechanism was not reproduced.')])
        self.assistant.answer(self.bundle, 'What evidence conflicts?', claim_ids=[evidence['claim_id']])
        prompt_data = json.loads(self.client.prompt.split('\n\n', 1)[1])
        claim = next(c for c in prompt_data['graph_claims'] if c['id'] == evidence['claim_id'])
        self.assertEqual({e['stance'] for e in claim['evidence']}, {'supports', 'contradicts'})
        self.assertEqual(claim['evidence_counts'], {'supports': 2, 'contradicts': 1})
        self.assertTrue(claim['evidence_truncated'])

    def test_uncited_factual_paragraph_is_rejected(self):
        self.client.data["paragraphs"][0].update({"citations": [], "insufficient": False})
        with self.assertRaises(ModelError) as ctx:
            self.assistant.answer(self.bundle, "What does the paper report?")
        self.assertIn("needs a passage citation", str(ctx.exception))

    def test_structured_insufficiency_is_rendered_deterministically(self):
        self.client.data["paragraphs"] = [{"text": "whatever", "insufficient": True,
                                           "citations": [], "claim_ids": [], "node_ids": []}]
        result = self.assistant.answer(self.bundle, "Question")
        self.assertEqual(result["answer"], "The supplied graph claims and retrieved passages do not establish this point.")

    def test_machine_checked_curated_evidence_needs_review(self):
        evidence = self.bundle["evidence"][0]
        claim = next(c for c in self.bundle["claims"] if c["id"] == evidence["claim_id"])
        source = next(s for s in self.bundle["sources"] if s["id"] == evidence["source_id"])
        evidence["review_status"] = "machine_checked"
        self.retriever.hits = [{"id": "curated-1", "source_id": evidence["source_id"],
            "title": source["title"], "url": source["url"], "locator": evidence["locator"],
            "text": "Context. " + evidence["excerpt"], "kind": "curated_evidence",
            "review_status": "machine_checked", "claim_id": claim["id"], "evidence_id": evidence["id"],
            "claim_ids": [claim["id"]], "node_ids": [claim["subject"], claim["object"]]}]
        self.client.data["paragraphs"][0]["citations"] = [1]
        result = self.assistant.answer(self.bundle, "Question")
        self.assertEqual(result["sources"][0]["classification"], "graph_assertion_needs_review")

    def test_human_review_requires_current_source_version_and_exact_graph_link(self):
        evidence = self.bundle["evidence"][0]
        claim = next(c for c in self.bundle["claims"] if c["id"] == evidence["claim_id"])
        source = next(s for s in self.bundle["sources"] if s["id"] == evidence["source_id"])
        source["version"] = "current-v1"
        evidence.update({"review_status": "human_reviewed", "source_version": "current-v1"})
        self.retriever.hits = [{"id": "curated-1", "source_id": source["id"], "title": source["title"],
            "url": source["url"], "locator": evidence["locator"], "text": evidence["excerpt"],
            "kind": "curated_evidence", "claim_id": claim["id"], "evidence_id": evidence["id"], "source_version": "current-v1"}]
        self.client.data["paragraphs"][0]["citations"] = [1]
        result = self.assistant.answer(self.bundle, "Question")
        self.assertEqual(result["sources"][0]["classification"], "reviewed_graph_evidence")
        self.retriever.hits[0]["kind"] = "article_text"
        result = self.assistant.answer(self.bundle, "Question")
        self.assertEqual(result["sources"][0]["classification"], "unreviewed_discovery")

    def test_empty_claim_scope_still_unions_node_neighbors_and_curated_retrieval(self):
        evidence = self.bundle["evidence"][0]
        claim = next(c for c in self.bundle["claims"] if c["id"] == evidence["claim_id"])
        node_id = claim["subject"]
        # This retrieved curated claim may not be incident to the selected node.
        other_claim = next(c for c in self.bundle["claims"] if c["id"] != claim["id"]
                           and node_id not in {c["subject"], c["object"]})
        other_evidence = next(e for e in self.bundle["evidence"] if e["claim_id"] == other_claim["id"])
        other_source = next(s for s in self.bundle['sources'] if s['id'] == other_evidence['source_id'])
        self.retriever.hits = [{"id": "curated-2", "source_id": other_evidence["source_id"],
            "url": other_source['url'], "locator": other_evidence['locator'],
            "text": other_evidence["excerpt"], "kind": "curated_evidence", "claim_id": other_claim["id"],
            "evidence_id": other_evidence["id"]}]
        self.client.data["paragraphs"][0].update({"citations": [1], "claim_ids": [other_claim["id"]]})
        self.assistant.answer(self.bundle, "Question", node_id=node_id, claim_ids=[])
        self.assertIn(other_claim["id"], self.client.prompt)

    def test_reviewed_passage_requires_visible_excerpt_and_matching_source_metadata(self):
        evidence = self.bundle['evidence'][0]
        source = next(s for s in self.bundle['sources'] if s['id'] == evidence['source_id'])
        source['version'] = 'current-v1'
        evidence.update(review_status='human_reviewed', source_version='current-v1')
        original = {'id': 'curated-1', 'source_id': source['id'], 'url': source['url'],
                    'locator': evidence['locator'], 'text': evidence['excerpt'], 'kind': 'curated_evidence',
                    'claim_id': evidence['claim_id'], 'evidence_id': evidence['id'], 'source_version': 'current-v1'}
        for change in ({'url': 'https://different.example/source'}, {'locator': 'wrong page'},
                       {'source_version': 'prior-v0'}, {'source_version': None},
                       {'text': 'Unreviewed text. ' * 400 + evidence['excerpt']}):
            with self.subTest(change=list(change)):
                self.retriever.hits = [{**original, **change}]
                result = self.assistant.answer(self.bundle, 'Question')
                self.assertEqual(result['sources'][0]['classification'], 'unreviewed_discovery')
                self.assertEqual(result['sources'][0]['claim_ids'], [])
        self.retriever.hits = [{**original, 'text': 'Unreviewed surrounding claim. ' + evidence['excerpt']}]
        result = self.assistant.answer(self.bundle, 'Question')
        self.assertEqual(result['sources'][0]['classification'], 'reviewed_graph_evidence')
        self.assertEqual(result['sources'][0]['text'], evidence['excerpt'])
        self.assertNotIn('Unreviewed surrounding claim.', self.client.prompt)

    def test_selected_node_does_not_export_arbitrary_properties_or_unbounded_aliases(self):
        node = self.bundle['nodes'][0]
        node['properties'] = {'secret': 'unrelated-private-value' * 50000}
        node['aliases'] = ['alias' * 1000] * 1000
        self.assistant.answer(self.bundle, 'Question', node_id=node['id'])
        prompt = json.loads(self.client.prompt.split('\n\n', 1)[1])
        selected = prompt['selected_node']
        self.assertEqual(set(selected), {'id', 'type', 'label', 'aliases'})
        self.assertLess(len(json.dumps(selected)), 2000)
        self.assertNotIn('unrelated-private-value', self.client.prompt)

    def test_counterevidence_selection_prefers_active_current_sources(self):
        evidence = self.bundle['evidence'][0]
        source = next(s for s in self.bundle['sources'] if s['id'] == evidence['source_id'])
        stale_source = {**source, 'id': 'stale-counter-source', 'status': 'retracted'}
        active_source = {**source, 'id': 'active-counter-source', 'version': 'v1'}
        self.bundle['sources'].extend([stale_source, active_source])
        self.bundle['evidence'].extend([
            {**evidence, 'id': 'a-stale-counter', 'source_id': stale_source['id'], 'stance': 'contradicts', 'excerpt': 'STALE COUNTER'},
            {**evidence, 'id': 'z-current-counter', 'source_id': active_source['id'], 'source_version': 'v1',
             'review_status': 'human_reviewed', 'stance': 'contradicts', 'excerpt': 'ACTIVE COUNTER'}])
        self.assistant.answer(self.bundle, 'Question', claim_ids=[evidence['claim_id']])
        prompt = json.loads(self.client.prompt.split('\n\n', 1)[1])
        claim = next(c for c in prompt['graph_claims'] if c['id'] == evidence['claim_id'])
        self.assertIn('ACTIVE COUNTER', [e['excerpt'] for e in claim['evidence']])
        self.assertNotIn('STALE COUNTER', [e['excerpt'] for e in claim['evidence']])

    def test_assessment_is_bound_to_snapshot_policy_and_selected_claim_basis(self):
        from tests.test_recommendations import fixture as recommendation_fixture, request
        bundle = recommendation_fixture()
        analysis = RecommendationEngine(bundle).assess(request())
        for change in ({'policy_version': 'old-policy'}, {'snapshot_id': 'foreign-snapshot'}):
            with self.subTest(change=change):
                self.assistant.answer(bundle, 'Question', analysis={**analysis, **change})
                self.assertIsNone(json.loads(self.client.prompt.split('\n\n', 1)[1])['deterministic_assessment'])
        self.assistant.answer(bundle, 'Question', analysis=analysis)
        prompt = json.loads(self.client.prompt.split('\n\n', 1)[1])
        self.assertTrue(prompt['deterministic_assessment']['recommendations'])
        invalid = deepcopy(analysis)
        invalid['recommendations'][0]['gates'][0]['claim_ids'] = ['invented-claim']
        self.assistant.answer(bundle, 'Question', analysis=invalid)
        self.assertIsNone(json.loads(self.client.prompt.split('\n\n', 1)[1])['deterministic_assessment'])
        for field, value in (('status', 'ready_for_discussion'), ('next_action', 'Invented access route')):
            invalid = deepcopy(analysis)
            invalid['recommendations'][-1][field] = value
            self.assistant.answer(bundle, 'Question', analysis=invalid)
            self.assertIsNone(json.loads(self.client.prompt.split('\n\n', 1)[1])['deterministic_assessment'])
        invalid = deepcopy(analysis)
        invalid['recommendations'][0]['citations'][0]['id'] = 'foreign-evidence'
        self.assistant.answer(bundle, 'Question', analysis=invalid)
        self.assertIsNone(json.loads(self.client.prompt.split('\n\n', 1)[1])['deterministic_assessment'])
        # A narrower question cannot inherit a ready label after dropping its basis.
        self.retriever.hits = []
        self.client.data['paragraphs'][0].update(citations=[], claim_ids=['demo:anchor-step'])
        self.assistant.answer(bundle, 'Question', claim_ids=['demo:anchor-step'], analysis=analysis)
        prompt = json.loads(self.client.prompt.split('\n\n', 1)[1])
        self.assertEqual(prompt['deterministic_assessment']['recommendations'], [])


if __name__ == "__main__":
    unittest.main()

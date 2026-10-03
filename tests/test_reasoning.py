"""Small explicit fixtures for the conservative Atlas reasoning rules."""

import unittest

from atlas.reasoning import AtlasReasoner


def fixture():
    nodes = [
        {"id": "a", "type": "Disease", "label": "Aurora"},
        {"id": "b", "type": "Disease", "label": "Boreal"},
        {"id": "c", "type": "Disease", "label": "Cinder"},
        {"id": "m", "type": "Mechanism", "label": "Transport"},
        {"id": "va", "type": "Variant", "label": "VA"},
        {"id": "vb", "type": "Variant", "label": "VB"},
        {"id": "vc", "type": "Variant", "label": "VC"},
        {"id": "g", "type": "Gene", "label": "GENE"},
        {"id": "asset", "type": "Asset", "label": "Registry design", "properties": {
            "reuse_scope": "Design review only", "limitations": ["No access rights implied."],
            "validation_questions": ["Does the design fit?"]}},
        {"id": "org", "type": "Organization", "label": "Boreal group"},
        {"id": "phen", "type": "Phenotype", "label": "Motor finding"},
    ]
    claims, evidence = [], []
    sources = [{"id": "s", "title": "Fixture source", "url": "https://example.org/source", "kind": "fixture"}]

    def add(cid, subject, predicate, obj, *, effect="unknown", assertion="reported", stance="supports", context=None):
        claims.append({"id": cid, "subject": subject, "predicate": predicate, "object": obj,
                       "assertion_type": assertion,
                       "context": context if context is not None else {"effect": effect, "species": "human", "tissue": "neural", "stage": "childhood"}})
        if stance:
            evidence.append({"id": "ev-" + cid, "claim_id": cid, "source_id": "s", "locator": cid,
                             "excerpt": "Fictional evidence for " + cid, "stance": stance, "review_status": "human_reviewed"})

    add("a-v", "a", "HAS_VARIANT", "va", context={})
    add("a-e", "va", "HAS_EFFECT", "m", effect="loss_of_function")
    add("b-v", "b", "HAS_VARIANT", "vb", context={})
    add("b-e", "vb", "HAS_EFFECT", "m", effect="loss_of_function")
    add("b-asset", "asset", "RELEVANT_TO", "b", context={})
    add("b-owner", "org", "MAINTAINS", "asset", context={})
    add("b-org", "org", "REPRESENTS", "b", context={})
    return {"dataset": {"synthetic": True}, "nodes": nodes, "claims": claims,
            "sources": sources, "evidence": evidence, "coverage": [
                {"id": "cov-a", "source_id": "s", "entity_id": "a", "scope": "fixture scope",
                 "status": "searched", "searched_at": "2026-01-01", "notes": "test"}]}, add


def candidate(result, disease_id):
    return next(item for item in result["candidates"] if item["disease"]["id"] == disease_id)


class AtlasReasonerTests(unittest.TestCase):
    def test_supported_mechanism_and_evidenced_asset_owner_route(self):
        bundle, _ = fixture()
        result = AtlasReasoner(bundle).explore("a")
        boreal = candidate(result, "b")
        self.assertEqual("supported_lead", boreal["status"])
        self.assertIn("a-e", boreal["path_claim_ids"])
        self.assertIn("b-e", boreal["path_claim_ids"])
        self.assertTrue(any(item["source"]["id"] == "s" for item in boreal["evidence"]))
        self.assertEqual("leads_found", result["status"])
        self.assertEqual("asset", result["opportunities"][0]["asset"]["id"])
        self.assertEqual("a", result["opportunities"][0]["source_disease"]["id"])
        self.assertEqual("org", result["opportunities"][0]["organizations"][0]["id"])
        self.assertIn("a-e", result["opportunities"][0]["path_claim_ids"])
        self.assertIn("expert", result["opportunities"][0]["next_step"])
        self.assertTrue(result["synthetic"])

    def test_same_gene_does_not_rescue_opposite_effect(self):
        bundle, add = fixture()
        bundle["nodes"].append({"id": "gene", "type": "Gene", "label": "Shared gene"})
        add("c-v", "c", "HAS_VARIANT", "vc", context={})
        add("c-gene", "vc", "AFFECTS", "gene", context={})
        add("a-gene", "va", "AFFECTS", "gene", context={})
        add("c-e", "vc", "HAS_EFFECT", "m", effect="gain_of_function")
        result = AtlasReasoner(bundle).explore("a")
        cinder = candidate(result, "c")
        self.assertEqual("rejected", cinder["status"])
        self.assertIn("opposite_effect_contexts_disqualify_shared_mechanism", cinder["reasons"])

    def test_shared_phenotype_alone_is_rejected(self):
        bundle, add = fixture()
        add("a-p", "a", "HAS_PHENOTYPE", "phen", context={})
        add("b-p", "b", "HAS_PHENOTYPE", "phen", context={})
        # Remove the shared-mechanism path so only phenotype overlap remains.
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] not in {"a-v", "a-e", "b-v", "b-e"}]
        result = AtlasReasoner(bundle).explore("a")
        boreal = candidate(result, "b")
        self.assertEqual("rejected", boreal["status"])
        self.assertIn("phenotype_overlap_alone_is_insufficient_without_a_supported_shared_mechanism", boreal["reasons"])
        self.assertEqual([], result["opportunities"])

    def test_negated_phenotype_does_not_create_an_overlap_candidate(self):
        bundle, add = fixture()
        add("a-neg-p", "a", "HAS_PHENOTYPE", "phen", context={"negated": True})
        add("b-p", "b", "HAS_PHENOTYPE", "phen", context={})
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] not in {"a-v", "a-e", "b-v", "b-e"}]
        result = AtlasReasoner(bundle).explore("a")
        self.assertFalse(any(item["disease"]["id"] == "b" for item in result["candidates"]))

    def test_negated_mechanism_or_asset_link_cannot_support_a_route(self):
        bundle, add = fixture()
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] != "b-asset"]
        bundle["evidence"][:] = [e for e in bundle["evidence"] if e["claim_id"] != "b-asset"]
        add("b-asset", "asset", "RELEVANT_TO", "b", context={"negated": True})
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("no_supported_route", result["status"])
        self.assertEqual([], result["opportunities"])

        bundle, add = fixture()
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] != "b-e"]
        bundle["evidence"][:] = [e for e in bundle["evidence"] if e["claim_id"] != "b-e"]
        add("b-e", "vb", "HAS_EFFECT", "m", effect="loss_of_function", context={"negated": True})
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("rejected", candidate(result, "b")["status"])

    def test_supported_contraindication_excludes_asset_and_keeps_evidence(self):
        bundle, add = fixture()
        add("asset-contra-b", "asset", "CONTRAINDICATED_FOR", "b", context={})
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("no_supported_route", result["status"])
        rejected = next(item for item in result["opportunities"] if item["status"] == "rejected")
        self.assertIn("asset-contra-b", rejected["path_claim_ids"])
        self.assertTrue(any(e["claim_id"] == "asset-contra-b" for e in rejected["evidence"]))
        self.assertIsNone(rejected["proposal"])

    def test_review_path_is_not_counted_as_a_supported_actionable_route(self):
        bundle, add = fixture()
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] != "b-e"]
        bundle["evidence"][:] = [e for e in bundle["evidence"] if e["claim_id"] != "b-e"]
        add("b-e", "vb", "HAS_EFFECT", "m", effect="unknown")
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("needs_review", result["opportunities"][0]["status"])
        self.assertEqual("no_supported_route", result["status"])

    def test_unreviewed_extracted_quote_cannot_promote_a_lead_or_actionable_route(self):
        bundle, _ = fixture()
        evidence = next(e for e in bundle["evidence"] if e["claim_id"] == "b-e")
        evidence["review_status"] = "unreviewed"
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("needs_review", candidate(result, "b")["status"])
        self.assertIn("supporting_evidence_is_unreviewed_and_requires_review", candidate(result, "b")["reasons"])
        self.assertEqual("no_supported_route", result["status"])
        self.assertTrue(all(op["status"] != "supported_route" for op in result["opportunities"]))
        self.assertTrue(any(e["review_status"] == "unreviewed" for e in candidate(result, "b")["evidence"]))

    def test_unreviewed_asset_and_owner_edges_do_not_form_a_route(self):
        bundle, _ = fixture()
        for evidence in bundle["evidence"]:
            if evidence["claim_id"] in {"b-asset", "b-owner"}:
                evidence["review_status"] = "unreviewed"
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("no_supported_route", result["status"])
        self.assertEqual([], result["opportunities"])

    def test_alternative_contradiction_is_exposed_but_excluded_from_chosen_route(self):
        bundle, add = fixture()
        bundle["nodes"].append({"id": "vb2", "type": "Variant", "label": "VB2"})
        add("b-v2", "b", "HAS_VARIANT", "vb2", context={})
        add("b-e2", "vb2", "HAS_EFFECT", "m", effect="loss_of_function", stance="contradicts")
        result = AtlasReasoner(bundle).explore("a")
        boreal = candidate(result, "b")
        self.assertEqual("supported_lead", boreal["status"])
        self.assertTrue(any(e["stance"] == "contradicts" for e in boreal["evidence"]))
        opportunity = next(item for item in result["opportunities"] if item["candidate_id"] == "b")
        self.assertNotIn("b-e2", opportunity["path_claim_ids"])

    def test_contradicted_mechanism_is_exposed_but_rejected(self):
        bundle, add = fixture()
        bundle["evidence"].append({"id": "ev-b-e-conflict", "claim_id": "b-e", "source_id": "s",
                                   "locator": "conflicting result", "excerpt": "Fictional contradiction",
                                   "stance": "contradicts", "review_status": "unreviewed"})
        result = AtlasReasoner(bundle).explore("a")
        boreal = candidate(result, "b")
        self.assertEqual("rejected", boreal["status"])
        self.assertTrue(any(e["stance"] == "contradicts" for e in boreal["evidence"]))
        self.assertIn("mechanistic_path_has_contradicting_evidence", boreal["reasons"])

    def test_inferred_only_and_unsupported_mechanism_paths_are_rejected(self):
        for assertion, stance in (("inferred", "supports"), ("reported", None)):
            with self.subTest(assertion=assertion, stance=stance):
                bundle, add = fixture()
                bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] != "b-e"]
                bundle["evidence"][:] = [e for e in bundle["evidence"] if e["claim_id"] != "b-e"]
                add("b-e", "vb", "HAS_EFFECT", "m", effect="loss_of_function", assertion=assertion, stance=stance)
                result = AtlasReasoner(bundle).explore("a")
                self.assertEqual("rejected", candidate(result, "b")["status"])

    def test_unknown_effect_requires_review_and_does_not_become_supported_biology(self):
        bundle, add = fixture()
        bundle["claims"][:] = [c for c in bundle["claims"] if c["id"] != "b-e"]
        bundle["evidence"][:] = [e for e in bundle["evidence"] if e["claim_id"] != "b-e"]
        add("b-e", "vb", "HAS_EFFECT", "m", effect="unknown")
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("needs_review", candidate(result, "b")["status"])
        self.assertEqual("no_supported_route", result["status"])
        self.assertEqual("b", result["opportunities"][0]["candidate_id"])
        self.assertEqual("needs_review", result["opportunities"][0]["status"])

    def test_missing_maintainer_prevents_actionable_route(self):
        bundle, _ = fixture()
        bundle["claims"] = [c for c in bundle["claims"] if c["id"] != "b-owner"]
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("supported_lead", candidate(result, "b")["status"])
        self.assertEqual("no_supported_route", result["status"])
        self.assertEqual([], result["opportunities"])

    def test_empty_search_result_reports_coverage_and_no_supported_route(self):
        bundle, _ = fixture()
        bundle["claims"][:] = []
        bundle["coverage"][0]["status"] = "failed"
        result = AtlasReasoner(bundle).explore("a")
        self.assertEqual("no_supported_route", result["status"])
        self.assertEqual([], result["candidates"])
        self.assertEqual("failed", result["coverage"][0]["status"])
        self.assertTrue(any("coverage is failed" in gap for gap in result["gaps"]))


if __name__ == "__main__":
    unittest.main()

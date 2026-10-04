"""Regression checks for the curated neuro source corpus and review-safe request."""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from atlas.model import require_valid_bundle
from atlas.recommendations import RecommendationEngine, ResearchRequest

ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated"


def load_corpus():
    bundle = json.loads((CURATED / "neuro_bundle.json").read_text(encoding="utf-8"))
    documents = json.loads((CURATED / "neuro_documents.json").read_text(encoding="utf-8"))
    request = json.loads((CURATED / "neuro_request.json").read_text(encoding="utf-8"))
    return bundle, documents, request


class NeuroCorpusTests(unittest.TestCase):
    def test_bundle_schema_hashes_and_exact_evidence_spans(self):
        bundle, documents, _ = load_corpus()
        require_valid_bundle(bundle)

        self.assertIs(bundle["dataset"]["synthetic"], False)
        self.assertTrue(all(source["synthetic"] is False for source in bundle["sources"]))
        docs_by_source = {doc["source_id"]: doc for doc in documents}
        sources_by_id = {source["id"]: source for source in bundle["sources"]}
        self.assertEqual(set(docs_by_source), set(sources_by_id))

        for source_id, doc in docs_by_source.items():
            text = doc["text"]
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            self.assertEqual(doc["version"], digest)
            self.assertEqual(sources_by_id[source_id]["version"], digest)
            self.assertTrue(doc["url"].startswith("https://pmc.ncbi.nlm.nih.gov/articles/PMC"))
            self.assertEqual(doc["url"], sources_by_id[source_id]["url"])
            self.assertEqual(doc["license"], sources_by_id[source_id]["license"])

        for evidence in bundle["evidence"]:
            doc = docs_by_source[evidence["source_id"]]
            start, end = map(int, evidence["locator"].split(" ")[2].split("-"))
            self.assertEqual(doc["text"][start:end], evidence["excerpt"])
            self.assertEqual(evidence["source_version"], doc["version"])
            self.assertIn(evidence["excerpt"], doc["text"])
            self.assertIn(evidence["review_status"], {"machine_checked", "unreviewed"})

    def test_science_steps_and_candidate_readout_stay_distinct(self):
        bundle, documents, request_data = load_corpus()
        nodes = {node["id"]: node for node in bundle["nodes"]}
        claims = {claim["id"]: claim for claim in bundle["claims"]}
        evidence = {row["id"]: row for row in bundle["evidence"]}
        docs = {doc["source_id"]: doc["text"] for doc in documents}

        self.assertEqual(claims["claim:vici-involves-fusion"]["context"]["mechanism_step"], "autophagosome–lysosome fusion")
        epg5_asset = nodes["asset:vici-tandem-lc3"]
        self.assertIn("proxy", epg5_asset["properties"]["interpretation_caveat"].lower())
        self.assertEqual(claims["claim:vici-assay-measures-fusion"]["context"]["mechanism_step"], "autophagosome–lysosome fusion")
        self.assertEqual(claims["claim:vici-assay-measures-fusion"]["context"]["tissue"], "EPG5-knockout HeLa cells")
        self.assertIn("Pearson’s correlation index", docs["epg5-vici-fusion-2018"])
        self.assertIn("cultured skin fibroblasts (SFs)", docs["epg5-vici-fusion-2018"])

        self.assertEqual(claims["claim:bpan-involves-formation"]["context"]["mechanism_step"], "early autophagosome formation")
        self.assertIn("WDR45 (WIPI4) is essential for the early stages of autophagosome formation.", evidence["evidence:bpan-anchor"]["excerpt"])
        self.assertEqual(claims["claim:bpan-assay-measures-formation"]["context"]["readout"], "LC3 puncta count (autophagosome proxy)")

        self.assertEqual(claims["claim:spg47-involves-atg9a"]["context"]["mechanism_step"], "AP-4-dependent ATG9A trafficking")
        self.assertIn("TGN46", claims["claim:ap4-assay-measures-atg9a"]["context"]["readout"])
        self.assertIn("TGN46", evidence["evidence:ap4-assay"]["excerpt"])

        self.assertEqual(claims["claim:vici-assay-measures-fusion"]["object"], "mechanism:autophagy")
        self.assertEqual(claims["claim:bpan-assay-measures-formation"]["object"], "mechanism:autophagy")
        self.assertEqual(claims["claim:ap4-assay-measures-atg9a"]["object"], "mechanism:autophagy")
        self.assertFalse(any(claim["predicate"] == "MAINTAINS" for claim in bundle["claims"]))
        self.assertEqual(request_data["mechanism_id"], "mechanism:autophagy")
        self.assertEqual(request_data["mechanism_step"], "autophagosome–lysosome fusion")

    def test_request_stays_pending_without_human_review_or_access_evidence(self):
        bundle, _, request_data = load_corpus()
        self.assertTrue(all(row["review_status"] != "human_reviewed" for row in bundle["evidence"]))
        request = ResearchRequest.from_dict(request_data)
        result = RecommendationEngine(bundle).assess(request)

        self.assertEqual(result["candidate_count"], 3)
        self.assertEqual(result["status"], "no_ready_candidate")
        by_asset = {row["asset_id"]: row for row in result["recommendations"]}
        self.assertEqual(by_asset["asset:vici-tandem-lc3"]["status"], "needs_clarification")
        self.assertTrue(all(row["status"] == "needs_clarification" for row in result["recommendations"]))
        self.assertTrue(all(not row["partner"] for row in result["recommendations"]))

"""Resolved artifact traversal and read-only API integration tests."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

from atlas.resolution import resolve_entities
from atlas.resolved_graph import ResolvedGraph
from atlas.server import create_server
from atlas.store import GraphStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data" / "fixtures" / "atlas-demo.json"


def resolved_artifact(path):
    raw_nodes = [
        {"id": "MONDO:0001", "type": "Disease", "label": "Vici syndrome", "aliases": ["Vici disorder"],
         "properties": {"mondo_id": "MONDO:0001"}, "provenance": {"source_id": "source:disease"}},
        {"id": "source:disease-vici", "type": "Disease", "label": "Vici disease",
         "aliases": [], "properties": {}, "provenance": {"source_id": "source:paper"}},
        {"id": "HGNC:17465", "type": "Gene", "label": "EPG5", "aliases": [], "properties": {},
         "provenance": {"source_id": "source:gene"}},
        {"id": "HP:0000001", "type": "Phenotype", "label": "Phenotype one", "aliases": [], "properties": {}},
        {"id": "asset:assay", "type": "Asset", "label": "LC3 assay", "aliases": [], "properties": {}},
        {"id": "PMID:12345", "type": "Publication", "label": "A paper", "aliases": [], "properties": {}},
        {"id": "ORG:1", "type": "Organization", "label": "Research group", "aliases": [], "properties": {}},
        {"id": "NCT:12345678", "type": "Study", "label": "Trial", "aliases": [], "properties": {}},
        {"id": "unconnected:1", "type": "Mechanism", "label": "Isolated mechanism", "aliases": [], "properties": {}},
        {"id": "gene:ambiguous", "type": "Gene", "label": "Conflicting registry record", "aliases": [],
         "properties": {"identifiers": {"hgnc": ["HGNC:1", "HGNC:2"]}}},
    ]
    resolution = resolve_entities(raw_nodes, [{"subject": "MONDO:0001", "object": "source:disease-vici",
        "rule": "curated_identifier", "provenance": {"source_id": "source:curation", "excerpt": "same ID"}}])
    disease = resolution["alias_map"]["source:disease-vici"]
    gene, phenotype, asset = "HGNC:17465", "HP:0000001", "asset:assay"
    sources = [
        {"id": "source:support", "title": "Supporting study", "url": "https://example.org/support",
         "kind": "paper", "retrieved_at": "2026-10-04", "published_at": None, "license": "CC BY",
         "version": "support-v1", "text": "Full text of supporting source."},
        {"id": "source:conflict", "title": "Conflicting study", "url": "https://example.org/conflict",
         "kind": "paper", "retrieved_at": "2026-10-04", "published_at": None, "license": "CC BY",
         "version": "conflict-v1", "text": "Full text of conflicting source."},
        {"id": "source:phenotype", "title": "Phenotype database", "url": "https://example.org/phenotype",
         "kind": "database", "retrieved_at": "2026-10-04", "published_at": None, "license": "CC0",
         "version": "phenotype-v1", "text": "Raw database dump."},
    ]
    claims = [
        {"id": "claim:disease-phenotype", "subject": disease, "predicate": "HAS_PHENOTYPE", "object": phenotype,
         "assertion_type": "reported", "context": {"species": "human"}, "extraction_confidence": 0.8},
        {"id": "claim:gene-disease", "subject": gene, "predicate": "ASSOCIATED_WITH_DISEASE", "object": disease,
         "assertion_type": "reported", "context": {}, "extraction_confidence": 0.7},
        {"id": "claim:asset-disease", "subject": asset, "predicate": "RELEVANT_TO", "object": disease,
         "assertion_type": "inferred", "context": {}, "extraction_confidence": 0.5},
        {"id": "claim:paper-disease", "subject": "PMID:12345", "predicate": "ABOUT", "object": disease,
         "assertion_type": "reported", "context": {}, "extraction_confidence": 0.6},
        {"id": "claim:org-disease", "subject": "ORG:1", "predicate": "REPRESENTS", "object": disease,
         "assertion_type": "reported", "context": {}, "extraction_confidence": 0.6},
        {"id": "claim:trial-disease", "subject": "NCT:12345678", "predicate": "STUDIES", "object": disease,
         "assertion_type": "reported", "context": {}, "extraction_confidence": 0.6},
    ]
    evidence = [
        {"id": "evidence:support", "claim_id": "claim:disease-phenotype", "source_id": "source:support",
         "excerpt": "Vici syndrome includes phenotype one.", "locator": "section 1", "stance": "supports",
         "review_status": "human_reviewed", "source_version": "support-v1"},
        {"id": "evidence:conflict", "claim_id": "claim:disease-phenotype", "source_id": "source:conflict",
         "excerpt": "Phenotype one was not observed.", "locator": "section 2", "stance": "contradicts",
         "review_status": "unreviewed", "source_version": "conflict-v1"},
        {"id": "evidence:gene", "claim_id": "claim:gene-disease", "source_id": "source:support",
         "excerpt": "EPG5 was linked to Vici syndrome.", "locator": "section 3", "stance": "supports",
         "review_status": "unreviewed", "source_version": "support-v1"},
    ]
    artifact = {"schema_version": "1.0", "dataset": {"id": "resolved-fixture", "title": "Resolved fixture"},
                "nodes": resolution["nodes"], "claims": claims, "evidence": evidence, "sources": sources,
                "resolution": {**resolution, "seeds": [disease], "stats": {"nodes": len(resolution["nodes"]), "claims": len(claims)}}}
    Path(path).write_text(json.dumps(artifact), encoding="utf-8")
    return artifact, disease


class ResolvedGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "resolved.json"
        self.artifact, self.disease = resolved_artifact(self.path)
        self.graph = ResolvedGraph(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_graph_pagination_is_bounded_and_focus_accepts_alias_ids(self):
        first = self.graph.graph(limit=2, focus="source:disease-vici", offset=0)
        self.assertEqual(first["harvest"]["focus"], self.disease)
        self.assertEqual(len(first["nodes"]), 2)
        self.assertEqual(first["harvest"]["next_offset"], 1)
        self.assertTrue(first["harvest"]["truncated"])
        self.assertEqual(first["nodes"][0]["id"], self.disease)
        self.assertTrue(first["nodes"][0]["properties"]["resolved"])
        second = self.graph.graph(limit=2, focus=self.disease, offset=1)
        self.assertNotEqual(first["nodes"][1]["id"], second["nodes"][1]["id"])
        self.assertEqual(second["harvest"]["next_offset"], 2)
        with self.assertRaises(KeyError):
            self.graph.graph(focus="missing:node")

    def test_global_pages_do_not_repeat_nodes_and_graph_sources_omit_raw_text(self):
        first = self.graph.graph(limit=3, offset=0)
        second = self.graph.graph(limit=3, offset=3)
        first_ids = {node["id"] for node in first["nodes"]}
        second_ids = {node["id"] for node in second["nodes"]}
        self.assertFalse(first_ids & second_ids)
        self.assertTrue(first["harvest"]["truncated"])
        self.assertNotIn("text", json.dumps(first["sources"]))
        self.assertLessEqual(len(first["nodes"]), 3)
        for node in first["nodes"]:
            identity = node["properties"]["identity_resolution"]
            self.assertIn("member_ids", identity)
            self.assertIn("node_provenance", identity)
            self.assertIn("link_provenance", identity)

    def test_search_matches_aliases_and_member_ids_with_total(self):
        result = self.graph.search("Vici disorder", limit=5)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["nodes"][0]["id"], self.disease)
        member_search = self.graph.search("source:disease-vici")
        self.assertEqual(member_search["nodes"][0]["id"], self.disease)
        self.assertEqual(self.graph.search(" ")["total"], 0)

    def test_node_detail_exposes_resolution_decisions_conflicts_and_provenance(self):
        detail = self.graph.node("source:disease-vici")
        self.assertEqual(detail["id"], self.disease)
        self.assertIn("MONDO:0001", detail["identity"]["members"])
        self.assertIn("source:disease-vici", detail["identity"]["members"])
        self.assertEqual(detail["identity"]["decisions"][0]["status"], "merged")
        self.assertIn("original_nodes", detail["provenance"])
        self.assertIn("identity_links", detail["provenance"])
        conflict = self.graph.node("gene:ambiguous")
        self.assertTrue(any(item.get("kind") == "node_identity_conflict" for item in conflict["identity"]["conflicts"]))

    def test_claim_detail_separates_support_and_contradiction_and_sources(self):
        detail = self.graph.claim("claim:disease-phenotype")
        self.assertEqual([row["id"] for row in detail["support"]], ["evidence:support"])
        self.assertEqual([row["id"] for row in detail["contradictions"]], ["evidence:conflict"])
        self.assertEqual({row["id"] for row in detail["sources"]}, {"source:support", "source:conflict"})
        self.assertIsNone(self.graph.claim("claim:missing"))


class ResolvedGraphAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "resolved.json"
        self.artifact, self.disease = resolved_artifact(path)
        self.resolved = ResolvedGraph(path)
        self.store = GraphStore()
        self.store.load_bundle(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.server = create_server(self.store, port=0, resolved=self.resolved)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()
        self.temp.cleanup()

    def get_json(self, path):
        with urlopen(self.base + path, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def get_error(self, path, status):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + path, timeout=2)
        self.assertEqual(caught.exception.code, status)
        with caught.exception as response:
            return json.loads(response.read().decode("utf-8"))

    def test_resolved_status_graph_search_node_and_claim_routes(self):
        _, status = self.get_json("/api/resolved/status")
        self.assertTrue(status["available"])
        self.assertEqual(status["stats"]["nodes"], len(self.artifact["nodes"]))
        self.assertIn(self.disease, status["seeds"])
        self.assertIn("source:disease-vici", status["alias_map"])
        _, page = self.get_json("/api/resolved/graph?limit=2&offset=0")
        self.assertEqual(len(page["nodes"]), 2)
        _, search = self.get_json("/api/resolved/search?q=Vici%20disorder")
        self.assertEqual(search["nodes"][0]["id"], self.disease)
        _, node = self.get_json("/api/resolved/node?id=source%3Adisease-vici")
        self.assertEqual(node["id"], self.disease)
        _, claim = self.get_json("/api/resolved/claim?id=claim%3Adisease-phenotype")
        self.assertEqual(len(claim["support"]), 1)
        self.assertEqual(len(claim["contradictions"]), 1)

    def test_invalid_bounds_and_missing_entities_use_safe_400_404_json(self):
        for path in ("/api/resolved/graph?limit=1", "/api/resolved/graph?limit=no",
                     "/api/resolved/graph?offset=-1", "/api/resolved/search?limit=101",
                     "/api/resolved/search?limit=0", "/api/resolved/node"):
            with self.subTest(path=path):
                payload = self.get_error(path, 400)
                self.assertIn("error", payload)
        for path in ("/api/resolved/graph?focus=missing%3Aid", "/api/resolved/node?id=missing%3Aid",
                     "/api/resolved/claim?id=missing%3Aclaim", "/api/resolved/unknown"):
            with self.subTest(path=path):
                payload = self.get_error(path, 404)
                self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()

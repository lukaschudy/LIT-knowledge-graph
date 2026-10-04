"""Catalog snapshots, scope selection, provenance and result ranking."""
import json
from hashlib import sha256
import gzip
from pathlib import Path
import shutil
import tempfile
import unittest

from atlas.catalog import CatalogError, EvidenceCatalog, combined_bundle
from atlas.search.passages import VERSION, bundle_documents, canonical, digest, file_sha
from atlas.search.topk import fuse


ROOT = Path(__file__).resolve().parents[1]


class EvidenceCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="atlas-catalog-fixture-")
        cls.root = Path(cls._tmp.name)
        cls._copy_inputs(cls.root)
        cls._write_export(cls.root)
        cls.catalog = EvidenceCatalog(cls.root, mode="local")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_fixed_chat_scope_has_separate_cache_from_global_search(self):
        scoped = self.catalog.search('evidence', scope='grin')
        global_result = self.catalog.search('evidence')
        self.assertEqual([s['id'] for s in scoped['scopes']], ['grin'])
        self.assertEqual({s['id'] for s in global_result['scopes']}, {'grin', 'neuro'})
        self.assertTrue(all(hit['scope'] == 'grin' for hit in scoped['hits']))
        with self.assertRaises(CatalogError):
            self.catalog.search('evidence', scope='unknown')

    @staticmethod
    def _copy_inputs(root):
        for relative in ("data/curated/neuro_documents.json", "data/curated/neuro_bundle.json",
                         "data/curated/grin_atlas_bundle.json"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)

    @staticmethod
    def _write_export(root):
        graph_path = root / "data/curated/grin_atlas_bundle.json"
        inputs = {"data/curated/grin_atlas_bundle.json": file_sha(graph_path)}
        snapshot = digest(canonical({"version": VERSION, "inputs": inputs}))[:24]
        rows = []
        for document in bundle_documents(json.loads(graph_path.read_text())):
            document["snapshot_id"] = snapshot
            document["export_version"] = VERSION
            document["_id"] = digest(canonical(document))
            rows.append(document)
        export = root / "data/processed/search/grin-passages.jsonl.gz"
        export.parent.mkdir(parents=True, exist_ok=True)
        with export.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as stream:
                for row in rows:
                    stream.write((canonical(row) + "\n").encode())
        manifest = {"version": VERSION, "snapshot_id": snapshot, "input_sha256": inputs,
                    "documents": len(rows), "export_sha256": file_sha(export), "live_topk_status": "verified",
                    "collection": "fixture-grin", "verified_documents": len(rows),
                    "verified_at": "2026-10-04T00:00:00+00:00"}
        receipt = root / "data/curated/topk-grin-index.json"
        receipt.write_text(json.dumps(manifest, indent=2) + "\n")

    def test_status_distinguishes_loaded_passages_from_verified_index_and_full_harvest(self):
        status = self.catalog.status()
        self.assertEqual(status["provider"], "local_lexical")
        self.assertFalse(status["configured"])
        self.assertFalse(status["full_harvest_indexed"])
        self.assertEqual(status["loaded_passages"], sum(s["loaded_passages"] for s in status["scopes"]))
        grin = next(scope for scope in status["scopes"] if scope["id"] == "grin")
        self.assertEqual(grin["index_status"], "verified_snapshot")
        self.assertEqual(grin["loaded_passages"], grin["indexed_passages"])
        self.assertEqual(status["note"], self.catalog.status()["note"])

    def test_passage_receipt_checksums_and_canonical_snapshot_are_consistent(self):
        manifest = json.loads((self.root / "data/curated/topk-grin-index.json").read_text())
        self.assertEqual(canonical({"b": 2, "a": 1}), canonical({"a": 1, "b": 2}))
        self.assertEqual(file_sha(self.root / "data/processed/search/grin-passages.jsonl.gz"), manifest["export_sha256"])
        expected = sha256(canonical({"version": manifest["version"],
            "inputs": manifest["input_sha256"]}).encode()).hexdigest()[:24]
        self.assertEqual(expected, manifest["snapshot_id"])
        graph_hash = manifest["input_sha256"]["data/curated/grin_atlas_bundle.json"]
        self.assertEqual(file_sha(self.root / "data/curated/grin_atlas_bundle.json"), graph_hash)

    def test_source_version_binding_requires_exact_local_evidence_metadata(self):
        row = next(row for row in self.catalog.grin_rows.values() if row['kind']=='curated_evidence').copy()
        graph=json.loads((self.root/'data/curated/grin_atlas_bundle.json').read_text())
        evidence=next(e for e in graph['evidence'] if e['id']==row['evidence_id']).copy()
        source=next(s for s in graph['sources'] if s['id']==evidence['source_id']).copy()
        source['version']='test-source-v1';evidence['source_version']='test-source-v1'
        normalized=EvidenceCatalog._normalize_grin(row,evidence=evidence,source=source)
        self.assertEqual(normalized['source_version'],'test-source-v1')
        for changed in ({'locator':'unrelated'}, {'url':'https://example.org/other'},
                        {'claim_id':'other'}, {'content':'Not the source excerpt.'}):
            with self.subTest(changed=changed):
                self.assertIsNone(EvidenceCatalog._normalize_grin({**row,**changed},evidence=evidence,source=source)['source_version'])
        evidence['source_version']='older-version'
        self.assertIsNone(EvidenceCatalog._normalize_grin(row,evidence=evidence,source=source)['source_version'])

    def test_scope_selection_keeps_neuro_and_grin_evidence_distinct(self):
        neuro = self.catalog.search("WDR45 BPAN autophagy", top_k=4)
        self.assertEqual(neuro["provider"], "local_lexical")
        self.assertEqual([scope["id"] for scope in neuro["scopes"]], ["neuro"])
        self.assertTrue(all(hit["scope"] == "neuro" for hit in neuro["hits"]))

        grin = self.catalog.search("GRIN2A S541R", top_k=4)
        self.assertEqual([scope["id"] for scope in grin["scopes"]], ["grin"])
        self.assertTrue(all(hit["scope"] == "grin" for hit in grin["hits"]))

        both = self.catalog.search("GRIN2A and EPG5 evidence", top_k=5)
        self.assertEqual({scope["id"] for scope in both["scopes"]}, {"grin", "neuro"})
        self.assertTrue({hit["scope"] for hit in both["hits"]} <= {"grin", "neuro"})

    def test_curated_hit_import_metadata_is_exact_and_copy_isolated(self):
        result = self.catalog.search("GRIN2A S541R", top_k=4)
        curated = next(hit for hit in result["hits"] if hit["kind"] == "curated_evidence")
        imported = self.catalog.get(curated["id"])
        self.assertEqual(imported["id"], curated["id"])
        self.assertEqual(imported["claim_id"], curated["claim_id"])
        self.assertEqual(imported["evidence_id"], curated["evidence_id"])
        self.assertEqual(imported["locator"], curated["locator"])
        self.assertEqual(imported["license"], curated["license"])
        self.assertEqual(imported["claim_ids"], [curated["claim_id"]])
        imported["text"] = "mutated"
        self.assertNotEqual(self.catalog.get(curated["id"])["text"], "mutated")

    def test_fusion_is_rank_based_deduplicated_and_stable(self):
        rankings = {"semantic": [{"_id": "a"}, {"_id": "b"}, {"_id": "a"}],
                    "keyword": [{"_id": "b"}, {"_id": "c"}]}
        result = fuse(rankings, k=3)
        self.assertEqual([item["_id"] for item in result], ["b", "a", "c"])
        self.assertEqual(result[0]["channel_ranks"], {"semantic": 2, "keyword": 1})
        self.assertEqual([item["_id"] for item in fuse(rankings, k=3)], ["b", "a", "c"])

    def test_combined_bundle_has_referentially_valid_merged_identity(self):
        bundle = combined_bundle(ROOT)
        self.assertEqual(bundle["dataset"]["id"], "atlas-connected-evidence-v1")
        identifiers = {name: {row["id"] for row in bundle[name]}
                       for name in ("nodes", "sources", "claims", "evidence")}
        self.assertTrue(all(row["subject"] in identifiers["nodes"] and row["object"] in identifiers["nodes"]
                            for row in bundle["claims"]))
        self.assertTrue(all(row["claim_id"] in identifiers["claims"] and row["source_id"] in identifiers["sources"]
                            for row in bundle["evidence"]))

    def test_export_checksum_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="atlas-catalog-test-") as tmp:
            root = Path(tmp)
            self._copy_inputs(root)
            self._write_export(root)
            export = root / "data/processed/search/grin-passages.jsonl.gz"
            export.write_bytes(export.read_bytes() + b"tamper")
            with self.assertRaisesRegex(CatalogError, "checksum"):
                EvidenceCatalog(root, mode="local")

    def test_incomplete_grin_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="atlas-catalog-test-") as tmp:
            root = Path(tmp)
            self._copy_inputs(root)
            self._write_export(root)
            receipt = root / "data/curated/topk-grin-index.json"
            content = json.loads(receipt.read_text())
            content["live_topk_status"] = "uploaded_not_verified"
            receipt.write_text(json.dumps(content))
            with self.assertRaisesRegex(CatalogError, "not verified"):
                EvidenceCatalog(root, mode="local")

    def test_explicit_local_mode_ignores_injected_remote_client(self):
        class RemoteMustNotRun:
            def collection(self, *_):
                raise AssertionError("local mode attempted remote search")
        catalog = EvidenceCatalog(self.root, mode="local", client=RemoteMustNotRun())
        self.assertFalse(catalog.status()["configured"])
        self.assertEqual(catalog.search("WDR45 BPAN")["provider"], "local_lexical")


if __name__ == "__main__":
    unittest.main()

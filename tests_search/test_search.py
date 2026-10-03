import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from atlas.search.passages import article_documents, bundle_documents, chunks, export, protein_mentions, read_rows, xml_units
from atlas.search.topk import batches, fuse, graph_connections, ingest, resolve_filters, settings

ROOT = Path(__file__).resolve().parents[1]


class PassageTests(unittest.TestCase):
    def test_variant_identity_and_no_substring_collisions(self):
        self.assertEqual(protein_mentions("p.Ser541Arg S541R S541G XS541RR"), ["S541G", "S541R"])
        self.assertEqual(resolve_filters("GRIN2B p.Ser541Arg current"), ("GRIN2B", "S541R"))
        self.assertEqual(resolve_filters("GRIN2A and GRIN2B S541R"), (None, None))
        with self.assertRaises(ValueError):
            resolve_filters("current", protein="S541R")

    def test_chunks_cover_every_character_with_bounded_overlap(self):
        text = " ".join(f"word{i}" for i in range(2000))
        covered = set()
        for start, end, part in chunks(text, maximum=200, overlap=30):
            self.assertEqual(part, text[start:end])
            self.assertLessEqual(len(part), 200)
            covered.update(range(start, end))
        self.assertTrue(all(i in covered or c.isspace() for i, c in enumerate(text)))

    def test_jats_locator_tables_and_references(self):
        xml = '<article><body><sec id="s1"><title>Results</title><p id="p1">GRIN2B <italic>S541R</italic> reduced current.</p><table-wrap id="t1"><table><tr><td>WT</td><td>10</td></tr></table></table-wrap></sec></body><back><ref-list><p>unrelated citation</p></ref-list></back></article>'
        rows = list(xml_units(xml))
        self.assertEqual(len(rows), 2)
        self.assertIn("p[1]#p1", rows[0][0])
        self.assertEqual(rows[0][1], "Results")
        self.assertEqual(rows[1][3], "table_text_uninterpreted")
        docs = list(article_documents({"pmcid": "PMC123", "title": "Study", "jats_xml": xml, "license": "cc by"}))
        self.assertEqual(docs[0]["proteins"], ["S541R"])
        self.assertEqual(docs[0]["effect"], "unknown")
        self.assertEqual(docs[0]["node_ids"], [])
        self.assertEqual(docs[1]["proteins"], [])

    def test_curated_context_preserves_opposing_and_provisional(self):
        bundle = json.loads((ROOT / "data/curated/grin_atlas_bundle.json").read_text())
        docs = list(bundle_documents(bundle))
        for protein, effect, tier in [("S541R", "loss_of_function", "core_likely_reduced"),
                                      ("S541G", "gain_of_function", "opposing_control"),
                                      ("C461F", "loss_of_function", "provisional_possible_reduced"),
                                      ("R540H", "unknown", "unresolved_control")]:
            selected = [d for d in docs if protein in d["proteins"] and d["cohort_tier"] == tier]
            self.assertTrue(selected)
            self.assertTrue(all(d["effect"] == effect for d in selected))
        raw_hit = {"kind": "article_text", "evidence_id": docs[0]["evidence_id"], "claim_id": docs[0]["claim_id"]}
        self.assertEqual(graph_connections([raw_hit], bundle), [])
        linked = graph_connections([docs[0]], bundle)
        self.assertEqual(linked[0]["matched_evidence"][0]["id"], docs[0]["evidence_id"])

    def test_export_reproducible_with_citations_and_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "passages.gz"
            a = export(ROOT, p, fulltext=False)
            b = export(ROOT, p, fulltext=False)
            self.assertEqual(a, b)
            rows = list(read_rows(p))
            self.assertEqual(len(rows), 56)
            self.assertEqual(len({r["_id"] for r in rows}), 56)
            for r in rows:
                self.assertTrue(r["locator"] and r["url"] and r["source_id"])
                self.assertEqual(r["snapshot_id"], a["snapshot_id"])


class TransportTests(unittest.TestCase):
    def test_rank_fusion_uses_rank_not_raw_score(self):
        ranks = {"keyword": [{"_id": "a", "retrieval_score": 999}, {"_id": "b", "retrieval_score": 1}],
                 "semantic": [{"_id": "b", "retrieval_score": .9}, {"_id": "c", "retrieval_score": .8}]}
        self.assertEqual(fuse(ranks)[0]["_id"], "b")

    def test_secret_loader_treats_values_literally(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ".env"
            p.write_text('TOPK_API_KEY="$(do-not-execute)"\nOTHER=ignored\nTOPK_REGION=\n')
            with patch.dict("os.environ", {}, clear=True):
                v = settings(p)
            self.assertEqual(v["TOPK_API_KEY"], "$(do-not-execute)")
            self.assertNotIn("OTHER", v)

    def test_transport_limits(self):
        self.assertEqual([len(b) for b in batches([{"x": "a"}] * 201)], [100, 100, 1])
        with self.assertRaises(ValueError):
            list(batches([{"x": "a" * 64001}]))

    def test_resume_after_unacknowledged_write_and_verify_contents(self):
        class Remote:
            def __init__(self):
                self.docs, self.calls, self.fail = {}, 0, True
            def upsert(self, rows):
                self.calls += 1
                self.docs.update({r["_id"]: r for r in rows})
                if self.fail:
                    self.fail = False
                    raise ConnectionError("lost ack")
                return "lsn1"
            def get(self, ids, **kw):
                return {k: self.docs[k] for k in ids}
        class Client:
            def __init__(self): self.remote = Remote()
            def collection(self, name): return self.remote
        with tempfile.TemporaryDirectory() as td:
            p, state = Path(td) / "rows.gz", Path(td) / "state.json"
            export(ROOT, p, fulltext=False)
            client = Client()
            with patch("atlas.search.topk.wire_documents", side_effect=lambda rows: rows):
                with self.assertRaises(ConnectionError):
                    ingest(client, "pilot", p, state, "region")
                self.assertFalse(state.exists())
                result = ingest(client, "pilot", p, state, "region")
                self.assertEqual(result["verified_documents"], 56)
                self.assertEqual(len(client.remote.docs), 56)
                ingest(client, "pilot", p, state, "region")
                self.assertEqual(client.remote.calls, 2)
                with self.assertRaises(ValueError):
                    ingest(client, "other", p, state, "region")
                next(iter(client.remote.docs.values()))["content"] = "corrupted"
                with self.assertRaises(ValueError):
                    ingest(client, "pilot", p, state, "region")


if __name__ == "__main__":
    unittest.main()

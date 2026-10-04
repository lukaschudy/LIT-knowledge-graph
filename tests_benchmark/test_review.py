from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from atlas.benchmark.contracts import digest
from atlas.benchmark.review import compare, packet
from tests_benchmark.fixtures import example


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.m, self.s, self.a, _ = example()
        self.b = deepcopy(self.a)
        for ref, name in [(self.a, "ai-a"), (self.b, "ai-b")]:
            for d in ref["documents"]:
                d["review"]["annotators"] = [name]
                d["decisions"] = []
        self.scope = {"scope_id": self.m["benchmark_id"], "description": self.m["scope"],
                      "document_ids": [d["document_id"] for d in self.m["documents"]],
                      "cells": [{"unit_id": u["unit_id"], "document_id": u["document_id"]} for u in self.s["units"]]}
        self.ca = {"cells": [{"unit_id": u["unit_id"], "state": "annotated", "observation_id": "reference-1"} for u in self.s["units"]]}
        self.cb = deepcopy(self.ca)

    def result(self):
        return compare(self.m, self.s, self.scope, self.a, self.b, self.ca, self.cb)

    def test_agreement_is_not_expert_accuracy(self):
        r = self.result()
        self.assertEqual(r["exact_observation_agreement"], {"agree": 2, "total": 2})
        self.assertFalse(r["scientifically_validated"])
        self.assertEqual(r["adjudication_status"], "pending")

    def test_protocol_difference_is_explicit_even_when_numbers_agree(self):
        self.b["documents"][0]["observations"][0]["conditions"]["protocol"] = "different"
        r = self.result()
        self.assertEqual(r["field_agreement"]["value"]["agree"], 2)
        self.assertEqual(r["exact_observation_agreement"]["agree"], 1)
        self.assertEqual(set(r["disagreements"][0]["fields"]), {"conditions"})

    def test_missingness_disagreement_not_ignored(self):
        self.b["documents"][0]["observations"] = []
        self.cb["cells"][0].update(state="not_reported", observation_id=None)
        r = self.result()
        self.assertEqual(r["coverage_state_agreement"], {"agree": 1, "total": 2})
        self.assertEqual(r["paired_observations"], 1)
        self.assertEqual(r["disagreements"][0]["type"], "coverage")

    def test_different_ids_do_not_count_as_disagreement(self):
        self.b["documents"][0]["observations"][0]["id"] = "b-id"
        self.cb["cells"][0]["observation_id"] = "b-id"
        self.assertEqual(self.result()["exact_observation_agreement"]["agree"], 2)

    def test_coverage_must_include_every_cell_once(self):
        self.cb["cells"].pop()
        with self.assertRaisesRegex(ValueError, "every scope cell"):
            self.result()

    def test_coverage_cannot_hide_extra_records(self):
        extra = deepcopy(self.b["documents"][0]["observations"][0])
        extra.update(id="extra", value="17")
        self.b["documents"][0]["observations"].append(extra)
        with self.assertRaisesRegex(ValueError, "outside declared coverage"):
            self.result()

    def test_same_reviewer_cannot_claim_independence(self):
        for doc in self.b["documents"]:
            doc["review"]["annotators"] = ["ai-a"]
        with self.assertRaisesRegex(ValueError, "same reviewer"):
            self.result()

    def test_expert_flag_is_not_inferred_from_agreement(self):
        self.b["documents"][0]["review"]["expert_reviewed"] = True
        with self.assertRaisesRegex(ValueError, "non-expert drafts"):
            self.result()

    def test_packet_is_source_only_and_reproducible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            ledger = {"documents": [{"document_id": d["document_id"]} for d in self.m["documents"]]}
            for name, value in [("manifest.json", self.m), ("sources.json", self.s), ("source-ledger.json", ledger)]:
                (source / name).write_text(json.dumps(value))
            a = packet(source, self.scope, root / "a")
            b = packet(source, self.scope, root / "b")
            self.assertEqual(a, b)
            r = json.loads((root / "a/reference-template.json").read_text())
            self.assertTrue(all(not d["observations"] and not d["review"]["annotators"] for d in r["documents"]))
            self.assertEqual(r["manifest_sha256"], digest(self.m))
            self.assertEqual(set(p.name for p in (root / "a").iterdir()), {"manifest.json", "sources.json", "source-ledger.json", "reference-template.json", "scope.json", "contract.py"})
            with self.assertRaisesRegex(ValueError, "already exists"):
                packet(source, self.scope, root / "a")


if __name__ == "__main__":
    unittest.main()

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from atlas.benchmark.contracts import digest, validate_manifest
from atlas.benchmark.scoring import bootstrap, maximum_matching, score
from tests_benchmark.fixtures import example


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.m, self.s, self.r, self.p = example()

    def report(self):
        return score(self.m, self.s, self.r, self.p, iterations=100)

    def test_perfect_fixture_is_not_scientific_validation(self):
        result = self.report()
        self.assertEqual(result["observations"], {"tp": 2, "fp": 0, "fn": 0, "precision": 1, "recall": 1, "f1": 1})
        self.assertEqual(result["decisions"]["grounded_accuracy"], 1)
        self.assertFalse(result["assessment"]["scientifically_validated"])
        self.assertEqual(result["assessment"]["status"], "inconclusive")

    def test_duplicates_count_as_false_positives(self):
        duplicate = deepcopy(self.p["documents"][0]["observations"][0])
        duplicate["id"] = "duplicate"
        self.p["documents"][0]["observations"].append(duplicate)
        result = self.report()["observations"]
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (2, 1, 0))

    def test_missing_document_and_decision_are_misses(self):
        self.p["documents"].pop()
        result = self.report()
        self.assertEqual(result["observations"]["recall"], .5)
        self.assertEqual(result["decisions"]["coverage"], .5)
        self.assertEqual(result["decisions"]["grounded_accuracy"], .5)
        self.assertEqual(result["documents"][1]["execution_status"], "missing")

    def test_empty_output_cannot_pass_on_precision(self):
        self.p["documents"] = []
        result = self.report()
        self.assertIsNone(result["observations"]["precision"])
        self.assertEqual(result["observations"]["recall"], 0)
        self.assertIsNone(result["operations"]["cost_per_correct_observation_usd"])

    def test_wrong_identity_is_not_rescued_by_same_number(self):
        self.p["documents"][0]["observations"][0]["variant"] = "p.Ala1Gly"
        result = self.report()
        self.assertEqual(result["observations"]["tp"], 1)
        self.assertEqual(result["decisions"]["label_accuracy"], 1)
        self.assertEqual(result["decisions"]["grounded_accuracy"], .5)

    def test_wrong_value_and_units_fail_strict_matching(self):
        for field, wrong in [("value", "300"), ("unit", "nA")]:
            with self.subTest(field=field):
                self.setUp()
                self.p["documents"][0]["observations"][0][field] = wrong
                result = self.report()
                self.assertEqual(result["observations"]["tp"], 1)
                self.assertEqual(result["field_diagnostics"][field]["accuracy"], .5)

    def test_decimal_equivalence_does_not_introduce_float_tolerance(self):
        row = self.p["documents"][0]["observations"][0]
        row["value"] = "3.000e1"
        self.assertEqual(self.report()["observations"]["tp"], 2)
        row["value"] = "30.00000000000000000000000000001"
        self.assertEqual(self.report()["observations"]["tp"], 1)

    def test_missing_and_forged_citations_are_not_grounded(self):
        row = self.p["documents"][0]["observations"][0]
        row["evidence"][0]["quote"] = "invented quote"
        result = self.report()
        self.assertEqual(result["observations"]["tp"], 1)
        self.assertEqual(result["source_spans"]["valid"], 1)
        self.assertEqual(result["documents"][0]["content_only_tp"], 1)
        row["evidence"] = []
        self.assertEqual(self.report()["observations"]["tp"], 1)

    def test_cross_document_citation_is_not_valid(self):
        self.p["documents"][0]["observations"][0]["evidence"] = deepcopy(self.p["documents"][1]["observations"][0]["evidence"])
        self.assertEqual(self.report()["observations"]["tp"], 1)

    def test_full_evidence_bundle_required(self):
        span = self.r["documents"][0]["observations"][0]["evidence_sets"][0][0]
        # The reference needs the complete paragraph; a real but shorter quote is insufficient.
        partial = self.p["documents"][0]["observations"][0]["evidence"][0]
        partial["end"] = 14
        partial["quote"] = span["quote"][:14]
        self.assertEqual(self.report()["observations"]["tp"], 1)

    def test_maximum_matching_not_greedy(self):
        p = [{"id": "a"}, {"id": "b"}]
        g = [{"id": "x"}, {"id": "y"}]
        matches = maximum_matching(p, g, lambda p, g: p["id"] == "a" or g["id"] == "x")
        self.assertEqual(matches, {"b": "x", "a": "y"})

    def test_study_cannot_cross_splits(self):
        d = self.m["documents"][1]
        d.update(study_id=self.m["documents"][0]["study_id"], split="held_out", known_development=False)
        with self.assertRaisesRegex(ValueError, "Study family"):
            validate_manifest(self.m)

    def test_known_development_cannot_be_reassigned(self):
        self.m["documents"][0]["split"] = "held_out"
        with self.assertRaisesRegex(ValueError, "Known development"):
            validate_manifest(self.m)

    def test_frozen_manifest_needs_reviewed_groups_and_snapshots(self):
        for field, wrong in [("grouping_reviewed", False), ("source_sha256", None)]:
            with self.subTest(field=field):
                self.setUp()
                self.m["documents"][0][field] = wrong
                with self.assertRaisesRegex(ValueError, "Frozen documents"):
                    validate_manifest(self.m)

    def test_source_tampering_and_manifest_tampering_fail(self):
        self.s["units"][0]["text"] += " modified"
        with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
            self.report()
        self.setUp()
        self.m["scope"] = "changed"
        with self.assertRaisesRegex(ValueError, "Reference does not match"):
            self.report()

    def test_reference_cannot_omit_selected_documents(self):
        self.r["documents"].pop()
        with self.assertRaisesRegex(ValueError, "every document"):
            self.report()

    def test_unknown_predictions_cannot_be_silently_dropped(self):
        self.p["documents"][0]["document_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "outside evaluation"):
            self.report()

    def test_reference_cannot_have_forged_evidence(self):
        self.r["documents"][0]["observations"][0]["evidence_sets"][0][0]["quote"] = "forged"
        with self.assertRaisesRegex(ValueError, "Ungrounded reference"):
            self.report()

    def test_null_is_not_zero(self):
        self.p["documents"][0]["observations"][0]["value"] = None
        self.assertEqual(self.report()["observations"]["tp"], 1)

    def test_failed_execution_is_explicit(self):
        self.p["documents"][0]["status"] = "failed"
        result = self.report()
        self.assertIn("Some document executions failed or are missing", result["assessment"]["reasons"])

    def test_bootstrap_resamples_studies_and_is_reproducible(self):
        rows = [{"study_id": "a", "tp": 3, "fp": 0, "fn": 0},
                {"study_id": "a", "tp": 4, "fp": 0, "fn": 0},
                {"study_id": "b", "tp": 0, "fp": 0, "fn": 7}]
        result = bootstrap(rows, 100, 42)
        self.assertEqual(result, bootstrap(rows, 100, 42))
        self.assertEqual(result["study_count"], 2)
        self.assertGreater(result["intervals"]["precision"]["undefined_draws"], 0)
        self.assertIsNone(bootstrap(rows[:2], 100)["intervals"])

    def test_unknown_fields_and_invalid_numbers_rejected(self):
        self.p["documents"][0]["observations"][0]["value"] = "NaN"
        with self.assertRaisesRegex(ValueError, "decimal string"):
            self.report()
        self.setUp()
        self.p["documents"][0]["observations"][0]["confidence"] = 1
        with self.assertRaisesRegex(ValueError, "expected exactly"):
            self.report()

    def test_cli_writes_report_once_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            command = [sys.executable, "-m", "atlas.benchmark", "score", "--bootstrap-iterations", "100"]
            for name, data in zip(("manifest", "sources", "reference", "predictions"), (self.m, self.s, self.r, self.p)):
                path = root / (name + ".json")
                path.write_text(json.dumps(data))
                command += ["--" + name, str(path)]
            output = root / "report.json"
            command += ["--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            before = output.read_bytes()
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(again.returncode, 2)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(json.loads(before)["input_hashes"]["manifest"], digest(self.m))


if __name__ == "__main__":
    unittest.main()

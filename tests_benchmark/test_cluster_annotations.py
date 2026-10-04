from copy import deepcopy
import unittest

from atlas.benchmark.cluster_annotations import compare, validate
from atlas.benchmark.contracts import digest
from atlas.cluster_demo import build, ratio, tier_for
from tests_benchmark.fixtures import example


def fixture():
    _, sources, reference, _ = example()
    def measurement(value, raw=None):
        return dict(raw=raw or value, estimate=value, relation="eq", unit="pA/pF", uncertainty_type=None,
                    uncertainty_value=None, ci_lower=None, ci_upper=None, n=5, n_unit=None, qualitative=None)
    observations = []
    for index, doc in enumerate(reference["documents"]):
        spans = doc["observations"][0]["evidence_sets"][0]
        observations.append(dict(id=f"o{index}", document_id=doc["document_id"], gene="GRIN2B", protein="p.Ser541Arg",
             table_id=f"{doc['document_id']}:table:1", row=2, column=2, endpoint="peak_current_density",
             assay="whole_cell_voltage_clamp", measurement_type="measured", sequence_context=None,
             conditions=dict(receptor="synthetic receptor", system="synthetic cells", protocol={"voltage": None}),
             measurement=measurement("30"), comparator=dict(label="WT", measurement=measurement("100"), evidence=spans), evidence=spans))
    data = dict(schema_version="grin-cluster-annotations-v2", reviewer="ai-a", review_type="independent_ai_draft", expert_reviewed=False,
                sources_sha256=digest(sources), observations=observations, claims=[], issues=[],
                coverage=[dict(document_id=d["document_id"], status="synthetic", scope="Invented software test", omissions=[], reviewed_tables=[]) for d in reference["documents"]])
    return data, sources


class ClusterAnnotationTests(unittest.TestCase):
    def test_intervals_and_censoring_survive_validation(self):
        a, s = fixture()
        a["observations"][0]["measurement"].update(uncertainty_type="95%CI", ci_lower="20", ci_upper="40")
        a["observations"][1]["measurement"].update(raw=">30", relation="gt")
        self.assertEqual(validate(a, s)["observations"], 2)
        self.assertIsNone(ratio(a["observations"][1]))

    def test_wrong_intervals_missingness_and_source_hash_fail(self):
        for mutation in [dict(ci_lower="50", ci_upper="40"), dict(relation="not_reported"), dict(relation="qualitative")]:
            a, s = fixture()
            a["observations"][0]["measurement"].update(mutation)
            with self.assertRaises(ValueError): validate(a, s)
        a, s = fixture()
        a["sources_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "checksum"): validate(a, s)

    def test_wrong_gene_identity_and_reused_cell_fail(self):
        a, s = fixture()
        a["observations"][0]["gene"] = "GRIN2A"
        with self.assertRaisesRegex(ValueError, "outside declared"): validate(a, s)
        a, s = fixture()
        copy = deepcopy(a["observations"][0]); copy["id"] = "other"
        a["observations"].append(copy)
        with self.assertRaisesRegex(ValueError, "Duplicate variant"): validate(a, s)

    def test_forged_span_and_missing_document_coverage_fail(self):
        a, s = fixture()
        a["observations"][0]["evidence"][0]["quote"] = "made up"
        with self.assertRaisesRegex(ValueError, "source evidence"): validate(a, s)
        a, s = fixture()
        a["coverage"].pop()
        with self.assertRaisesRegex(ValueError, "each source document"): validate(a, s)

    def test_ratio_respects_endpoint_units_zero_and_missing_wt(self):
        a, _ = fixture(); o = a["observations"][0]
        self.assertAlmostEqual(float(ratio(o)["value"]), .3)
        o["endpoint"] = "glutamate_ec50"
        self.assertAlmostEqual(float(ratio(o)["value"]), 100/30)
        o["comparator"]["measurement"]["unit"] = "nA"
        self.assertIsNone(ratio(o))
        o["comparator"]["measurement"]["unit"] = "pA/pF"
        o["comparator"]["measurement"]["estimate"] = "0"
        self.assertIsNone(ratio(o))
        o["comparator"]["measurement"] = None
        self.assertIsNone(ratio(o))

    def test_drug_response_and_calculated_values_do_not_gate_core(self):
        a, _ = fixture(); rows = a["observations"]
        claim = dict(category="Likely LoF", predicate="author_functional_classification", evidence_type="primary_report")
        self.assertEqual(tier_for([claim], rows), "core_likely_reduced")
        for row in rows: row["endpoint"] = "memantine_ic50"
        self.assertEqual(tier_for([claim], rows), "provisional_possible_reduced")
        self.assertIsNone(ratio(rows[0]))
        claim["evidence_type"] = "secondary_summary"
        self.assertEqual(tier_for([claim], rows), "unresolved_control")

    def test_conflicting_primary_categories_remain_unresolved(self):
        a, _ = fixture()
        claims = [dict(category=c, predicate="author_functional_classification", evidence_type="primary_report") for c in ("Likely LoF", "Possible GoF")]
        self.assertEqual(tier_for(claims, a["observations"]), "unresolved_control")

    def test_comparison_reports_missing_records_and_changes(self):
        a, s = fixture(); b = deepcopy(a); b["reviewer"] = "ai-b"
        b["observations"].pop()
        b["observations"][0]["measurement"]["estimate"] = "31"
        result = compare(a, b, s)
        self.assertEqual(result["paired_table_cells"], 1)
        self.assertEqual(len(result["a_only"]), 1)
        self.assertIn("measurement", result["disagreements"][0]["fields"])

    def test_demo_requires_audit_and_retains_citation_coordinates(self):
        a, s = fixture()
        curated = {"variants": [dict(gene="GRIN2B", reported_protein="p.Ser541Arg", variant_id="GRIN2B:p.Ser541Arg", cohort_tier="core_likely_reduced")]}
        ledger = {"documents": [dict(document_id=d["document_id"], title="Synthetic source", url="https://example.invalid") for d in a["coverage"]]}
        with self.assertRaisesRegex(ValueError, "source-audited"): build(a, s, curated, ledger)
        a["review_type"] = "source_audited_ai_reference"
        result = build(a, s, curated, ledger)
        self.assertEqual(result["members"][0]["tier"], "unresolved_control")
        self.assertTrue(result["members"][0]["tier_changed"])
        self.assertNotIn("quote", result["observations"][0]["evidence"][0])
        self.assertIn("locator", result["observations"][0]["evidence"][0])


if __name__ == "__main__": unittest.main()

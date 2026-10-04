"""Validate interval-aware cluster annotations and compare independent drafts."""
from collections import Counter
from decimal import Decimal
import re

from .contracts import digest, keys, numeric, require, span_shape, valid_span

FOCUS = {
    "GRIN2A": {"p.Gly483Arg", "p.Ala716Thr", "p.Asp731Asn"},
    "GRIN2B": {"p.Glu413Gly", "p.Ser541Arg", "p.Pro553Thr", "p.Cys461Phe", "p.Ser541Gly", "p.Ala639Val", "p.Arg540His"},
}
MEASURE_KEYS = {"raw", "estimate", "relation", "unit", "uncertainty_type", "uncertainty_value", "ci_lower", "ci_upper", "n", "n_unit", "qualitative"}
OBS_KEYS = {"id", "document_id", "gene", "protein", "table_id", "row", "column", "endpoint", "assay", "measurement_type", "sequence_context", "conditions", "measurement", "comparator", "evidence"}
CATEGORIES = {"Likely LoF", "Possible LoF", "Likely GoF", "Possible GoF", "GoF", "LoF", "No effect", "Indeterminant", None}


def text(value, name, nullable=False):
    require(nullable and value is None or isinstance(value, str) and bool(value.strip()), f"Invalid {name}")


def measure(m):
    keys(m, MEASURE_KEYS, "measurement")
    text(m["raw"], "raw measurement")
    require(m["relation"] in {"eq", "lt", "le", "gt", "ge", "range", "qualitative", "not_reported"}, "Invalid relation")
    for key in ("estimate", "uncertainty_value", "ci_lower", "ci_upper"):
        numeric(m[key], key)
    for key in ("unit", "n_unit", "qualitative"):
        text(m[key], key, nullable=True)
    require(m["uncertainty_type"] in {"SEM", "SD", "95%CI", "unspecified", None}, "Invalid uncertainty type")
    require(m["n"] is None or type(m["n"]) is int and m["n"] > 0, "Invalid sample size")
    if m["relation"] in {"eq", "lt", "le", "gt", "ge"}:
        require(m["estimate"] is not None, "Quantitative measurement lacks estimate/bound")
    if m["relation"] in {"qualitative", "not_reported"}:
        require(m["estimate"] is None, "Missing/qualitative value cannot have an estimate")
    if m["relation"] == "qualitative":
        text(m["qualitative"], "qualitative value")
    if m["ci_lower"] is not None and m["ci_upper"] is not None:
        require(Decimal(m["ci_lower"]) <= Decimal(m["ci_upper"]), "Reversed interval")
    require((m["ci_lower"] is None) == (m["ci_upper"] is None), "One-sided interval requires explicit censoring instead")


def validate(data, sources):
    keys(data, {"schema_version", "reviewer", "review_type", "expert_reviewed", "sources_sha256", "observations", "claims", "coverage", "issues"}, "annotations")
    require(data["schema_version"] == "grin-cluster-annotations-v2", "Unknown cluster annotation schema")
    require(data["review_type"] in {"independent_ai_draft", "source_audited_ai_reference"}, "Invalid review type")
    require(data["expert_reviewed"] is False, "These AI annotations cannot assert expert review")
    text(data["reviewer"], "reviewer")
    require(data["sources_sha256"] == digest(sources), "Source checksum mismatch")
    units = {u["unit_id"]: u for u in sources["units"]}
    docs = {u["document_id"] for u in units.values()}
    def identity(row):
        require(row["document_id"] in docs, "Unknown source document")
        require(row["gene"] in FOCUS and row["protein"] in FOCUS[row["gene"]], "Variant outside declared cluster scope")
    def evidence(spans, doc, required=True):
        require(isinstance(spans, list) and (spans or not required), "Evidence list required")
        for span in spans:
            span_shape(span)
            require(valid_span(span, doc, units), "Invalid source evidence span")
    ids = set()
    anchors = set()
    for row in data["observations"]:
        keys(row, OBS_KEYS, "observation")
        identity(row)
        text(row["id"], "observation id")
        require(row["id"] not in ids, "Duplicate observation ID")
        ids.add(row["id"])
        require(re.fullmatch(r"[a-z0-9_]+", row["endpoint"]), "Endpoint must be snake_case")
        text(row["assay"], "assay")
        text(row["sequence_context"], "sequence context", nullable=True)
        require(row["measurement_type"] in {"measured", "author_calculated", "secondary_summary"}, "Invalid measurement type")
        keys(row["conditions"], {"receptor", "system", "protocol"}, "conditions")
        for key in ("receptor", "system"):
            text(row["conditions"][key], key, nullable=True)
        require(isinstance(row["conditions"]["protocol"], dict), "Protocol must have named conditions")
        for k, v in row["conditions"]["protocol"].items():
            text(k, "protocol key")
            text(v, "protocol value", nullable=True)
        if row["table_id"] is not None:
            text(row["table_id"], "table id")
            require(all(type(row[k]) is int and row[k] > 0 for k in ("row", "column")), "Table coordinates required")
            anchor = (row["document_id"], row["table_id"], row["row"], row["column"], row["gene"], row["protein"])
            require(anchor not in anchors, "Duplicate variant measurement cell")
            anchors.add(anchor)
        else:
            require(row["row"] is None and row["column"] is None, "Prose observations cannot have table coordinates")
        measure(row["measurement"])
        keys(row["comparator"], {"label", "measurement", "evidence"}, "comparator")
        text(row["comparator"]["label"], "comparator label", nullable=True)
        if row["comparator"]["measurement"] is not None:
            measure(row["comparator"]["measurement"])
            evidence(row["comparator"]["evidence"], row["document_id"])
        else:
            evidence(row["comparator"]["evidence"], row["document_id"], required=False)
        evidence(row["evidence"], row["document_id"])
    claim_ids = set()
    for row in data["claims"]:
        keys(row, {"id", "document_id", "gene", "protein", "predicate", "statement", "category", "evidence_type", "evidence"}, "claim")
        identity(row)
        text(row["id"], "claim id")
        require(row["id"] not in claim_ids, "Duplicate claim id")
        claim_ids.add(row["id"])
        require(row["predicate"] in {"author_functional_classification", "reported_functional_effect", "identity_conflict"}, "Invalid claim predicate")
        require(row["category"] in CATEGORIES, "Invalid author category")
        require(row["evidence_type"] in {"primary_report", "secondary_summary"}, "Invalid evidence type")
        text(row["statement"], "claim statement")
        evidence(row["evidence"], row["document_id"])
    require(isinstance(data["coverage"], list) and len(data["coverage"]) == len(docs)
            and {d["document_id"] for d in data["coverage"]} == docs, "Coverage must include each source document once")
    for row in data["coverage"]:
        keys(row, {"document_id", "status", "scope", "omissions", "reviewed_tables"}, "coverage")
        text(row["status"], "coverage status")
        text(row["scope"], "coverage scope")
        require(isinstance(row["omissions"], list) and isinstance(row["reviewed_tables"], list), "Coverage lists required")
    for row in data["issues"]:
        keys(row, {"document_id", "gene", "protein", "description", "evidence"}, "issue")
        require(row["document_id"] in docs, "Unknown issue document")
        text(row["description"], "issue description")
        evidence(row["evidence"], row["document_id"], required=False)
    return {"documents": len(docs), "observations": len(ids), "claims": len(claim_ids),
            "by_document": dict(Counter(r["document_id"] for r in data["observations"]))}


def anchor(row):
    return (row["document_id"], row["table_id"], row["row"], row["column"], row["gene"], row["protein"])


def compare(a, b, sources):
    validate(a, sources)
    validate(b, sources)
    require(a["reviewer"] != b["reviewer"], "Distinct reviewers required")
    aa, bb = ({anchor(r): r for r in d["observations"] if r["table_id"] is not None} for d in (a, b))
    differences = []
    fields = ("endpoint", "assay", "measurement_type", "sequence_context", "conditions", "measurement", "comparator")
    counts = Counter()
    for key in sorted(aa.keys() & bb.keys()):
        differing = {}
        for field in fields:
            av, bv = aa[key][field], bb[key][field]
            # Compare comparator content separately from alternative valid evidence selections.
            if field == "comparator":
                av, bv = ({k: v for k, v in obj.items() if k != "evidence"} for obj in (av, bv))
            if av != bv:
                differing[field] = {"a": av, "b": bv}
            else:
                counts[field] += 1
        if differing:
            differences.append({"anchor": list(key), "a_id": aa[key]["id"], "b_id": bb[key]["id"], "fields": differing})
    return {"schema_version": "grin-cluster-agreement-v2", "reviewers": [a["reviewer"], b["reviewer"]],
            "hashes": {"a": digest(a), "b": digest(b), "sources": digest(sources)},
            "paired_table_cells": len(aa.keys() & bb.keys()), "field_agreement": dict(counts),
            "a_only": [list(k) for k in sorted(aa.keys() - bb.keys())],
            "b_only": [list(k) for k in sorted(bb.keys() - aa.keys())],
            "disagreements": differences, "prose_and_claims": "Require source-based adjudication; not automatically paired",
            "scientifically_validated": False}

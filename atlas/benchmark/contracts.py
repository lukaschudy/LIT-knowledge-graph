"""Versioned benchmark contracts, split checks and source snapshot validation."""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import re

VERSION = "grin-benchmark-v1"
SPLITS = {"development", "held_out"}
STATES = {"supports", "contradicts", "unresolved"}
FIELDS = (
    "gene", "variant", "sequence_context", "assay", "property", "measurement_type",
    "value", "unit", "comparator", "conditions", "uncertainty", "sample_size",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected),
            f"{where}: expected exactly {sorted(expected)}")


def string(value, where, nullable=False):
    require((nullable and value is None) or isinstance(value, str) and bool(value.strip()),
            f"{where}: nonempty string required")


def checksum(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def unique(rows, field, where):
    require(isinstance(rows, list), f"{where}: list required")
    ids = []
    for row in rows:
        require(isinstance(row, dict) and field in row, f"{where}: missing {field}")
        string(row[field], where + "." + field)
        ids.append(row[field])
    require(len(set(ids)) == len(ids), f"{where}: duplicate {field}")
    return {row[field]: row for row in rows}


def validate_manifest(manifest):
    keys(manifest, {"schema_version", "benchmark_id", "state", "synthetic", "scope", "documents"}, "manifest")
    require(manifest["schema_version"] == VERSION, "Unknown manifest version")
    require(manifest["state"] in {"draft", "frozen"}, "Invalid manifest state")
    require(type(manifest["synthetic"]) is bool, "synthetic must be a boolean")
    string(manifest["benchmark_id"], "benchmark_id")
    string(manifest["scope"], "scope")
    docs = unique(manifest["documents"], "document_id", "manifest documents")
    groups, snapshots = defaultdict(set), defaultdict(set)
    for doc in docs.values():
        keys(doc, {"document_id", "study_id", "split", "known_development", "grouping_reviewed",
                   "source_sha256", "strata"}, "manifest document")
        string(doc["study_id"], "study_id")
        require(doc["split"] in SPLITS, "Invalid split")
        require(type(doc["known_development"]) is bool and type(doc["grouping_reviewed"]) is bool,
                "Development exposure and grouping review must be boolean")
        require(not doc["known_development"] or doc["split"] == "development",
                "Known development material cannot enter held_out")
        require(isinstance(doc["strata"], list) and all(isinstance(s, str) and s.strip() for s in doc["strata"]),
                "strata must be a list of strings")
        require(doc["source_sha256"] is None or checksum(doc["source_sha256"]), "Invalid source checksum")
        if manifest["state"] == "frozen":
            require(doc["grouping_reviewed"] and checksum(doc["source_sha256"]),
                    "Frozen documents require reviewed study grouping and source snapshots")
        groups[doc["study_id"]].add(doc["split"])
        if doc["source_sha256"]:
            snapshots[doc["source_sha256"]].add(doc["split"])
    require(all(len(v) == 1 for v in groups.values()), "Study family crosses splits")
    require(all(len(v) == 1 for v in snapshots.values()), "Identical source snapshot crosses splits")
    return docs


def source_index(manifest, sources):
    docs = validate_manifest(manifest)
    keys(sources, {"schema_version", "units"}, "sources")
    require(sources["schema_version"] == VERSION, "Unknown source version")
    units = unique(sources["units"], "unit_id", "source units")
    grouped = defaultdict(list)
    for unit in units.values():
        keys(unit, {"unit_id", "document_id", "kind", "locator", "text"}, "source unit")
        require(unit["document_id"] in docs, "Source document outside manifest")
        require(unit["kind"] in {"paragraph", "table_cell", "caption", "footnote", "methods"}, "Invalid source kind")
        string(unit["locator"], "source locator")
        string(unit["text"], "source text")
        grouped[unit["document_id"]].append(unit)
    for doc_id, rows in grouped.items():
        require(docs[doc_id]["source_sha256"] == digest(sorted(rows, key=lambda r: r["unit_id"])),
                f"Source snapshot mismatch: {doc_id}")
    return units


def span_shape(span):
    keys(span, {"unit_id", "start", "end", "quote"}, "evidence span")
    string(span["unit_id"], "span unit")
    require(type(span["start"]) is int and type(span["end"]) is int, "Integer character offsets required")
    string(span["quote"], "span quote")


def valid_span(span, document_id, units):
    unit = units.get(span["unit_id"])
    return bool(unit and unit["document_id"] == document_id
                and 0 <= span["start"] < span["end"] <= len(unit["text"])
                and unit["text"][span["start"]:span["end"]] == span["quote"])


def spans(value, where, nonempty=True):
    require(isinstance(value, list) and (bool(value) or not nonempty), f"{where}: spans required")
    for span in value:
        span_shape(span)


def numeric(value, where, nullable=True):
    # Decimal strings retain source precision and avoid JSON binary-float rounding.
    require((nullable and value is None) or isinstance(value, str)
            and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value) is not None,
            f"{where}: decimal string or null required")


def observation(row, reference=False):
    keys(row, {"id", *FIELDS, "evidence_sets" if reference else "evidence"}, "observation")
    for field in ("id", "gene", "variant", "assay", "property"):
        string(row[field], field)
    for field in ("sequence_context", "unit"):
        string(row[field], field, nullable=True)
    require(row["measurement_type"] in {"measured", "author_calculated"}, "Invalid measurement type")
    numeric(row["value"], "value")
    keys(row["comparator"], {"label", "value", "unit"}, "comparator")
    string(row["comparator"]["label"], "comparator label", nullable=True)
    string(row["comparator"]["unit"], "comparator unit", nullable=True)
    numeric(row["comparator"]["value"], "comparator value")
    keys(row["conditions"], {"receptor", "system", "protocol"}, "conditions")
    for value in row["conditions"].values():
        string(value, "condition", nullable=True)
    keys(row["uncertainty"], {"type", "value"}, "uncertainty")
    string(row["uncertainty"]["type"], "uncertainty type", nullable=True)
    numeric(row["uncertainty"]["value"], "uncertainty value")
    keys(row["sample_size"], {"value", "unit"}, "sample size")
    n = row["sample_size"]["value"]
    require(n is None or type(n) is int and n > 0, "Sample size must be a positive integer or null")
    string(row["sample_size"]["unit"], "sample unit", nullable=True)
    if reference:
        require(isinstance(row["evidence_sets"], list) and bool(row["evidence_sets"]), "Reference evidence required")
        for bundle in row["evidence_sets"]:
            spans(bundle, "reference evidence bundle")
    else:
        spans(row["evidence"], "prediction evidence", nonempty=False)


def validate_reference(manifest, sources, reference):
    docs = validate_manifest(manifest)
    units = source_index(manifest, sources)
    keys(reference, {"schema_version", "manifest_sha256", "split", "documents"}, "reference")
    require(reference["schema_version"] == VERSION and reference["manifest_sha256"] == digest(manifest),
            "Reference does not match manifest")
    require(reference["split"] in SPLITS, "Invalid reference split")
    selected = unique(reference["documents"], "document_id", "reference documents")
    require(bool(selected) and set(selected) == {k for k, d in docs.items() if d["split"] == reference["split"]},
            "Reference must cover every document in selected split")
    for doc_id, doc in selected.items():
        keys(doc, {"document_id", "coverage", "review", "observations", "decisions"}, "reference document")
        require(any(u["document_id"] == doc_id for u in units.values()), "Missing source snapshot")
        require(doc["coverage"] in {"partial", "complete"}, "Invalid annotation coverage")
        keys(doc["review"], {"annotators", "adjudicator", "expert_reviewed"}, "review")
        annotators = doc["review"]["annotators"]
        require(isinstance(annotators, list) and all(isinstance(a, str) and a.strip() for a in annotators)
                and len(annotators) == len(set(annotators)), "Annotators must be distinct identifiers")
        string(doc["review"]["adjudicator"], "adjudicator", nullable=True)
        require(type(doc["review"]["expert_reviewed"]) is bool, "Expert review must be boolean")
        obs = unique(doc["observations"], "id", "reference observations")
        for row in obs.values():
            observation(row, reference=True)
            for bundle in row["evidence_sets"]:
                require(all(valid_span(s, doc_id, units) for s in bundle), "Ungrounded reference span")
        decisions = unique(doc["decisions"], "case_id", "reference decisions")
        for row in decisions.values():
            keys(row, {"case_id", "question", "label", "observation_ids", "author_interpretation"}, "reference decision")
            string(row["question"], "decision question")
            string(row["author_interpretation"], "author interpretation", nullable=True)
            require(row["label"] in STATES, "Invalid reference decision")
            require(isinstance(row["observation_ids"], list)
                    and len(row["observation_ids"]) == len(set(row["observation_ids"]))
                    and set(row["observation_ids"]) <= set(obs), "Unknown or duplicate reference observation")
            require(row["label"] == "unresolved" or bool(row["observation_ids"]), "Decisive reference requires observations")
    return docs, units, selected


def validate_predictions(manifest, reference, predictions):
    keys(predictions, {"schema_version", "manifest_sha256", "split", "run", "documents"}, "predictions")
    require(predictions["schema_version"] == VERSION and predictions["manifest_sha256"] == digest(manifest),
            "Predictions do not match manifest")
    require(predictions["split"] == reference["split"], "Run split mismatch")
    run = predictions["run"]
    keys(run, {"id", "mode", "code_commit", "prompt_sha256", "configuration", "configuration_sha256",
               "input_tokens", "output_tokens", "cost_usd", "elapsed_seconds"}, "run")
    string(run["id"], "run id")
    require(run["mode"] in {"extraction", "end_to_end"}, "Unsupported benchmark mode")
    require(isinstance(run["code_commit"], str) and re.fullmatch(r"[0-9a-f]{40}", run["code_commit"]), "Commit SHA required")
    require(checksum(run["prompt_sha256"]), "Prompt checksum required")
    require(isinstance(run["configuration"], dict) and bool(run["configuration"])
            and run["configuration_sha256"] == digest(run["configuration"]), "Configuration checksum mismatch")
    for key in ("input_tokens", "output_tokens"):
        require(run[key] is None or type(run[key]) is int and run[key] >= 0, f"Invalid {key}")
    for key in ("cost_usd", "elapsed_seconds"):
        numeric(run[key], key)
        require(run[key] is None or float(run[key]) >= 0, f"Negative {key}")
    documents = unique(predictions["documents"], "document_id", "prediction documents")
    selected = {d["document_id"]: d for d in reference["documents"]}
    require(set(documents) <= set(selected), "Prediction document outside evaluation split")
    for doc_id, doc in documents.items():
        keys(doc, {"document_id", "status", "observations", "decisions"}, "prediction document")
        require(doc["status"] in {"complete", "failed"}, "Invalid execution status")
        obs = unique(doc["observations"], "id", "prediction observations")
        for row in obs.values():
            observation(row)
        for row in unique(doc["decisions"], "case_id", "prediction decisions").values():
            keys(row, {"case_id", "label", "observation_ids"}, "prediction decision")
            require(row["case_id"] in {d["case_id"] for d in selected[doc_id]["decisions"]}, "Unknown decision case")
            require(row["label"] in STATES | {"abstain"}, "Invalid prediction decision")
            require(isinstance(row["observation_ids"], list)
                    and len(row["observation_ids"]) == len(set(row["observation_ids"]))
                    and set(row["observation_ids"]) <= set(obs), "Unknown or duplicate prediction observation")
    return documents

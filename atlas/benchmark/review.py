"""Prepare source-only annotation packets and compare independent AI drafts.

Agreement is not accuracy. No automatic adjudication or expert-review promotion.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

from .__main__ import read
from .contracts import FIELDS, VERSION, digest, require, source_index, validate_reference
from .scoring import equal_field
from .snapshots import write_json


def packet(snapshot_dir, scope, output):
    snapshot_dir, output = Path(snapshot_dir), Path(output)
    require(not output.exists(), "Packet directory already exists")
    manifest = read(snapshot_dir / "manifest.json")
    sources = read(snapshot_dir / "sources.json")
    ledger = read(snapshot_dir / "source-ledger.json")
    source_index(manifest, sources)
    selected = set(scope["document_ids"])
    require(selected and selected <= {d["document_id"] for d in manifest["documents"]}, "Unknown scope documents")
    manifest["documents"] = [d for d in manifest["documents"] if d["document_id"] in selected]
    require(all(d["split"] == "development" for d in manifest["documents"]), "This pilot builder is development-only")
    manifest["benchmark_id"] = scope["scope_id"]
    manifest["scope"] = scope["description"]
    sources["units"] = [u for u in sources["units"] if u["document_id"] in selected]
    ledger["documents"] = [d for d in ledger["documents"] if d["document_id"] in selected]
    reference = {"schema_version": VERSION, "manifest_sha256": digest(manifest), "split": "development",
                 "documents": [{"document_id": d["document_id"], "coverage": "partial",
                                "review": {"annotators": [], "adjudicator": None, "expert_reviewed": False},
                                "observations": [], "decisions": []} for d in manifest["documents"]]}
    validate_reference(manifest, sources, reference)
    require(set(c["document_id"] for c in scope["cells"]) <= selected, "Scope cells outside packet")
    units = {u["unit_id"] for u in sources["units"]}
    require(len({c["unit_id"] for c in scope["cells"]}) == len(scope["cells"])
            and all(c["unit_id"] in units for c in scope["cells"]), "Invalid or duplicate scope cells")
    output.mkdir(parents=True)
    for name, value in (("manifest.json", manifest), ("sources.json", sources), ("source-ledger.json", ledger),
                        ("reference-template.json", reference), ("scope.json", scope)):
        write_json(output / name, value)
    shutil.copyfile(Path(__file__).with_name("contracts.py"), output / "contract.py")
    return {"manifest_sha256": digest(manifest), "sources_sha256": digest(sources), "scope_sha256": digest(scope)}


def coverage_index(scope, reference, coverage, units):
    require(isinstance(coverage, dict) and isinstance(coverage.get("cells"), list), "Coverage cells required")
    expected = {c["unit_id"]: c for c in scope["cells"]}
    rows = coverage["cells"]
    require(len(rows) == len(expected) and {c.get("unit_id") for c in rows} == set(expected),
            "Coverage must account for every scope cell exactly once")
    documents = {d["document_id"]: d for d in reference["documents"]}
    all_observations = {(doc_id, o["id"]): o for doc_id, d in documents.items() for o in d["observations"]}
    used = set()
    result = {}
    for row in rows:
        uid = row["unit_id"]
        require(row.get("state") in {"annotated", "not_reported", "unsupported"}, "Invalid cell coverage state")
        doc_id = expected[uid]["document_id"]
        require(units[uid]["document_id"] == doc_id, "Coverage document mismatch")
        if row["state"] == "annotated":
            key = (doc_id, row.get("observation_id"))
            require(key in all_observations and key not in used, "Observation missing or reused across cells")
            obs = all_observations[key]
            require(any(any(s["unit_id"] == uid for s in evidence) for evidence in obs["evidence_sets"]),
                    "Annotation must cite its measurement cell")
            used.add(key)
        else:
            require(row.get("observation_id") is None, "Unannotated cell has an observation ID")
        result[uid] = row
    require(used == set(all_observations), "Observations outside declared coverage")
    return result


def compare(manifest, sources, scope, a, b, coverage_a, coverage_b):
    _, units, adocs = validate_reference(manifest, sources, a)
    _, _, bdocs = validate_reference(manifest, sources, b)
    require(a["split"] == b["split"], "Reviewer splits differ")
    require(manifest["benchmark_id"] == scope["scope_id"] and manifest["scope"] == scope["description"], "Scope does not match manifest")
    require(bool(scope["cells"]) and len({c["unit_id"] for c in scope["cells"]}) == len(scope["cells"]), "Scope cells must be nonempty and unique")
    require(set(scope["document_ids"]) == set(adocs), "Scope document IDs do not match annotations")
    reviewer_sets = []
    for documents in (adocs, bdocs):
        ids = {r for d in documents.values() for r in d["review"]["annotators"]}
        require(len(ids) == 1 and all(len(d["review"]["annotators"]) == 1 for d in documents.values()),
                "Each independent submission must identify exactly one annotator")
        require(all(not d["review"]["expert_reviewed"] and d["review"]["adjudicator"] is None for d in documents.values()),
                "AI comparison requires unadjudicated, non-expert drafts")
        require(all(not d["decisions"] for d in documents.values()), "This comparison is extraction-only")
        reviewer_sets.append(ids)
    require(not reviewer_sets[0] & reviewer_sets[1], "Submissions claim the same reviewer")
    ca = coverage_index(scope, a, coverage_a, units)
    cb = coverage_index(scope, b, coverage_b, units)
    obs_a = {(d, o["id"]): o for d, doc in adocs.items() for o in doc["observations"]}
    obs_b = {(d, o["id"]): o for d, doc in bdocs.items() for o in doc["observations"]}
    paired = counts_agree = exact = 0
    field_counts = Counter()
    disagreements, different_evidence = [], []
    for cell in scope["cells"]:
        uid, doc_id = cell["unit_id"], cell["document_id"]
        ac, bc = ca[uid], cb[uid]
        counts_agree += ac["state"] == bc["state"]
        if ac["state"] != bc["state"]:
            disagreements.append({"unit_id": uid, "document_id": doc_id, "type": "coverage",
                                  "a": ac["state"], "b": bc["state"]})
        if ac["state"] != "annotated" or bc["state"] != "annotated":
            continue
        ao, bo = obs_a[(doc_id, ac["observation_id"])], obs_b[(doc_id, bc["observation_id"])]
        paired += 1
        differing = []
        for f in FIELDS:
            same = equal_field(ao, bo, f)
            field_counts[f] += same
            if not same:
                differing.append(f)
        exact += not differing
        if differing:
            disagreements.append({"unit_id": uid, "document_id": doc_id, "type": "fields",
                                  "a_observation_id": ao["id"], "b_observation_id": bo["id"],
                                  "fields": {f: {"a": ao[f], "b": bo[f]} for f in differing}})
        def spans(row):
            return {tuple((s[k] for k in ("unit_id", "start", "end"))) for bundle in row["evidence_sets"] for s in bundle}
        if spans(ao) != spans(bo):
            different_evidence.append({"unit_id": uid, "a_observation_id": ao["id"], "b_observation_id": bo["id"]})
    return {"schema_version": "grin-ai-annotation-agreement-v1", "scope_id": scope["scope_id"],
            "provenance": "Two separate-context AI annotation drafts; not human or expert validation",
            "hashes": {"manifest": digest(manifest), "sources": digest(sources), "scope": digest(scope),
                       "annotation_a": digest(a), "annotation_b": digest(b), "coverage_a": digest(coverage_a), "coverage_b": digest(coverage_b)},
            "reviewers": [sorted(ids)[0] for ids in reviewer_sets],
            "scope_cells": len(ca), "coverage_states": {"a": dict(Counter(c["state"] for c in ca.values())),
                                                         "b": dict(Counter(c["state"] for c in cb.values()))},
            "coverage_state_agreement": {"agree": counts_agree, "total": len(ca)},
            "paired_observations": paired, "exact_observation_agreement": {"agree": exact, "total": paired},
            "field_agreement": {f: {"agree": field_counts[f], "total": paired} for f in FIELDS},
            "disagreements": disagreements, "different_evidence_selections": different_evidence,
            "decisions": "Not compared; extraction-only pilot", "adjudication_status": "pending",
            "scientifically_validated": False,
            "limitations": ["Shared model priors and annotation rules can produce correlated errors.",
                            "Exact protocol wording disagreements can be representational rather than scientific.",
                            "Cell agreement and valid source quotes do not establish entailment or completeness beyond this scope."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("packet")
    for name in ("snapshot", "scope", "output"):
        prepare.add_argument("--" + name, type=Path, required=True)
    compare_parser = sub.add_parser("compare")
    for name in ("manifest", "sources", "scope", "a", "b", "coverage-a", "coverage-b", "output"):
        compare_parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.command == "packet":
        print(json.dumps(packet(args.snapshot, read(args.scope), args.output)))
    else:
        report = compare(*(read(getattr(args, name)) for name in ("manifest", "sources", "scope", "a", "b", "coverage_a", "coverage_b")))
        write_json(args.output, report)
        print(json.dumps({"scope_cells": report["scope_cells"], "paired_observations": report["paired_observations"],
                          "exact_observation_agreement": report["exact_observation_agreement"],
                          "field_agreement": report["field_agreement"], "scientifically_validated": False}))


if __name__ == "__main__":
    main()

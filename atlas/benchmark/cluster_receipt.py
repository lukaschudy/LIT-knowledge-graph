"""Verify a completed seven-paper annotation run and write a quotation-free receipt."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from .cluster_annotations import anchor, audit_table_cells, compare, validate
from .contracts import digest, require, span_shape, valid_span
from ..cluster_demo import build


def read(path):
    return json.loads(path.read_text())


def receipt(packet, bundle_path, curated_path):
    sources = read(packet / "reviewer-a/sources.json")
    ledger = read(packet / "reviewer-a/source-ledger.json")
    a, b = (read(packet / f"reviewer-{r}/annotations.json") for r in ("a", "b"))
    reference = read(packet / "adjudicator/adjudicated-reference.json")
    original_agreement = read(packet / "agreement.json")
    agreement = compare(a, b, sources)
    require(agreement == original_agreement, "Reviewer drafts changed after initial comparison")
    packet_files = ("sources.json", "source-ledger.json", "manifest.json", "CONTRACT.md",
                    "source_contract.py", "cluster_contract.py", "myers-supplement.pdf")
    for name in packet_files:
        contents = [(packet / role / name).read_bytes() for role in ("reviewer-a", "reviewer-b", "adjudicator")]
        require(contents[0] == contents[1] == contents[2], f"Source packet mismatch: {name}")
    validations = {name: {**validate(data, sources), **audit_table_cells(data, ledger)}
                   for name, data in (("a", a), ("b", b), ("reference", reference))}
    cells = [{anchor(o) for o in d["observations"] if o["table_id"]} for d in (a, b, reference)]
    require(cells[0] == cells[1] == cells[2], "Main-table coverage changed during adjudication")
    bundle = read(bundle_path)
    require(bundle == build(reference, sources, read(curated_path), ledger), "Committed bundle differs from reproducible build")
    units = {u["unit_id"]: u for u in sources["units"]}
    def check_spans(obj):
        count = 0
        if isinstance(obj, dict):
            if {"unit_id", "start", "end", "quote"} <= obj.keys():
                span = {k: obj[k] for k in ("unit_id", "start", "end", "quote")}
                span_shape(span)
                require(span["unit_id"] in units and valid_span(span, units[span["unit_id"]]["document_id"], units), "Invalid audit span")
                return 1
            return sum(check_spans(v) for v in obj.values())
        if isinstance(obj, list):
            return sum(check_spans(v) for v in obj)
        return count
    audit_log = read(packet / "adjudicator/audit-log.json")
    span_count = sum(check_spans(obj) for obj in (a, b, reference, audit_log))
    paths = [packet / "agreement.json", bundle_path]
    for role in ("reviewer-a", "reviewer-b", "adjudicator"):
        paths.extend(p for p in (packet / role).iterdir() if p.suffix in {".json", ".md", ".py", ".pdf"})
    files = {str(p): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
             for p in sorted(paths)}
    return {
        "schema_version": "grin-cluster-annotation-receipt-v2",
        "scope": "Ten selected protein variants across seven development papers; not every GRIN variant or all harvested papers",
        "provenance": "Two fresh-context AI annotators and one separate source-based AI adjudicator",
        "isolation": {"fork_turns": "none", "same_source_packets": True,
                      "access_boundary": "Explicit agent instructions, not an OS security sandbox",
                      "prior_graph_supplied": False},
        "model_configuration": {"override": None, "inherited_model": True, "exact_deployment_id": None,
                                "token_usage": None, "cost_usd": None},
        "validation": {"drafts_unchanged": True, "table_coverage_preserved": True,
                       "exact_source_span_occurrences": span_count, "bundle_rebuild_equal": True,
                       "annotations": validations},
        "initial_agreement": {k: v for k, v in agreement.items() if k != "disagreements"},
        "reference": {"sha256": digest(reference), "sources_sha256": digest(sources),
                      "measurement_types": dict(Counter(o["measurement_type"] for o in reference["observations"])),
                      "relations": dict(Counter(o["measurement"]["relation"] for o in reference["observations"])),
                      "issues": len(reference["issues"]), "coverage": reference["coverage"]},
        "cluster": bundle["counts"], "files": files,
        "expert_reviewed": False, "scientifically_validated": False, "held_out_model_accuracy_measured": False,
        "limitations": bundle["limitations"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=Path("data/processed/benchmarks/grin-cluster-annotation-v2"))
    parser.add_argument("--bundle", type=Path, default=Path("data/curated/grin_cluster_demo_v2.json"))
    parser.add_argument("--curated", type=Path, default=Path("data/curated/grin_functional_evidence.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = receipt(args.packet, args.bundle, args.curated)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["validation"]))


if __name__ == "__main__":
    main()

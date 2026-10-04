"""Small, declared GRIN retrieval regression set; not a held-out scientific benchmark."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from .topk import checked_bundle, client_from_settings, graph_connections, save_json, search, settings, DEFAULT_REGION

CASES = [
    {"id": "g483r", "query": "GRIN2A G483R glutamate potency and reduced receptor function", "protein": "G483R", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "a716t", "query": "GRIN2A p.Ala716Thr reduced charge transfer", "protein": "A716T", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "d731n", "query": "GRIN2A D731N small current amplitude", "protein": "D731N", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "e413g", "query": "GRIN2B E413G loss of function", "protein": "E413G", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "s541r", "query": "GRIN2B S541R reduced NMDA receptor function", "protein": "S541R", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "p553t", "query": "GRIN2B P553T impaired receptor function", "protein": "P553T", "effect": "loss_of_function", "tier": "core_likely_reduced"},
    {"id": "s541g_control", "query": "GRIN2B S541G functional classification", "protein": "S541G", "effect": "gain_of_function", "tier": "opposing_control"},
    {"id": "a639v_control", "query": "GRIN2B A639V functional classification", "protein": "A639V", "effect": "gain_of_function", "tier": "opposing_control"},
    {"id": "c461f_provisional", "query": "GRIN2B C461F possible loss of function uncertainty", "protein": "C461F", "effect": "loss_of_function", "tier": "provisional_possible_reduced"},
    {"id": "r540h_unresolved", "query": "GRIN2B R540H indeterminate function", "protein": "R540H", "effect": "unknown", "tier": "unresolved_control"},
]


def evaluate(client, collection, snapshot, bundle, *, lsn=None, progress=None):
    runs = []
    for mode in ("keyword", "semantic", "hybrid"):
        for case in CASES:
            result = search(client, collection, case["query"], snapshot, mode=mode, k=5,
                            kind="curated_evidence", lsn=lsn)
            hits = result["hits"]
            ranks = [i for i, h in enumerate(hits, 1)
                     if case["protein"] in h["proteins"] and h["effect"] == case["effect"]
                     and h["cohort_tier"] == case["tier"]]
            identity_ok = bool(hits) and all(case["protein"] in h["proteins"] for h in hits)
            citations_ok = all(h.get("url") and h.get("locator") and h.get("source_id") for h in hits)
            runs.append({"case": case["id"], "mode": mode, "query": case["query"],
                         "hit_at_5": bool(ranks), "reciprocal_rank": 1 / ranks[0] if ranks else 0,
                         "exact_variant_filter_pass": identity_ok, "citations_pass": citations_ok,
                         "latency_ms": result["latency_ms"], "evidence_ids": [h["evidence_id"] for h in hits]})
        if progress:
            progress({"mode": mode, "finished_cases": len(CASES)})
    summaries = {}
    for mode in ("keyword", "semantic", "hybrid"):
        rows = [r for r in runs if r["mode"] == mode]
        summaries[mode] = {"cases": len(rows), "hit_at_5": sum(r["hit_at_5"] for r in rows) / len(rows),
                           "mrr_at_5": statistics.mean(r["reciprocal_rank"] for r in rows),
                           "median_latency_ms": statistics.median(r["latency_ms"] for r in rows),
                           "identity_and_citations_pass": all(r["exact_variant_filter_pass"] and r["citations_pass"] for r in rows)}
    # Uncurated discovery channel must not create graph edges.
    discovery = search(client, collection, "GRIN2B receptor trafficking surface expression", snapshot,
                       kind="article_text", k=5, lsn=lsn)
    connections = graph_connections(discovery["hits"], bundle)
    discovery_ok = bool(discovery["hits"]) and not connections and all(h["effect"] == "unknown" for h in discovery["hits"])
    return {"evaluated_at": datetime.now(timezone.utc).isoformat(), "snapshot_id": snapshot,
            "collection": collection, "benchmark_type": "development regression; known curated cases, not held-out",
            "summaries": summaries, "runs": runs, "discovery_does_not_create_claims": discovery_ok,
            "discovery_source_ids": [h["source_id"] for h in discovery["hits"]],
            "passed": discovery_ok and all(r["hit_at_5"] and r["exact_variant_filter_pass"] and r["citations_pass"] for r in runs),
            "limitations": ["Exact gene/protein filters are intentionally enabled for variant queries.",
                            "Hit@5 requires at least one expected classified evidence card; it is not recall over all relevant literature.",
                            "No expert relevance judgments or held-out cross-disease benchmark yet.",
                            "Cold/warm cache and network effects are not controlled; latency is descriptive only."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=Path("data/curated/grin_atlas_bundle.json"))
    parser.add_argument("--output", type=Path, default=Path("data/curated/topk-grin-evaluation.json"))
    args = parser.parse_args()
    config = settings(args.env_file)
    state = json.loads(args.checkpoint.read_text())
    if state["status"] != "verified":
        raise ValueError("Complete read-back verification before evaluating the final corpus")
    if (config.get("TOPK_REGION") or DEFAULT_REGION) != state["region"]:
        raise ValueError("Configured region does not match checkpoint")
    result = evaluate(client_from_settings(config), state["collection"], state["snapshot_id"],
                      checked_bundle(args.bundle, state), lsn=state.get("last_lsn"),
                      progress=lambda r: print(json.dumps(r), flush=True))
    save_json(args.output, result)
    print(json.dumps({"passed": result["passed"], "summaries": result["summaries"]}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

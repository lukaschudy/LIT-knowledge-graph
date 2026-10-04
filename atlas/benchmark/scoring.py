"""Exact observation matching and study-cluster uncertainty, without an LLM judge."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
import random
import statistics

from .contracts import FIELDS, STATES, digest, valid_span, validate_predictions, validate_reference


def normalized(value, key=None):
    if isinstance(value, dict):
        return tuple((k, normalized(v, k)) for k, v in sorted(value.items()))
    if isinstance(value, str):
        if key == "value":
            return Decimal(value)
        return " ".join(value.split()).replace("μ", "µ")
    return value


def equal_field(a, b, field):
    return normalized(a[field], field) == normalized(b[field], field)


def covers(prediction, reference, document_id, units):
    spans = prediction["evidence"]
    if not spans or not all(valid_span(s, document_id, units) for s in spans):
        return False
    return any(all(any(p["unit_id"] == g["unit_id"] and p["start"] <= g["start"]
                       and p["end"] >= g["end"] for p in spans) for g in bundle)
               for bundle in reference["evidence_sets"])


def maximum_matching(predictions, references, accepts):
    """Maximum cardinality bipartite matching, so duplicates never earn extra TP."""
    edges = {p["id"]: [g["id"] for g in sorted(references, key=lambda r: r["id"]) if accepts(p, g)]
             for p in sorted(predictions, key=lambda r: r["id"])}
    owners = {}

    def visit(pid, seen):
        for gid in edges[pid]:
            if gid in seen:
                continue
            seen.add(gid)
            if gid not in owners or visit(owners[gid], seen):
                owners[gid] = pid
                return True
        return False

    for pid in edges:
        visit(pid, set())
    return {pid: gid for gid, pid in owners.items()}


def metrics(tp, fp, fn):
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def aggregate(rows):
    return metrics(*(sum(r[k] for r in rows) for k in ("tp", "fp", "fn")))


def bootstrap(rows, iterations=2000, seed=20261004):
    """Resample entire study families. Undefined draws are counted, not made zero."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["study_id"]].append(row)
    clusters = [aggregate(groups[k]) for k in sorted(groups)]
    if len(clusters) < 2:
        return {"method": "study-cluster percentile bootstrap", "study_count": len(clusters),
                "intervals": None, "reason": "At least two study families required"}
    rng = random.Random(seed)
    draws = {k: [] for k in ("precision", "recall", "f1")}
    for _ in range(iterations):
        result = aggregate([rng.choice(clusters) for _ in clusters])
        for key in draws:
            if result[key] is not None:
                draws[key].append(result[key])
    intervals = {}
    for key, values in draws.items():
        values.sort()
        intervals[key] = {"lower": values[int(.025 * (len(values) - 1))] if values else None,
                          "upper": values[int(.975 * (len(values) - 1))] if values else None,
                          "valid_draws": len(values), "undefined_draws": iterations - len(values)}
    return {"method": "study-cluster percentile bootstrap", "study_count": len(clusters),
            "iterations": iterations, "seed": seed, "intervals": intervals,
            "limitation": "Descriptive uncertainty; perfect small samples do not rule out rare errors."}


def score(manifest, sources, reference, predictions, *, iterations=2000, seed=20261004):
    if type(iterations) is not int or not 100 <= iterations <= 100000:
        raise ValueError("Bootstrap iterations must be between 100 and 100000")
    docs, units, gold_docs = validate_reference(manifest, sources, reference)
    predicted_docs = validate_predictions(manifest, reference, predictions)
    results, decision_rows = [], []
    field_correct = Counter()
    field_total = Counter()
    numeric_correct = numeric_total = valid_spans = span_total = 0
    for doc_id, gold in sorted(gold_docs.items()):
        pred_doc = predicted_docs.get(doc_id)
        predictions_for_doc = pred_doc["observations"] if pred_doc else []
        gold_obs = gold["observations"]
        matches = maximum_matching(predictions_for_doc, gold_obs,
            lambda p, g: all(equal_field(p, g, f) for f in FIELDS) and covers(p, g, doc_id, units))
        content_matches = maximum_matching(predictions_for_doc, gold_obs,
            lambda p, g: all(equal_field(p, g, f) for f in FIELDS))
        result = metrics(len(matches), len(predictions_for_doc) - len(matches), len(gold_obs) - len(matches))
        result.update(document_id=doc_id, study_id=docs[doc_id]["study_id"],
                      execution_status=pred_doc["status"] if pred_doc else "missing",
                      matches=[{"prediction_id": p, "reference_id": g} for p, g in sorted(matches.items())],
                      unmatched_predictions=[p["id"] for p in predictions_for_doc if p["id"] not in matches],
                      missed_references=[g["id"] for g in gold_obs if g["id"] not in matches.values()],
                      content_only_tp=len(content_matches))
        results.append(result)
        # Field diagnostics are deliberately restricted to unambiguous anchors.
        # Wrong identities remain unmatched and penalized in the primary metrics.
        anchor_fields = ("gene", "variant", "sequence_context", "assay", "property", "measurement_type", "conditions")
        p_groups, g_groups = defaultdict(list), defaultdict(list)
        for rows, groups in ((predictions_for_doc, p_groups), (gold_obs, g_groups)):
            for row in rows:
                groups[tuple(normalized(row[f], f) for f in anchor_fields)].append(row)
        for anchor in p_groups.keys() & g_groups.keys():
            if len(p_groups[anchor]) != 1 or len(g_groups[anchor]) != 1:
                continue
            p, g = p_groups[anchor][0], g_groups[anchor][0]
            for field in FIELDS:
                field_total[field] += 1
                field_correct[field] += equal_field(p, g, field)
            for pv, gv in ((p["value"], g["value"]), (p["comparator"]["value"], g["comparator"]["value"]),
                           (p["uncertainty"]["value"], g["uncertainty"]["value"])):
                if gv is not None:
                    numeric_total += 1
                    numeric_correct += normalized(pv, "value") == normalized(gv, "value")
        for row in predictions_for_doc:
            span_total += len(row["evidence"])
            valid_spans += sum(valid_span(s, doc_id, units) for s in row["evidence"])
        predicted_decisions = {d["case_id"]: d for d in pred_doc["decisions"]} if pred_doc else {}
        for g in gold["decisions"]:
            p = predicted_decisions.get(g["case_id"])
            label = p["label"] if p else "abstain"
            mapped = [matches.get(pid) for pid in p["observation_ids"]] if p else []
            grounded = bool(p and None not in mapped and set(mapped) == set(g["observation_ids"]))
            decision_rows.append({"document_id": doc_id, "case_id": g["case_id"], "expected": g["label"],
                                  "predicted": label, "label_correct": label == g["label"],
                                  "grounded_correct": label == g["label"] and grounded})
    total = aggregate(results)
    confusion = {g: {p: sum(r["expected"] == g and r["predicted"] == p for r in decision_rows)
                     for p in sorted(STATES | {"abstain"})} for g in sorted(STATES)}
    per_label = {label: metrics(sum(r["expected"] == label and r["predicted"] == label for r in decision_rows),
                                sum(r["expected"] != label and r["predicted"] == label for r in decision_rows),
                                sum(r["expected"] == label and r["predicted"] != label for r in decision_rows))
                 for label in sorted(STATES)}
    reasons = []
    if manifest["synthetic"]:
        reasons.append("Synthetic fixtures test machinery, not extraction quality")
    if manifest["state"] != "frozen":
        reasons.append("Manifest is not frozen")
    if reference["split"] != "held_out":
        reasons.append("Development data are not an independent test")
    if any(g["coverage"] != "complete" for g in gold_docs.values()):
        reasons.append("Reference annotation coverage is incomplete; recall is provisional")
    if any(len(g["review"]["annotators"]) < 2 or not g["review"]["adjudicator"]
           or not g["review"]["expert_reviewed"] for g in gold_docs.values()):
        reasons.append("Independent annotation, adjudication and expert review are not recorded for every document")
    if len({r["study_id"] for r in results}) < 20:
        reasons.append("Fewer than the proposed minimum of 20 independent study families")
    if any(r["execution_status"] != "complete" for r in results):
        reasons.append("Some document executions failed or are missing")
    n_decisions = len(decision_rows)
    cost = predictions["run"]["cost_usd"]
    return {"schema_version": "grin-benchmark-report-v1", "run_id": predictions["run"]["id"],
            "mode": predictions["run"]["mode"], "split": reference["split"], "synthetic": manifest["synthetic"],
            "input_hashes": {"manifest": digest(manifest), "sources": digest(sources),
                             "reference": digest(reference), "predictions": digest(predictions)},
            "observations": total,
            "macro_by_document": {k: {"mean": statistics.mean(values) if values else None,
                                      "defined_documents": len(values), "total_documents": len(results)}
                                  for k in ("precision", "recall", "f1")
                                  for values in [[r[k] for r in results if r[k] is not None]]},
            "uncertainty": bootstrap(results, iterations, seed), "documents": results,
            "field_diagnostics": {k: {"correct": field_correct[k], "total": field_total[k],
                                      "accuracy": field_correct[k] / field_total[k] if field_total[k] else None}
                                  for k in FIELDS},
            "numeric_diagnostics": {"correct": numeric_correct, "total": numeric_total,
                                    "accuracy": numeric_correct / numeric_total if numeric_total else None,
                                    "scope": "Non-null reference numbers on uniquely anchored pairs only; not end-to-end accuracy"},
            "source_spans": {"valid": valid_spans, "total": span_total,
                             "note": "Exact source text verification is not independent semantic entailment review"},
            "decisions": {"cases": n_decisions, "confusion": confusion, "per_label": per_label,
                          "coverage": sum(r["predicted"] != "abstain" for r in decision_rows) / n_decisions if n_decisions else None,
                          "label_accuracy": sum(r["label_correct"] for r in decision_rows) / n_decisions if n_decisions else None,
                          "grounded_accuracy": sum(r["grounded_correct"] for r in decision_rows) / n_decisions if n_decisions else None,
                          "cases_detail": decision_rows},
            "operations": {**{k: predictions["run"][k] for k in ("input_tokens", "output_tokens", "cost_usd", "elapsed_seconds")},
                           "cost_per_correct_observation_usd": str(Decimal(cost) / total["tp"]) if cost is not None and total["tp"] else None},
            "assessment": {"status": "inconclusive" if reasons else "requires_release_review",
                           "reasons": reasons, "scientifically_validated": False,
                           "note": "No automatic scientific release. Freeze acceptance policy and document test exposure externally."},
            "limitations": ["Metrics apply to this reference scope, not the entire harvested corpus.",
                            "Study grouping, exposure history and reviewer independence require human verification.",
                            "Unknown sequence context does not resolve an allele identity.",
                            "Field diagnostics exclude ambiguous anchors; consult end-to-end recall.",
                            "Retrieval recall, entity mention recall, clustering and human correction time are not scored in v1."]}

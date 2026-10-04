"""Small GRIN cluster backed by source-audited, interval-aware observations."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from .benchmark.cluster_annotations import audit_table_cells, validate
from .benchmark.contracts import digest

INTRINSIC = {"glutamate_ec50", "glycine_ec50", "magnesium_ic50", "zinc_ic50", "proton_response_ratio",
             "open_probability", "weighted_deactivation_tau", "steady_state_peak_ratio", "peak_current_density", "surface_total_ratio"}
POTENCY = {"glutamate_ec50", "glycine_ec50"}
TIERS = ("core_likely_reduced", "provisional_possible_reduced", "opposing_control", "unresolved_control")


def ratio(observation):
    """Never turn censoring, unequal units, or missing WT into a point ratio."""
    m, wt = observation["measurement"], observation["comparator"]["measurement"]
    if observation["endpoint"] not in INTRINSIC or observation["measurement_type"] != "measured":
        return None
    if wt is None or m["relation"] != "eq" or wt["relation"] != "eq" or m["unit"] != wt["unit"]:
        return None
    if m["estimate"] is None or wt["estimate"] is None:
        return None
    a, b = Decimal(m["estimate"]), Decimal(wt["estimate"])
    if a < 0 or b <= 0 or observation["endpoint"] in POTENCY and a == 0:
        return None
    value = b / a if observation["endpoint"] in POTENCY else a / b
    return {"value": str(value), "definition": "WT EC50 / variant EC50" if observation["endpoint"] in POTENCY else "variant / matched WT",
            "uncertainty": "Not propagated; descriptive central-value ratio only"}


def tier_for(claims, observations):
    labels = {c["category"] for c in claims if c["predicate"] == "author_functional_classification" and c["evidence_type"] == "primary_report"}
    reduced = labels & {"Likely LoF", "Possible LoF", "LoF"}
    increased = labels & {"Likely GoF", "Possible GoF", "GoF"}
    if reduced and increased or labels & {"Indeterminant", "No effect"}:
        return "unresolved_control"
    measured = any(ratio(o) is not None for o in observations)
    if "Likely LoF" in labels and measured:
        return "core_likely_reduced"
    if reduced:
        return "provisional_possible_reduced"
    if increased:
        return "opposing_control"
    return "unresolved_control"


def build(reference, sources, curated, ledger):
    validation = validate(reference, sources)
    validation.update(audit_table_cells(reference, ledger))
    if reference["review_type"] != "source_audited_ai_reference":
        raise ValueError("Cluster requires a source-audited reference, not an independent draft")
    data = {"schema_version": "grin-cluster-demo-v2", "title": "GRIN functional evidence", "synthetic": False,
            "method": "Source-reported functional-category grouping with contextual assay evidence; not unsupervised clustering",
            "review_status": "AI source-audited; expert review pending", "reference_sha256": digest(reference),
            "sources_sha256": digest(sources), "members": [], "observations": [], "claims": [],
            "coverage": reference["coverage"], "issues": [], "sources": []}
    unit_index = {u["unit_id"]: u for u in sources["units"]}
    for d in ledger["documents"]:
        data["sources"].append({"document_id": d["document_id"], "title": d["title"], "url": d["url"]})
    def without_quotes(row):
        if isinstance(row, dict):
            if {"unit_id", "start", "end", "quote"} <= set(row):
                return {"unit_id": row["unit_id"], "start": row["start"], "end": row["end"],
                        "locator": unit_index[row["unit_id"]]["locator"]}
            return {k: without_quotes(v) for k, v in row.items()}
        if isinstance(row, list):
            return [without_quotes(v) for v in row]
        return row
    for row in reference["observations"]:
        output = without_quotes(row)
        output["normalized_comparison"] = ratio(row)
        output["channel"] = (
            "secondary_summary" if row["measurement_type"] == "secondary_summary" else
            "calculated_function" if row["measurement_type"] == "author_calculated" else
            "intrinsic_function" if row["endpoint"] in INTRINSIC else "pharmacology_or_other")
        data["observations"].append(output)
    data["claims"] = without_quotes(reference["claims"])
    data["issues"] = without_quotes(reference["issues"])
    for variant in curated["variants"]:
        gene, protein = variant["gene"], variant["reported_protein"]
        rows = [o for o in data["observations"] if (o["gene"], o["protein"]) == (gene, protein)]
        claims = [c for c in data["claims"] if (c["gene"], c["protein"]) == (gene, protein)]
        issues = [i for i in data["issues"] if (i["gene"], i["protein"]) == (gene, protein)]
        tier = tier_for(claims, rows)
        data["members"].append({"id": "variant:" + re.sub(r"[^a-z0-9]+", "-", variant["variant_id"].lower()).strip("-"),
                                "gene": gene, "protein": protein, "tier": tier,
                                "previous_tier": variant["cohort_tier"], "tier_changed": tier != variant["cohort_tier"],
                                "author_classifications": sorted({c["category"] for c in claims if c["category"] and c["predicate"] == "author_functional_classification"}),
                                "observation_count": len(rows), "quantitative_count": sum(r["measurement"]["estimate"] is not None for r in rows),
                                "paper_count": len({r["document_id"] for r in rows} | {c["document_id"] for c in claims}),
                                "issue_count": len(issues), "claim_ids": [c["id"] for c in claims],
                                "identity_scope": "Protein variant and reported assay construct; genomic/transcript conflicts remain explicit"})
    data["counts"] = {**validation, "variants": len(data["members"]), "tiers": dict(Counter(v["tier"] for v in data["members"]))}
    data["limitations"] = ["This is the selected ten-variant cluster, not all GRIN variants or a patient cohort.",
        "Intervals, censored values, treatments, receptor compositions and source conflicts remain separate.",
        "No numerical averaging across studies, uncertainty propagation or treatment recommendation.",
        "Drug response observations do not establish intrinsic functional direction.",
        "Counts describe annotated source records, not independent experiments; later papers can reuse earlier measurements.",
        "AI annotation agreement and source checks are not expert scientific validation."]
    return data


def serve(bundle, sources, port):
    if bundle["sources_sha256"] != digest(sources):
        raise ValueError("Source snapshots do not match the cluster")
    units = {u["unit_id"]: u for u in sources["units"]}
    records = {r["id"]: r for r in bundle["observations"] + bundle["claims"]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, code, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") not in {f"localhost:{port}", f"127.0.0.1:{port}"}:
                self.respond(403, {"error": "Forbidden host"}); return
            route = urlsplit(self.path)
            if route.path == "/":
                self.respond(200, Path(__file__).with_name("cluster_web.html").read_bytes(), "text/html; charset=utf-8")
            elif route.path == "/api/cluster":
                self.respond(200, bundle)
            elif route.path == "/api/evidence":
                ident = parse_qs(route.query).get("id", [""])[0]
                if ident not in records:
                    self.respond(404, {"error": "Unknown observation or claim"}); return
                record = records[ident]
                spans = record["evidence"] + record.get("comparator", {}).get("evidence", [])
                result, seen = [], set()
                for span in spans:
                    key = (span["unit_id"], span["start"], span["end"])
                    if key not in seen:
                        seen.add(key)
                        result.append({**span, "quote": units[span["unit_id"]]["text"][span["start"]:span["end"]]})
                self.respond(200, {"record": record, "spans": result})
            else:
                self.respond(404, {"error": "Not found"})
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    build_cmd = sub.add_parser("build")
    for name in ("reference", "sources", "curated", "ledger", "output"):
        build_cmd.add_argument("--" + name, type=Path, required=True)
    server = sub.add_parser("serve")
    server.add_argument("--bundle", type=Path, default=Path("data/curated/grin_cluster_demo_v2.json"))
    server.add_argument("--sources", type=Path, default=Path("data/processed/benchmarks/grin-development-v1/sources.json"))
    server.add_argument("--port", type=int, default=18769)
    args = p.parse_args()
    def read(path): return json.loads(path.read_text())
    if args.command == "build":
        result = build(read(args.reference), read(args.sources), read(args.curated), read(args.ledger))
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result["counts"]))
    else:
        serve(read(args.bundle), read(args.sources), args.port)


if __name__ == "__main__":
    main()

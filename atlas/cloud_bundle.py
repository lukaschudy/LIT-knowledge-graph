"""Overlay the reviewed cluster onto the public, source-linked GRIN graph."""
from copy import deepcopy
from .cluster_questions import short_protein


def reviewed_graph(original, cluster):
    if original["dataset"]["synthetic"] or cluster.get("synthetic") is not False:
        raise ValueError("Production GRIN deployment requires real source records")
    graph = deepcopy(original)
    graph["dataset"].update(id="grin-reviewed-cluster-v2-" + cluster["reference_sha256"][:12],
        title="GRIN — source-audited functional evidence",
        description="Ten selected GRIN2A/GRIN2B protein variants; 340 source-audited observations across seven papers. AI review complete; expert review pending.",
        annotation_reference_sha256=cluster["reference_sha256"], annotation_counts=cluster["counts"])
    members = {v["id"]: v for v in cluster["members"]}
    nodes = {n["id"]: n for n in graph["nodes"]}
    if not members.keys() <= nodes.keys():
        raise ValueError("Reviewed variant identities do not match the graph")
    for ident, v in members.items():
        n = nodes[ident]
        n["aliases"] = list(dict.fromkeys(n["aliases"] + [short_protein(v["protein"])]))
        p = n["properties"]
        # Earlier scalar transcription notes can conflict with the new source audit.
        for field in ("functional_evidence", "integrated_function"):
            p.pop(field, None)
        p.update(cohort_tier=v["tier"], strict_reduced_function_inclusion=v["tier"] == "core_likely_reduced",
                 annotation_summary=deepcopy(v), description=f"{v['observation_count']} annotated source records in {v['paper_count']} papers. {cluster['review_status']}.")
    source_ids = {s["document_id"]: next((old["id"] for old in graph["sources"] if s["document_id"] in old["url"]), None) for s in cluster["sources"]}
    if not all(source_ids.values()):
        raise ValueError("A reviewed paper is missing from the graph source list")
    for claim in graph["claims"]:
        if claim["predicate"] != "HAS_EFFECT" or claim["subject"] not in members:
            continue
        v = members[claim["subject"]]
        classes = [c for c in cluster["claims"] if c["gene"] == v["gene"] and c["protein"] == v["protein"]
                   and c["predicate"] == "author_functional_classification" and c["evidence_type"] == "primary_report"]
        claim["context"].update(cohort_tier=v["tier"], source_classification="; ".join(sorted({c["category"] for c in classes if c["category"]})),
            effect={"core_likely_reduced": "loss_of_function", "opposing_control": "gain_of_function"}.get(v["tier"], "unknown"),
            assay_details="See the source-audited observation records for assay-specific conditions and matched controls.",
            annotation_reference_sha256=cluster["reference_sha256"])
        graph["evidence"] = [e for e in graph["evidence"] if e["claim_id"] != claim["id"]]
        for c in classes:
            graph["evidence"].append(dict(id="reviewed:" + c["id"], claim_id=claim["id"], source_id=source_ids[c["document_id"]],
                locator="; ".join(dict.fromkeys(e["locator"] for e in c["evidence"])),
                excerpt=c["statement"], stance="supports", review_status="machine_checked"))
    return graph

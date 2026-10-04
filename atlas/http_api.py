"""Runtime-independent, read-only API shared by local and Cloudflare hosting."""
from __future__ import annotations
from typing import Any
from .reasoning import AtlasReasoner
from .questions import answer_question


def response(status: int, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return status, payload


def error(status: int, code: str, message: str) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"code": code, "message": message}}


def _index_by_id(bundle: dict[str, Any], collection: str) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in bundle.get(collection, []) if isinstance(item, dict) and item.get("id")}


def _node_terms(node: dict[str, Any]) -> list[str]:
    return [str(value) for value in [node["id"], node["label"], *node["aliases"]]
            if isinstance(value, (str, int, float))]


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("name") or node.get("label") or node.get("symbol") or node.get("id") or "Untitled node")


class AtlasAPI:
    def __init__(self, bundle: dict[str, Any], stats: dict[str, int]):
        reasoner = AtlasReasoner(bundle)
        nodes = _index_by_id(bundle, "nodes")
        claims = _index_by_id(bundle, "claims")
        sources = _index_by_id(bundle, "sources")
        node_terms = {node_id: [term.casefold() for term in _node_terms(node)] for node_id, node in nodes.items()}
        evidence_by_claim: dict[str, list[dict[str, Any]]] = {}
        for row in bundle["evidence"]:
            evidence_by_claim.setdefault(row["claim_id"], []).append(row)

        self.bundle, self.stats, self.reasoner = bundle, stats, reasoner
        self.nodes, self.claims, self.sources = nodes, claims, sources
        self.node_terms, self.evidence_by_claim = node_terms, evidence_by_claim

    def _one(self, query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key, [])
        if len(values) != 1:
            return None
        value = values[0].strip()
        return value or None

    def request(self, path: str, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
        bundle, stats, reasoner = self.bundle, self.stats, self.reasoner
        nodes, claims, sources = self.nodes, self.claims, self.sources
        node_terms, evidence_by_claim = self.node_terms, self.evidence_by_claim
        if path == "/api/ask":
            question = self._one(query, "q")
            context = self._one(query, "node")
            claim_context = query.get("claim", [])
            if not question or len(question) > 1000:
                return error(400, "invalid_question", "Ask a question of 1–1000 characters.")
            if context and context not in nodes:
                return error(404, "node_not_found", "That entity is not in this graph.")
            if len(claim_context) > 100 or any(cid not in claims for cid in claim_context):
                return error(400, "invalid_claim_context", "Use claim references from this graph.")
            return response(200, answer_question(bundle, reasoner, question, context, claim_context))
        if path == "/api/health":
            return response(200, {"status": "ok", "synthetic": bool(bundle["dataset"]["synthetic"]), "dataset": bundle["dataset"]})
        if path == "/api/stats":
            return response(200, {"dataset": bundle["dataset"], "stats": stats})
        if path == "/api/graph":
            return response(200, bundle)
        if path == "/api/search":
            term = self._one(query, "q")
            if term is None:
                return error(400, "missing_query", "Enter a name, synonym, or identifier to search the atlas.")
            folded = term.casefold()
            matches: list[tuple[int, dict[str, Any]]] = []
            for node_id, terms in node_terms.items():
                node = nodes[node_id]
                if folded in terms:
                    score = 0
                elif any(folded in value for value in terms):
                    score = 1
                else:
                    continue
                matches.append((score, node))
            matches.sort(key=lambda item: (item[0], _node_label(item[1]).casefold(), str(item[1].get("id"))))
            return response(200, {"query": term, "total": len(matches), "results": [node for _, node in matches[:40]]})
        if path == "/api/explore":
            disease_id = self._one(query, "disease")
            if disease_id is None:
                return error(400, "missing_disease", "Choose a disease to explore.")
            node = nodes.get(disease_id)
            if node is None:
                return error(404, "disease_not_found", "That disease is not in this atlas dataset.")
            if str(node.get("type", node.get("kind", ""))).casefold() != "disease":
                return error(400, "not_a_disease", "Choose a disease node to explore connections.")
            result = reasoner.explore(disease_id)
            return response(200, result)
        if path == "/api/claim":
            claim_id = self._one(query, "id")
            if claim_id is None:
                return error(400, "missing_claim", "Choose an evidence claim to inspect.")
            claim = claims.get(claim_id)
            if claim is None:
                return error(404, "claim_not_found", "That claim is not in this atlas dataset.")
            claim_evidence = evidence_by_claim.get(claim_id, [])
            support_rows = [row for row in claim_evidence if row["stance"] == "supports"]
            contradiction_rows = [row for row in claim_evidence if row["stance"] == "contradicts"]
            source_ids = list(dict.fromkeys(row["source_id"] for row in claim_evidence))
            return response(200, {
                "claim": claim,
                "support": support_rows,
                "contradictions": contradiction_rows,
                "sources": [sources[item] for item in dict.fromkeys(source_ids) if item in sources],
            })
        return error(404, "api_not_found", "That atlas endpoint does not exist.")

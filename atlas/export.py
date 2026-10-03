"""Serialization helpers for JSON-LD and Cytoscape consumers."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote


def to_jsonld(bundle: dict[str, Any]) -> dict[str, Any]:
    """Export a bundle as JSON-LD, retaining claims and evidence as first-class nodes."""
    context = {
        "atlas": "https://example.org/atlas/",
        "schema": "https://schema.org/",
        "label": "schema:name",
        "aliases": {"@id": "atlas:aliases", "@type": "@json"},
        "properties": {"@id": "atlas:properties", "@type": "@json"},
        "dataset": {"@id": "atlas:dataset", "@type": "@json"},
        "schemaVersion": "atlas:schemaVersion",
        "title": "schema:name",
        "url": "schema:url",
        "published_at": "atlas:publishedAt",
        "retrieved_at": "atlas:retrievedAt",
        "kind": "atlas:sourceKind",
        "synthetic": "atlas:synthetic",
        "license": "atlas:license",
        "subject": {"@id": "atlas:subject", "@type": "@id"},
        "predicate": {"@id": "atlas:predicate", "@type": "@id"},
        "object": {"@id": "atlas:object", "@type": "@id"},
        "assertionType": "atlas:assertionType",
        "context": {"@id": "atlas:context", "@type": "@json"},
        "extractionConfidence": "atlas:extractionConfidence",
        "claim": {"@id": "atlas:claim", "@type": "@id"},
        "source": {"@id": "atlas:source", "@type": "@id"},
        "entity": {"@id": "atlas:entity", "@type": "@id"},
        "locator": "atlas:locator",
        "excerpt": "atlas:excerpt",
        "stance": "atlas:stance",
        "reviewStatus": "atlas:reviewStatus",
        "scope": "atlas:scope",
        "status": "atlas:status",
        "searchedAt": "atlas:searchedAt",
        "notes": "atlas:notes",
    }
    graph: list[dict[str, Any]] = []
    for node in bundle.get("nodes", []):
        graph.append({
            "@id": node["id"], "@type": f"atlas:{node['type']}", "label": node["label"],
            "aliases": node.get("aliases", []), "properties": node.get("properties", {}),
        })
    for source in bundle.get("sources", []):
        graph.append({"@id": source["id"], "@type": "atlas:Source", **{k: v for k, v in source.items() if k != "id"}})
    for claim in bundle.get("claims", []):
        graph.append({
            "@id": claim["id"], "@type": "atlas:Claim",
            "subject": {"@id": claim["subject"]}, "predicate": {"@id": f"atlas:{claim['predicate']}"},
            "object": {"@id": claim["object"]}, "assertionType": claim["assertion_type"],
            "context": claim["context"], "extractionConfidence": claim["extraction_confidence"],
        })
    for evidence in bundle.get("evidence", []):
        graph.append({
            "@id": evidence["id"], "@type": "atlas:Evidence",
            "claim": {"@id": evidence["claim_id"]},
            "source": {"@id": evidence["source_id"]},
            "locator": evidence["locator"], "excerpt": evidence["excerpt"],
            "stance": evidence["stance"], "reviewStatus": evidence["review_status"],
        })
    for coverage in bundle.get("coverage", []):
        graph.append({
            "@id": coverage["id"], "@type": "atlas:Coverage",
            "source": {"@id": coverage["source_id"]}, "entity": {"@id": coverage["entity_id"]},
            "scope": coverage["scope"], "status": coverage["status"],
            "searchedAt": coverage["searched_at"], "notes": coverage.get("notes", ""),
        })
    return {"@context": context,
            "@type": "schema:Dataset", "dataset": bundle.get("dataset"), "schemaVersion": bundle.get("schema_version"),
            "@graph": graph}


def to_cytoscape(bundle: dict[str, Any]) -> dict[str, Any]:
    """Export graph elements while preserving assertion and provenance records."""
    elements: list[dict[str, Any]] = []

    def cy_id(kind: str, record_id: str) -> str:
        return f"{kind}|{quote(record_id, safe='')}"

    def node_element(identifier: str, data: dict[str, Any]) -> None:
        record_id = data.get("id")
        payload = {key: value for key, value in data.items() if key != "id"}
        elements.append({"data": {"id": identifier, "record_id": record_id, **payload}})

    def edge(identifier: str, source: str, target: str, predicate: str, **extra: Any) -> None:
        elements.append({"data": {"id": identifier, "source": source, "target": target, "predicate": predicate, **extra}})

    for node in bundle.get("nodes", []):
        node_element(cy_id("entity", node["id"]), {"kind": "entity", **node})
    for source in bundle.get("sources", []):
        node_element(cy_id("source", source["id"]), {"kind": "source", **source})
    for claim in bundle.get("claims", []):
        cid = cy_id("claim", claim["id"])
        node_element(cid, {"kind": "claim", **claim})
        edge(f"{cid}:subject", cid, cy_id("entity", claim["subject"]), "CLAIM_SUBJECT")
        edge(f"{cid}:object", cid, cy_id("entity", claim["object"]), "CLAIM_OBJECT")
    for evidence in bundle.get("evidence", []):
        eid = cy_id("evidence", evidence["id"])
        node_element(eid, {"kind": "evidence", **evidence})
        edge(f"{eid}:claim", eid, cy_id("claim", evidence["claim_id"]), "EVIDENCE_FOR")
        edge(f"{eid}:source", eid, cy_id("source", evidence["source_id"]), "EVIDENCE_FROM")
    for coverage in bundle.get("coverage", []):
        cid = cy_id("coverage", coverage["id"])
        node_element(cid, {"kind": "coverage", **coverage})
        edge(f"{cid}:source", cid, cy_id("source", coverage["source_id"]), "COVERAGE_OF_SOURCE")
        edge(f"{cid}:entity", cid, cy_id("entity", coverage["entity_id"]), "COVERAGE_OF_ENTITY")
    return {"data": {"dataset": bundle.get("dataset"), "schema_version": bundle.get("schema_version")},
            "elements": elements}

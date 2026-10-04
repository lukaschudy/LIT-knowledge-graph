"""Deterministic entity resolution from explicit, trusted identity links.

Names and labels are descriptive only. This module never merges on text
similarity; callers must supply an explicitly typed identity link and its
provenance.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any


TRUSTED_RULES = {"registry_same_as", "publication_identifiers", "curated_identifier"}
_PATTERNS = (
    ("HGNC", re.compile(r"(?:^|[/#:])HGNC[:/#]?(\d+)$", re.I)),
    ("MONDO", re.compile(r"(?:^|[/#:])MONDO[:/#]?(\d+)$", re.I)),
    ("ClinVar", re.compile(r"(?:^|[/#:])(?:ClinVar(?:Variation)?|VCV)[:/#]?(\d+)$", re.I)),
    ("PMID", re.compile(r"(?:^|[/#:])PMID[:/#]?(\d+)$", re.I)),
    ("DOI", re.compile(r"(?:^|[/#:])(?:doi:)?(10\.\d{4,9}/\S+)$", re.I)),
    ("ORCID", re.compile(r"(?:^|[/#:])?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$", re.I)),
)
_PROPERTY_NAMES = {
    "HGNC": ("hgnc", "hgnc_id", "hgnc_identifier"),
    "MONDO": ("mondo", "mondo_id", "mondo_identifier"),
    "ClinVar": ("clinvar", "clinvar_id", "clinvar_variation_id", "variation_id"),
    "PMID": ("pmid", "pubmed_id"),
    "DOI": ("doi",),
    "ORCID": ("orcid", "orcid_id"),
}
_CANONICAL_PRIORITY = {"HGNC": 0, "MONDO": 0, "ClinVar": 0, "PMID": 0, "DOI": 1, "ORCID": 0}


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for namespace, pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            token = match.group(1)
            if namespace == "DOI":
                token = token.casefold()
            else:
                token = token.upper()
            return namespace, token
    return None


def _identities(node: dict[str, Any]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}

    def add(raw: Any, namespace: str | None = None) -> None:
        parsed = _identity(str(raw)) if raw is not None else None
        if parsed:
            ns, value = parsed
        elif namespace and isinstance(raw, (str, int)) and str(raw).strip():
            ns, value = namespace, str(raw).strip().upper()
        else:
            return
        found.setdefault(ns, set()).add(value)

    add(node.get("id"))
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for namespace, names in _PROPERTY_NAMES.items():
        for name in names:
            if name in properties:
                add(properties[name], namespace)
    identifiers = properties.get("identifiers")
    if isinstance(identifiers, dict):
        for key, value in identifiers.items():
            namespace = next((ns for ns, names in _PROPERTY_NAMES.items()
                              if key.casefold() in {n.casefold() for n in names} or key.casefold() == ns.casefold()), None)
            if namespace:
                if isinstance(value, (list, tuple, set)):
                    for item in value:
                        add(item, namespace)
                else:
                    add(value, namespace)
    elif isinstance(identifiers, (list, tuple, set)):
        for value in identifiers:
            add(value)
    return found


def _conflicting_identities(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, set[str]] = {}
    for node in nodes:
        for namespace, values in _identities(node).items():
            grouped.setdefault(namespace, set()).update(values)
    return [{"namespace": namespace, "identifiers": sorted(values)}
            for namespace, values in sorted(grouped.items()) if len(values) > 1]


def _canonical_key(node: dict[str, Any]) -> tuple[int, int, str, str, str]:
    direct = _identity(node['id'])
    if direct and direct[0] in _CANONICAL_PRIORITY:
        return 0, _CANONICAL_PRIORITY[direct[0]], direct[0], direct[1], node['id']
    ids = _identities(node)
    candidates = []
    for namespace, values in ids.items():
        if namespace in _CANONICAL_PRIORITY:
            candidates.extend((_CANONICAL_PRIORITY[namespace], namespace, value) for value in values)
    if candidates:
        rank, namespace, value = min(candidates)
        return 1, rank, namespace, value, node["id"]
    return 2, 100, "source", str(node["id"]), node["id"]


def resolve_entities(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve nodes only through explicit trusted identity links.

    Args:
        nodes: Node records with unique ``id``, ``type``, ``label`` fields.
        links: ``{subject, object, rule, provenance}`` identity proposals.

    Returns canonical nodes, every original ID's canonical ID, per-link
    decisions, and rejected/conflicting identity links. Merged nodes keep member
    IDs, member labels, original node provenance, and identity-link provenance
    under ``properties.identity_resolution``.
    """
    if not isinstance(nodes, list) or not isinstance(links, list):
        raise ValueError("nodes and links must be arrays")
    if any(not isinstance(link, dict) for link in links):
        raise ValueError("each identity link must be an object")
    by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if (not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]
                or not isinstance(node.get("type"), str) or not isinstance(node.get("label"), str)):
            raise ValueError("each node requires string id, type, and label fields")
        if node["id"] in by_id:
            raise ValueError(f"duplicate node ID: {node['id']}")
        by_id[node["id"]] = deepcopy(node)

    parent = {node_id: node_id for node_id in by_id}

    def root(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    # A malformed record containing multiple authoritative values cannot be
    # used as a bridge that silently collapses another entity.
    blocked = {node_id for node_id, node in by_id.items() if _conflicting_identities([node])}
    conflicts = [{"kind": "node_identity_conflict", "node_id": node_id,
                  "identities": _conflicting_identities([by_id[node_id]])} for node_id in sorted(blocked)]

    ordered_links = sorted((deepcopy(link) for link in links), key=_stable)
    decisions: list[dict[str, Any]] = []
    accepted_links: list[dict[str, Any]] = []
    for link in ordered_links:
        subject, object_id, rule = link.get("subject"), link.get("object"), link.get("rule")
        decision = {"link": link, "status": None}
        if rule not in TRUSTED_RULES:
            decision["status"] = "rejected_untrusted_rule"
        elif link.get("provenance") is None or link.get("provenance") == {} or link.get("provenance") == [] or link.get("provenance") == "":
            decision["status"] = "rejected_missing_provenance"
        elif not isinstance(subject, str) or not isinstance(object_id, str) or subject not in by_id or object_id not in by_id:
            decision["status"] = "rejected_missing_node"
        elif subject in blocked or object_id in blocked:
            decision["status"] = "rejected_node_identity_conflict"
        elif by_id[subject]["type"] != by_id[object_id]["type"]:
            decision["status"] = "rejected_type_mismatch"
            decision["conflict"] = {"subject_type": by_id[subject]["type"], "object_type": by_id[object_id]["type"]}
        else:
            left, right = root(subject), root(object_id)
            if left == right:
                decision["status"] = "already_connected"
                accepted_links.append(link)
            else:
                left_members = [by_id[item] for item in by_id if root(item) == left]
                right_members = [by_id[item] for item in by_id if root(item) == right]
                identity_conflicts = _conflicting_identities(left_members + right_members)
                if identity_conflicts:
                    decision["status"] = "rejected_identity_conflict"
                    decision["conflict"] = identity_conflicts
                    conflicts.append({"kind": "link_identity_conflict", "link": link,
                                      "identities": identity_conflicts})
                else:
                    # Root choice is stable and independent of input ordering.
                    first, second = sorted((left, right))
                    parent[second] = first
                    decision["status"] = "merged"
                    accepted_links.append(link)
        decisions.append(decision)

    groups: dict[str, list[str]] = {}
    for node_id in sorted(by_id):
        groups.setdefault(root(node_id), []).append(node_id)

    output_nodes = []
    alias_map: dict[str, str] = {}
    for member_ids in groups.values():
        members = [by_id[item] for item in member_ids]
        canonical = min(members, key=_canonical_key)
        canonical_id = canonical["id"]
        output = deepcopy(canonical)
        aliases = set(output.get("aliases", []))
        labels = sorted({str(member.get("label", "")) for member in members if member.get("label")})
        aliases.update(label for label in labels if label != canonical.get("label"))
        for member in members:
            for alias in member.get("aliases", []) if isinstance(member.get("aliases"), list) else []:
                if isinstance(alias, str) and alias and alias != canonical.get("label"):
                    aliases.add(alias)
            alias_map[member["id"]] = canonical_id
        output["aliases"] = sorted(aliases)
        output.setdefault("properties", {})
        if not isinstance(output["properties"], dict):
            output["properties"] = {}
        member_set = set(member_ids)
        link_rows = [link for link in accepted_links
                     if link.get("subject") in member_set and link.get("object") in member_set]
        provenance_rows = []
        for member in members:
            provenance = member.get("provenance")
            if provenance is None and isinstance(member.get("properties"), dict):
                provenance = member["properties"].get("provenance")
            if provenance is not None:
                provenance_rows.append({"node_id": member["id"], "provenance": provenance})
        output["properties"]["identity_resolution"] = {
            "canonical_id": canonical_id,
            "member_ids": sorted(member_ids),
            "member_labels": labels,
            "node_provenance": sorted(provenance_rows, key=_stable),
            "link_provenance": sorted(({"rule": link.get("rule"), "subject": link.get("subject"),
                                         "object": link.get("object"), "provenance": link.get("provenance")}
                                        for link in link_rows), key=_stable),
        }
        output_nodes.append(output)

    output_nodes.sort(key=lambda node: node["id"])
    decisions.sort(key=_stable)
    conflicts.sort(key=_stable)
    return {"nodes": output_nodes, "alias_map": alias_map, "decisions": decisions, "conflicts": conflicts}

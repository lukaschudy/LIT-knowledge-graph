"""Data model and validation for the rare-disease atlas bundle."""

from __future__ import annotations

from datetime import date
import math
from typing import Any
from urllib.parse import urlparse


NODE_TYPES = {
    "Disease", "Gene", "Variant", "Mechanism", "Phenotype", "Organization",
    "Person", "Study", "Asset", "Publication", "Funding",
}
PREDICATE_ENDPOINTS: dict[str, tuple[set[str], set[str]]] = {
    "HAS_VARIANT": ({"Disease"}, {"Variant"}),
    "AFFECTS": ({"Variant"}, {"Gene"}),
    "HAS_EFFECT": ({"Variant"}, {"Mechanism"}),
    "INVOLVES": ({"Disease"}, {"Mechanism"}),
    "HAS_PHENOTYPE": ({"Disease"}, {"Phenotype"}),
    "REPRESENTS": ({"Organization"}, {"Disease"}),
    "MAINTAINS": ({"Organization"}, {"Asset"}),
    "RELEVANT_TO": ({"Asset"}, {"Disease"}),
    "STUDIES": ({"Person", "Study"}, {"Disease", "Mechanism"}),
    "AFFILIATED_WITH": ({"Person"}, {"Organization"}),
    "USED_IN": ({"Asset"}, {"Study"}),
    "AUTHORED": ({"Person"}, {"Publication"}),
    "FUNDS": ({"Funding"}, {"Study", "Asset"}),
    "CONTRAINDICATED_FOR": ({"Asset"}, {"Disease"}),
    "IS_A": ({"Phenotype"}, {"Phenotype"}),
    "SAME_AS": (NODE_TYPES, NODE_TYPES),
}
ASSERTION_TYPES = {"reported", "inferred"}
SOURCE_KINDS = {"database", "paper", "registry", "organization", "fixture"}
EVIDENCE_STANCES = {"supports", "contradicts"}
REVIEW_STATUSES = {"unreviewed", "machine_checked", "human_reviewed"}
COVERAGE_STATUSES = {"searched", "not_searched", "failed"}
CONTEXT_EFFECTS = {"loss_of_function", "gain_of_function", "unknown"}


class ValidationError(ValueError):
    """Raised when a bundle fails validation; ``errors`` contains all findings."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Invalid atlas bundle: " + "; ".join(errors))


def _is_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _check_json_value(value: Any, path: str, err: Any) -> None:
    """Reject Python values that cannot be represented as standards-compliant JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            err(path, "must not contain NaN or infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_json_value(item, f"{path}[{index}]", err)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                err(path, "object keys must be strings")
            else:
                _check_json_value(item, f"{path}.{key}", err)
        return
    err(path, f"contains a non-JSON value of type {type(value).__name__}")


def _validate_bundle(bundle: Any) -> list[str]:
    """Return validation errors for a complete bundle; performs no mutation."""
    errors: list[str] = []

    def err(path: str, message: str) -> None:
        errors.append(f"{path}: {message}")

    def obj(value: Any, path: str) -> bool:
        if not isinstance(value, dict):
            err(path, "must be an object")
            return False
        return True

    def required_fields(value: dict, fields: set[str], path: str) -> None:
        for field in sorted(fields - value.keys()):
            err(path, f"missing required field {field!r}")

    if not obj(bundle, "bundle"):
        return errors
    # Optional/extension metadata is serialized alongside the known fields.
    # Validate the complete payload so a "valid" bundle cannot later fail JSON
    # persistence or emit NaN merely because the value lived outside context.
    _check_json_value(bundle, "bundle", err)
    required_fields(bundle, {"schema_version", "dataset", "nodes", "sources", "claims", "evidence", "coverage"}, "bundle")
    if bundle.get("schema_version") != "1.0":
        err("schema_version", "must equal '1.0'")
    dataset = bundle.get("dataset")
    if obj(dataset, "dataset"):
        required_fields(dataset, {"id", "title", "description", "synthetic", "created_at"}, "dataset")
        for field in ("id", "title", "description"):
            if not isinstance(dataset.get(field), str) or not dataset[field].strip():
                err(f"dataset.{field}", "must be a nonempty string")
        if not isinstance(dataset.get("synthetic"), bool):
            err("dataset.synthetic", "must be a boolean")
        if not _is_date(dataset.get("created_at")):
            err("dataset.created_at", "must be an ISO date (YYYY-MM-DD)")

    buckets = {name: bundle.get(name) for name in ("nodes", "sources", "claims", "evidence", "coverage")}
    for name, rows in buckets.items():
        if not isinstance(rows, list):
            err(name, "must be an array")
            buckets[name] = []

    identifiers: dict[str, str] = {}
    rows_by_name: dict[str, dict[str, dict]] = {name: {} for name in buckets}
    for name, rows in buckets.items():
        for index, row in enumerate(rows):
            path = f"{name}[{index}]"
            if not obj(row, path):
                continue
            identifier = row.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                err(path + ".id", "must be a nonempty string")
            else:
                if identifier in identifiers:
                    err(path + ".id", f"duplicates ID in {identifiers[identifier]}")
                else:
                    identifiers[identifier] = path
                    rows_by_name[name][identifier] = row

    for index, node in enumerate(buckets["nodes"]):
        if not isinstance(node, dict):
            continue
        path = f"nodes[{index}]"
        if not isinstance(node.get("type"), str) or node["type"] not in NODE_TYPES:
            err(path + ".type", f"unknown node type {node.get('type')!r}")
        for field in ("label",):
            if not isinstance(node.get(field), str) or not node[field].strip():
                err(path + "." + field, "must be a nonempty string")
        aliases = node.get("aliases")
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() for a in aliases):
            err(path + ".aliases", "must be an array of nonempty strings")
        if not isinstance(node.get("properties"), dict):
            err(path + ".properties", "must be an object")

    source_rows = rows_by_name["sources"]
    for index, source in enumerate(buckets["sources"]):
        if not isinstance(source, dict):
            continue
        path = f"sources[{index}]"
        if "published_at" not in source:
            err(path, "missing required field 'published_at'")
        for field in ("title", "url", "kind", "retrieved_at", "license"):
            if not isinstance(source.get(field), str) or not source[field].strip():
                err(path + "." + field, "must be a nonempty string")
        parsed = None
        url = source.get("url")
        if isinstance(url, str):
            try:
                parsed = urlparse(url)
            except ValueError:
                parsed = None
        if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            err(path + ".url", "must be an absolute HTTP(S) URL")
        published = source.get("published_at")
        if published is not None and not _is_date(published):
            err(path + ".published_at", "must be an ISO date or null")
        if not _is_date(source.get("retrieved_at")):
            err(path + ".retrieved_at", "must be an ISO date (YYYY-MM-DD)")
        if not isinstance(source.get("kind"), str) or source["kind"] not in SOURCE_KINDS:
            err(path + ".kind", f"unknown source kind {source.get('kind')!r}")
        if not isinstance(source.get("synthetic"), bool):
            err(path + ".synthetic", "must be a boolean")
        if source.get("synthetic") is True:
            if source.get("kind") != "fixture":
                err(path, "synthetic sources must have kind 'fixture'")
            try:
                host = (parsed.hostname or "").lower() if parsed is not None else ""
            except ValueError:
                host = ""
            if host != "example.org" and not host.endswith(".example.org"):
                err(path + ".url", "synthetic fixture URLs must use example.org")
        if source.get("kind") == "fixture" and source.get("synthetic") is not True:
            err(path, "fixture sources must be marked synthetic")
    if isinstance(dataset, dict) and dataset.get("synthetic") is False:
        for source in buckets["sources"]:
            if isinstance(source, dict) and (source.get("synthetic") is True or source.get("kind") == "fixture"):
                err("sources", "production datasets cannot include synthetic or fixture sources")

    node_rows = rows_by_name["nodes"]
    for index, claim in enumerate(buckets["claims"]):
        if not isinstance(claim, dict):
            continue
        path = f"claims[{index}]"
        subject, object_id, predicate = claim.get("subject"), claim.get("object"), claim.get("predicate")
        for field, ref in (("subject", subject), ("object", object_id)):
            if not isinstance(ref, str) or ref not in node_rows:
                err(path + "." + field, f"must reference an existing node ID ({ref!r})")
        endpoint_types = PREDICATE_ENDPOINTS.get(predicate) if isinstance(predicate, str) else None
        if endpoint_types is None:
            err(path + ".predicate", f"unknown predicate {predicate!r}")
        elif isinstance(subject, str) and subject in node_rows and isinstance(node_rows[subject].get("type"), str):
            if node_rows[subject]["type"] not in endpoint_types[0]:
                err(path + ".subject", f"predicate {predicate} does not accept {node_rows[subject]['type']} as subject")
        if endpoint_types is not None and isinstance(object_id, str) and object_id in node_rows and isinstance(node_rows[object_id].get("type"), str):
            if node_rows[object_id]["type"] not in endpoint_types[1]:
                err(path + ".object", f"predicate {predicate} does not accept {node_rows[object_id]['type']} as object")
        if not isinstance(claim.get("assertion_type"), str) or claim["assertion_type"] not in ASSERTION_TYPES:
            err(path + ".assertion_type", "must be 'reported' or 'inferred'")
        context = claim.get("context")
        if not isinstance(context, dict):
            err(path + ".context", "must be an object")
        else:
            if "effect" in context and (not isinstance(context["effect"], str) or context["effect"] not in CONTEXT_EFFECTS):
                err(path + ".context.effect", f"unknown effect {context['effect']!r}")
            if "negated" in context and not isinstance(context["negated"], bool):
                err(path + ".context.negated", "must be a boolean")
            for qualifier in ("species", "tissue", "stage", "onset", "frequency", "evidence_code"):
                if qualifier in context and not isinstance(context[qualifier], str):
                    err(path + ".context." + qualifier, "must be a string")
        if "extraction_confidence" not in claim:
            err(path + ".extraction_confidence", "is required")
        confidence = claim.get("extraction_confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or confidence < 0 or confidence > 1 or (isinstance(confidence, float) and not math.isfinite(confidence))):
            err(path + ".extraction_confidence", "must be null or a finite number in [0, 1]")

    supporting: set[str] = set()
    for index, evidence in enumerate(buckets["evidence"]):
        if not isinstance(evidence, dict):
            continue
        path = f"evidence[{index}]"
        claim_id, source_id = evidence.get("claim_id"), evidence.get("source_id")
        if not isinstance(claim_id, str) or claim_id not in rows_by_name["claims"]:
            err(path + ".claim_id", f"must reference an existing claim ID ({claim_id!r})")
        if not isinstance(source_id, str) or source_id not in source_rows:
            err(path + ".source_id", f"must reference an existing source ID ({source_id!r})")
        for field in ("locator", "excerpt"):
            if not isinstance(evidence.get(field), str) or not evidence[field].strip():
                err(path + "." + field, "must be a nonempty string")
        if not isinstance(evidence.get("stance"), str) or evidence["stance"] not in EVIDENCE_STANCES:
            err(path + ".stance", "must be 'supports' or 'contradicts'")
        if not isinstance(evidence.get("review_status"), str) or evidence["review_status"] not in REVIEW_STATUSES:
            err(path + ".review_status", f"unknown review status {evidence.get('review_status')!r}")
        if evidence.get("stance") == "supports" and isinstance(claim_id, str):
            supporting.add(claim_id)
    for claim_id, claim in rows_by_name["claims"].items():
        if claim.get("assertion_type") == "reported" and claim_id not in supporting:
            err(f"claims[{claim_id}]", "reported claims require at least one supporting evidence item")

    for index, coverage in enumerate(buckets["coverage"]):
        if not isinstance(coverage, dict):
            continue
        path = f"coverage[{index}]"
        for required in ("searched_at", "notes"):
            if required not in coverage:
                err(path, f"missing required field {required!r}")
        if not isinstance(coverage.get("source_id"), str) or coverage["source_id"] not in source_rows:
            err(path + ".source_id", "must reference an existing source ID")
        if not isinstance(coverage.get("entity_id"), str) or coverage["entity_id"] not in node_rows:
            err(path + ".entity_id", "must reference an existing node ID")
        for field in ("scope", "status"):
            if not isinstance(coverage.get(field), str) or not coverage[field].strip():
                err(path + "." + field, "must be a nonempty string")
        if not isinstance(coverage.get("status"), str) or coverage["status"] not in COVERAGE_STATUSES:
            err(path + ".status", f"unknown coverage status {coverage.get('status')!r}")
        searched_at = coverage.get("searched_at")
        if searched_at is not None and not _is_date(searched_at):
            err(path + ".searched_at", "must be an ISO date or null")
        if coverage.get("status") == "searched" and searched_at is None:
            err(path + ".searched_at", "is required when status is 'searched'")
        if "notes" in coverage and not isinstance(coverage["notes"], str):
            err(path + ".notes", "must be a string")
    return errors


def validate_bundle(bundle: Any) -> list[str]:
    """Return errors for malformed or invalid JSON-compatible bundle input."""
    try:
        return _validate_bundle(bundle)
    except (TypeError, AttributeError, ValueError, OverflowError, RecursionError) as exc:
        return [f"bundle: malformed input ({type(exc).__name__}: {exc})"]


def require_valid_bundle(bundle: Any) -> None:
    errors = validate_bundle(bundle)
    if errors:
        raise ValidationError(errors)

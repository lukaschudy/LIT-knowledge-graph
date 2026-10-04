"""Action-specific assay reuse assessments; never treatment or transfer predictions.

Retrievers may propose evidence, but cannot promote it to reviewed science. The
legacy disease-neighbour explorer remains a separate, less restrictive API.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Protocol
from urllib.parse import urlsplit

from .model import require_valid_bundle

POLICY_VERSION = "assay-reuse-v3"
COLLECTIONS = ("nodes", "sources", "claims", "evidence", "coverage")
QUALIFIERS = ("mechanism_step", "readout", "species", "tissue")
STATUS_ORDER = {"ready_for_discussion": 0, "needs_clarification": 1, "not_supported": 2}


def _unknown_scope(value: Any) -> bool:
    return (not isinstance(value, str) or value.strip().casefold() in {
        "", "unknown", "unspecified", "not reported", "not_reported", "not available", "n/a", "na", "null", "none"})


def _scope(context: dict, request: ResearchRequest) -> str:
    """Absent optional scope is broad; explicitly unknown scope is unresolved."""
    unresolved = "variant_id" in context  # The request has no variant selector.
    for key in (*QUALIFIERS, "stage", "action_type"):
        if key not in context:
            continue
        actual = context[key]
        wanted = "assay_reuse" if key == "action_type" else getattr(request, key)
        if _unknown_scope(actual) or _unknown_scope(wanted):
            unresolved = True
        elif actual != wanted:
            return "different"
    return "unknown" if unresolved else "applicable"


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def snapshot_id(bundle: dict) -> str:
    canonical = deepcopy(bundle)
    for name in COLLECTIONS:
        canonical[name] = sorted(canonical[name], key=lambda row: row["id"])
    return digest(canonical)


@dataclass(frozen=True)
class ResearchRequest:
    disease_id: str
    mechanism_id: str
    mechanism_step: str
    readout: str
    species: str
    tissue: str
    stage: str = ""
    preferred_asset_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for key in ("disease_id", "mechanism_id", *QUALIFIERS):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{key} must be a nonempty, trimmed identifier")
        if not isinstance(self.stage, str) or self.stage != self.stage.strip():
            raise ValueError("stage must be a trimmed string; omit it only when not specified")
        if not isinstance(self.preferred_asset_ids, tuple) or any(
                not isinstance(x, str) or not x for x in self.preferred_asset_ids):
            raise ValueError("preferred_asset_ids must contain asset identifiers")
        if len(set(self.preferred_asset_ids)) != len(self.preferred_asset_ids):
            raise ValueError("preferred_asset_ids must be unique")

    @classmethod
    def from_dict(cls, value: dict) -> ResearchRequest:
        if not isinstance(value, dict):
            raise ValueError("Request must be an object")
        values = dict(value)
        if "preferred_asset_ids" in values:
            if not isinstance(values["preferred_asset_ids"], list):
                raise ValueError("preferred_asset_ids must be a list")
            values["preferred_asset_ids"] = tuple(values["preferred_asset_ids"])
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError(f"Invalid research request: {exc}") from exc


@dataclass(frozen=True)
class SearchBudget:
    max_candidates: int = 40
    max_followup_queries: int = 3
    max_new_claims: int = 30
    max_followup_rounds: int = 1

    def __post_init__(self) -> None:
        limits = {"max_candidates": (1, 100), "max_followup_queries": (0, 5),
                  "max_new_claims": (0, 100), "max_followup_rounds": (0, 1)}
        for field, (low, high) in limits.items():
            value = getattr(self, field)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{field} must be an integer in [{low}, {high}]")


class EvidenceRetriever(Protocol):
    def retrieve(self, questions: list[dict], *, max_claims: int) -> dict:
        """Return a delta with nodes, sources, claims and evidence lists.

        Implementations must enforce their own network timeout/cost limits.
        Only additive updates are accepted; every new evidence row is unreviewed.
        Source revisions and scientific review use the offline ingestion path.
        """
        ...


def gate(code: str, state: str, reason: str, claim_ids=(), *, researchable: bool = True) -> dict:
    return {"code": code, "state": state, "reason": reason,
            "claim_ids": sorted(set(claim_ids)), "researchable": researchable}


def _route_key(gates: list[dict]) -> tuple:
    # A viable but incomplete route is preferable to a documented mismatch.
    return (sum(g["state"] == "block" for g in gates),
            sum(g["state"] == "unknown" for g in gates),
            tuple(cid for g in gates for cid in g["claim_ids"]))


def _url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port  # A malformed port is not a usable professional contact route.
        return (parsed.scheme in ("https", "http") and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not any(char.isspace() for char in value))
    except ValueError:
        return False


class RecommendationEngine:
    def __init__(self, bundle: dict):
        require_valid_bundle(bundle)
        self._bundle = deepcopy(bundle)
        self.snapshot = snapshot_id(self._bundle)
        self.nodes = {n["id"]: n for n in self._bundle["nodes"]}
        self.sources = {s["id"]: s for s in self._bundle["sources"]}
        self.claims = {c["id"]: c for c in self._bundle["claims"]}
        self.outgoing: dict[tuple, list] = defaultdict(list)
        self.incoming: dict[tuple, list] = defaultdict(list)
        self.evidence: dict[str, list] = defaultdict(list)
        self.equivalents: dict[str, list] = defaultdict(list)
        for claim in sorted(self.claims.values(), key=lambda c: c["id"]):
            self.outgoing[claim["subject"], claim["predicate"]].append(claim)
            self.incoming[claim["object"], claim["predicate"]].append(claim)
            self.equivalents[self._proposition(claim)].append(claim)
        for evidence in sorted(self._bundle["evidence"], key=lambda e: e["id"]):
            self.evidence[evidence["claim_id"]].append(evidence)
        self._states: dict[str, dict] = {}

    @staticmethod
    def _proposition(claim: dict) -> str:
        context = {k: v for k, v in claim["context"].items() if k != "negated"}
        return digest([claim["subject"], claim["predicate"], claim["object"], context])

    def _claim_state(self, claim: dict) -> dict:
        """Coalesce identical propositions, including separately stored negation.

        Citation counts and model confidence never increase eligibility. Human
        review must refer to the exact current source version. Pending opposing
        evidence creates uncertainty, not proof that the proposition is false.
        """
        key = self._proposition(claim)
        if key in self._states:
            return self._states[key]
        positive = negative = pending_negative = False
        aliases = list(self.equivalents[key])
        context = {k: v for k, v in claim["context"].items() if k != "negated"}
        # A broad negation must not disappear just because its qualifier set is
        # less specific. Narrower opposition raises uncertainty about that scope.
        for related in self.outgoing[claim["subject"], claim["predicate"]]:
            if related["object"] != claim["object"] or self._proposition(related) == key:
                continue
            other = {k: v for k, v in related["context"].items() if k != "negated"}
            if all(context[k] == other[k] or (k in (*QUALIFIERS, "stage", "variant_id", "action_type")
                   and (_unknown_scope(context[k]) or _unknown_scope(other[k])))
                   for k in context.keys() & other.keys()):
                if any((e["stance"] == "contradicts") != bool(related["context"].get("negated"))
                       for e in self.evidence[related["id"]]):
                    aliases.append(related)
        for equivalent in aliases:
            if equivalent["assertion_type"] != "reported":
                continue
            for evidence in self.evidence[equivalent["id"]]:
                source = self.sources[evidence["source_id"]]
                if source.get("status", "active") != "active":
                    continue
                agrees = ((evidence["stance"] == "supports") != bool(equivalent["context"].get("negated")))
                reviewed = (evidence["review_status"] == "human_reviewed"
                            and isinstance(source.get("version"), str) and bool(source["version"])
                            and evidence.get("source_version") == source["version"])
                if self._proposition(equivalent) != key:
                    if agrees:
                        continue
                    other = {k: v for k, v in equivalent["context"].items() if k != "negated"}
                    if not other.items() <= context.items():
                        reviewed = False  # Narrow/partially specified opposition is not a global refutation.
                positive |= agrees and reviewed
                negative |= not agrees and reviewed
                pending_negative |= not agrees and not reviewed
        state = ("disputed" if positive and (negative or pending_negative) else
                 "supported" if positive else "refuted" if negative else "unknown")
        result = {"state": state, "claim_ids": sorted(c["id"] for c in aliases)}
        self._states[key] = result
        return result

    def _evidence_gate(self, claim: dict, code: str) -> dict:
        assessment = self._claim_state(claim)
        state = assessment["state"]
        reason = {"supported": "Reported claim has human review tied to the current source version.",
                  "refuted": "Reviewed evidence opposes this proposition.",
                  "disputed": "Supporting and opposing evidence require reconciliation.",
                  "unknown": "Current, source-versioned human review is missing."}[state]
        return gate(code, {"supported": "pass", "refuted": "block"}.get(state, "unknown"),
                    reason, assessment["claim_ids"],
                    researchable=state != "unknown")

    def _anchor(self, request: ResearchRequest) -> dict:
        claims = [c for c in self.outgoing[request.disease_id, "INVOLVES"]
                  if c["object"] == request.mechanism_id
                  and c["context"].get("mechanism_step") == request.mechanism_step]
        if not claims:
            return gate("anchor", "unknown", "The requested biological step is not documented for this disease.")
        checks = []
        for claim in claims:
            check = self._evidence_gate(claim, "anchor")
            context = claim["context"]
            if check["state"] == "pass" and (_scope(context, request) != "applicable"
                                              or _unknown_scope(request.mechanism_step)):
                check = gate("anchor", "unknown", "Disease mechanism evidence is scoped to a different or unspecified model, stage or variant; resolve that scope first.", check["claim_ids"])
            checks.append(check)
        return min(checks, key=lambda g: _route_key([g]))

    def _capabilities(self, asset_id: str, request: ResearchRequest) -> tuple[list[dict], list[dict]]:
        routes = []
        for claim in self.outgoing[asset_id, "MEASURES"]:
            if claim["object"] != request.mechanism_id:
                continue
            proof = self._evidence_gate(claim, "capability_evidence")
            checks = [proof]
            qualifiers = (*QUALIFIERS, "stage") if request.stage or "stage" in claim["context"] else QUALIFIERS
            for qualifier in qualifiers:
                actual = claim["context"].get(qualifier)
                wanted = getattr(request, qualifier)
                if proof["state"] != "pass":
                    checks.append(gate(qualifier, "unknown", "Capability evidence needs resolution before comparing context.", proof["claim_ids"],
                                       researchable=proof.get("researchable", True)))
                elif _unknown_scope(wanted) or _unknown_scope(actual):
                    checks.append(gate(qualifier, "unknown", f"The assay's {qualifier} is undocumented.", proof["claim_ids"]))
                else:
                    matches = actual == wanted
                    checks.append(gate(qualifier, "pass" if matches else "block",
                                       f"Requested {wanted}; documented {actual}.", proof["claim_ids"]))
            if ("variant_id" in claim["context"] or ("action_type" in claim["context"]
                    and claim["context"]["action_type"] != "assay_reuse")):
                checks.append(gate("capability_scope", "unknown", "Resolve the capability's variant or action scope before applying it to this request.", proof["claim_ids"]))
            routes.append({"claim_id": claim["id"], "gates": checks})
        if not routes:
            return [gate("capability_evidence", "unknown", "No documented measurement capability for this mechanism.")], []
        best = min(routes, key=lambda route: _route_key(route["gates"]))
        return best["gates"], routes

    def _access(self, asset_id: str, request: ResearchRequest) -> tuple[list[dict], dict | None, list[dict]]:
        routes = []
        for claim in self.incoming[asset_id, "MAINTAINS"]:
            proof = self._evidence_gate(claim, "maintainer_evidence")
            context = claim["context"]
            access = context.get("access_status")
            contact = context.get("contact_url")
            applicable = _scope(context, request) == "applicable"
            reviewed = proof["state"] == "pass" and applicable
            state = ("pass" if access in ("open", "on_request") else
                     "block" if access == "unavailable" else "unknown") if reviewed else "unknown"
            conflicting_access = any(
                other["subject"] == claim["subject"]
                and _scope(other["context"], request) != "different"
                and self._claim_state(other)["state"] != "refuted"
                and any(self.sources[e["source_id"]].get("status", "active") == "active"
                        and (e["stance"] == "supports") != bool(other["context"].get("negated"))
                        for e in self.evidence[other["id"]])
                and ((other["context"].get("access_status") == "unavailable") != (access == "unavailable"))
                and other["context"].get("access_status") in ("open", "on_request", "unavailable")
                for other in self.incoming[asset_id, "MAINTAINS"]
            ) if reviewed and access in ("open", "on_request", "unavailable") else False
            if conflicting_access:
                state = "unknown"
            checks = [proof,
                      gate("access", state, "Conflicting availability reports require reconciliation." if conflicting_access else
                           f"Documented access: {access or 'unknown'}; on-request access is not approval.", proof["claim_ids"],
                           researchable=proof.get("researchable", True)),
                      gate("contact", "pass" if reviewed and _url(contact) else "unknown",
                           "A source-backed professional contact route is required.", proof["claim_ids"],
                           researchable=proof.get("researchable", True))]
            if not applicable:
                checks.append(gate("access_scope", "unknown", "The documented access route does not establish access for this request's context.", proof["claim_ids"]))
            routes.append({"organization_id": claim["subject"], "contact_url": contact if reviewed and _url(contact) else None,
                           "access_status": access if reviewed else "unknown", "gates": checks})
        if not routes:
            return [gate("maintainer_evidence", "unknown", "No documented maintainer or access route.")], None, []
        best = min(routes, key=lambda route: _route_key(route["gates"]))
        return best["gates"], {k: v for k, v in best.items() if k != "gates"}, routes

    def _exclusions(self, asset_id: str, request: ResearchRequest) -> list[dict]:
        checks = []
        for claim in self.outgoing[asset_id, "CONTRAINDICATED_FOR"]:
            if claim["object"] != request.disease_id:
                continue
            action = claim["context"].get("action_type")
            scope = _scope(claim["context"], request)
            if scope == "different":
                continue
            proof = self._claim_state(claim)
            if proof["state"] == "refuted":
                continue
            state = "block" if proof["state"] == "supported" and action == "assay_reuse" and scope == "applicable" else "unknown"
            checks.append(gate("exclusion", state,
                               "Documented assay-reuse exclusion." if state == "block" else
                               "Potential exclusion needs review of its evidence or action scope.", proof["claim_ids"]))
        return checks or [gate("exclusion", "pass", "No applicable exclusion recorded in this snapshot; this is not proof of safety.")]

    def _candidates(self, request: ResearchRequest) -> list[str]:
        capable = {c["subject"] for c in self.incoming[request.mechanism_id, "MEASURES"]}
        diseases = {request.disease_id} | {c["subject"] for c in self.incoming[request.mechanism_id, "INVOLVES"]}
        nearby = {c["subject"] for disease in diseases for c in self.incoming[disease, "RELEVANT_TO"]}
        return sorted(capable) + sorted(nearby - capable)

    def _validate_request(self, request: ResearchRequest) -> None:
        for node_id, kind in ((request.disease_id, "Disease"), (request.mechanism_id, "Mechanism")):
            if self.nodes.get(node_id, {}).get("type") != kind:
                raise ValueError(f"{node_id} must identify a {kind} in this snapshot")
        for node_id in request.preferred_asset_ids:
            if self.nodes.get(node_id, {}).get("type") != "Asset":
                raise ValueError(f"Unknown preferred asset: {node_id}")

    def _record(self, asset_id: str, request: ResearchRequest, anchor: dict) -> dict:
        capability, capability_routes = self._capabilities(asset_id, request)
        access, partner, access_routes = self._access(asset_id, request)
        gates = [anchor, *capability, *access, *self._exclusions(asset_id, request)]
        status = ("not_supported" if any(g["state"] == "block" for g in gates) else
                  "needs_clarification" if any(g["state"] == "unknown" for g in gates) else "ready_for_discussion")
        decision_claims = sorted({cid for g in gates for cid in g["claim_ids"]})
        all_claims = set(decision_claims)
        for route in capability_routes + access_routes:
            all_claims.update(cid for g in route["gates"] for cid in g["claim_ids"])
        # Include context paths used for discovery as context, not scientific fit.
        discovery = self.outgoing[asset_id, "RELEVANT_TO"]
        all_claims.update(c["id"] for c in discovery)
        evidence = [e for cid in sorted(all_claims) for e in self.evidence[cid]]
        source_ids = sorted({e["source_id"] for e in evidence})
        identity = asdict(request)
        identity.pop("preferred_asset_ids")
        next_action = {
            "ready_for_discussion": "Ask the documented maintainer to review the protocol, controls, required adaptations and target-disease validation before planning an experiment.",
            "needs_clarification": "Resolve the listed evidence or access gaps before proposing a reuse experiment.",
            "not_supported": "Do not propose reuse under these requirements; inspect the blocker or choose a different assay/context.",
        }[status]
        return {"id": "recommendation:" + digest([POLICY_VERSION, identity, asset_id])[:24],
                "action_type": "assay_reuse", "assertion_type": "inferred", "asset_id": asset_id,
                "asset_label": self.nodes[asset_id]["label"], "status": status, "gates": gates,
                "partner": partner, "next_action": next_action,
                "limits": ["Eligibility is for a feasibility discussion, not established transfer or experimental approval.",
                           "Exact context identifiers are required; broader/narrower ontology equivalence is not inferred."],
                "decision_claim_ids": decision_claims,
                "capability_routes": capability_routes, "access_routes": access_routes,
                "citations": [deepcopy({**e, "source": self.sources[e["source_id"]]}) for e in evidence],
                "dependencies": {"claim_ids": sorted(all_claims), "source_ids": source_ids},
                "preferred": asset_id in request.preferred_asset_ids}

    def assess(self, request: ResearchRequest, budget: SearchBudget | None = None) -> dict:
        budget = budget or SearchBudget()
        self._validate_request(request)
        candidates = self._candidates(request)
        anchor = self._anchor(request)
        records = [self._record(asset, request, anchor) for asset in candidates[:budget.max_candidates]]
        records.sort(key=lambda r: (STATUS_ORDER[r["status"]],
                                   sum(g["state"] == "unknown" for g in r["gates"]),
                                   not r["preferred"], r["asset_id"]))
        for ordinal, record in enumerate(records, 1):
            record["triage_order"] = ordinal
            record["ranking_reasons"] = [record["status"],
                f"{sum(g['state'] == 'unknown' for g in record['gates'])} unresolved gates",
                "User preference applies only after evidence eligibility and gaps."]
        return {"policy_version": POLICY_VERSION, "snapshot_id": self.snapshot,
                "request": asdict(request), "budget": asdict(budget),
                "synthetic": self._bundle["dataset"]["synthetic"],
                "result_id": digest([POLICY_VERSION, self.snapshot, asdict(request), asdict(budget)]),
                "status": "discussion_candidates_found" if any(r["status"] == "ready_for_discussion" for r in records) else "no_ready_candidate",
                "recommendations": records, "candidate_count": len(candidates),
                "candidates_not_assessed": max(0, len(candidates) - len(records)),
                "coverage": deepcopy(self._bundle["coverage"]),
                "ranking_note": "Ordinal triage, not confidence. No citation-count or model-score boost. Candidate truncation can omit better options.",
                "scope_note": "Assay reuse only. The legacy neighbour score is not used. Absence of an eligible candidate is not evidence that none exists."}

    @staticmethod
    def _questions(result: dict, limit: int) -> list[dict]:
        questions = []
        seen = set()
        for record in result["recommendations"]:
            if record["status"] != "needs_clarification":
                continue  # Searching cannot overcome a documented hard mismatch.
            for check in record["gates"]:
                key = (None if check["code"] == "anchor" else record["asset_id"], check["code"])
                if check["state"] != "unknown" or not check.get("researchable", True) or key in seen:
                    continue
                seen.add(key)
                questions.append({"asset_id": key[0], "gate": check["code"],
                                  "request": result["request"], "claim_ids": check["claim_ids"],
                                  "question": check["reason"], "seek": ["supporting evidence", "opposing evidence"],
                                  "decision_effect": "May resolve this gate after source validation and scientific review."})
        priority = {"maintainer_evidence": 0, "access": 0, "contact": 0,
                    "mechanism_step": 1, "readout": 1, "species": 1, "tissue": 1, "stage": 1,
                    "anchor": 2, "capability_evidence": 3}
        questions.sort(key=lambda q: (priority.get(q["gate"], 4),
                                      q["asset_id"] or "", q["gate"]))
        return questions[:limit]

    def _merge_proposals(self, delta: dict, max_claims: int) -> tuple[dict, dict]:
        allowed = ("nodes", "sources", "claims", "evidence")
        if not isinstance(delta, dict) or set(delta) - set(allowed):
            raise ValueError("Retriever must return only nodes, sources, claims and evidence")
        limits = {"claims": max_claims, "nodes": max_claims * 4,
                  "sources": max_claims * 4, "evidence": max_claims * 8}
        normalized = {name: deepcopy(delta.get(name, [])) for name in allowed}
        for name, rows in normalized.items():
            if not isinstance(rows, list) or len(rows) > limits[name] or any(not isinstance(r, dict) for r in rows):
                raise ValueError(f"Invalid or over-budget {name} delta")
        for evidence in normalized["evidence"]:
            evidence["review_status"] = "unreviewed"
        merged = deepcopy(self._bundle)
        existing = {row["id"] for name in COLLECTIONS for row in merged[name]}
        for name, rows in normalized.items():
            for row in rows:
                if not isinstance(row.get("id"), str) or row["id"] in existing:
                    raise ValueError("Retriever cannot replace existing records or repeat identifiers")
                existing.add(row["id"])
            merged[name].extend(rows)
        require_valid_bundle(merged)
        return merged, normalized

    def run(self, request: ResearchRequest, *, budget: SearchBudget | None = None,
            retriever: EvidenceRetriever | None = None) -> dict:
        budget = budget or SearchBudget()
        initial = self.assess(request, budget)
        questions = self._questions(initial, budget.max_followup_queries)
        log = {"rounds": 0, "queries": questions, "status": "not_needed", "new_claims": 0,
               "limits": "Call/record quotas only; the adapter must enforce network timeout and monetary limits."}
        result = initial
        if any(r["status"] == "needs_clarification" for r in initial["recommendations"]):
            log["status"] = "budget_exhausted" if not questions or not budget.max_followup_rounds or not budget.max_new_claims else "not_configured"
        if questions and budget.max_followup_rounds and budget.max_new_claims and retriever is not None:
            log["rounds"] = 1
            try:
                delta = retriever.retrieve(deepcopy(questions), max_claims=budget.max_new_claims)
                merged, normalized = self._merge_proposals(delta, budget.max_new_claims)
                result = RecommendationEngine(merged).assess(request, budget)
                log.update(status="evidence_requires_review" if any(normalized.values()) else "no_new_evidence",
                           new_claims=len(normalized["claims"]))
                result["evidence_proposals"] = normalized
            except Exception as exc:
                # A failing connector must not erase the initial assessment.
                log.update(status="failed", error_type=type(exc).__name__)
        result["followup"] = log
        result["initial_snapshot_id"] = initial["snapshot_id"]
        return result

    def is_current(self, result: dict) -> bool:
        # Whole-snapshot invalidation also catches new opposing claims and missing
        # evidence becoming available. Positive-dependency-only caching misses both.
        return result.get("policy_version") == POLICY_VERSION and result.get("snapshot_id") == self.snapshot

    def reassess(self, previous: dict) -> dict:
        request_data = deepcopy(previous["request"])
        request_data["preferred_asset_ids"] = list(request_data.get("preferred_asset_ids", []))
        result = self.assess(ResearchRequest.from_dict(request_data), SearchBudget(**previous["budget"]))
        before = {r["id"]: r for r in previous["recommendations"]}
        after = {r["id"]: r for r in result["recommendations"]}
        result["previous_result_id"] = previous["result_id"]
        result["changes"] = [{"id": key, "before": before.get(key, {}).get("status"),
                              "after": after.get(key, {}).get("status", "not_in_current_candidate_set")}
                             for key in sorted(before.keys() | after.keys())
                             if before.get(key) != after.get(key)]
        return result

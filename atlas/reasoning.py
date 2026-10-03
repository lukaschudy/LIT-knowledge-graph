"""Conservative, evidence-traceable exploration of a rare-disease graph.

The reasoner deliberately distinguishes a shared biological hypothesis from a
usable research route. It does not estimate clinical compatibility or assign
probabilities; every returned relationship points back to claims and evidence.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


class AtlasReasoner:
    """Explore disease leads and evidenced research assets in a graph bundle."""

    MECHANISM_PREDICATES = {"INVOLVES", "HAS_VARIANT", "HAS_EFFECT"}
    PHENOTYPE_PREDICATES = {"HAS_PHENOTYPE"}

    def __init__(self, bundle: dict[str, Any]):
        self.bundle = bundle or {}
        self.nodes = {n.get("id"): n for n in self.bundle.get("nodes", []) if n.get("id")}
        self.claims = [c for c in self.bundle.get("claims", []) if c.get("id")]
        self.sources = {s.get("id"): s for s in self.bundle.get("sources", []) if s.get("id")}
        self.evidence_by_claim: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self.bundle.get("evidence", []):
            if item.get("claim_id"):
                self.evidence_by_claim[item["claim_id"]].append(item)
        self.coverage = list(self.bundle.get("coverage", []))

    @staticmethod
    def _id(value: Any) -> Any:
        return value.get("id") if isinstance(value, dict) else value

    @classmethod
    def _predicate(cls, claim: dict[str, Any]) -> str:
        return str(claim.get("predicate", "")).upper()

    @classmethod
    def _subject(cls, claim: dict[str, Any]) -> Any:
        return cls._id(claim.get("subject", claim.get("subject_id")))

    @classmethod
    def _object(cls, claim: dict[str, Any]) -> Any:
        return cls._id(claim.get("object", claim.get("object_id")))

    def _claims_between(self, subject: Any = None, predicate: str | None = None,
                        object_id: Any = None) -> list[dict[str, Any]]:
        return [c for c in self.claims
                if (subject is None or self._subject(c) == subject)
                and (predicate is None or self._predicate(c) == predicate.upper())
                and (object_id is None or self._object(c) == object_id)]

    def _node(self, node_id: Any) -> dict[str, Any] | None:
        return self.nodes.get(node_id)

    def _node_type(self, node_id: Any) -> str | None:
        node = self._node(node_id)
        return node.get("type") if node else None

    def _evidence(self, claim: dict[str, Any]) -> list[dict[str, Any]]:
        """Return actual evidence rows enriched with their source, preserving all stances."""
        rows = []
        for item in self.evidence_by_claim.get(claim["id"], []):
            row = dict(item)
            row["source"] = self.sources.get(item.get("source_id"))
            rows.append(row)
        return rows

    def _claim_state(self, claim: dict[str, Any]) -> str:
        """Classify a claim without letting inference or contradiction become support."""
        if self._context(claim).get("negated", False):
            return "negated"
        rows = self._evidence(claim)
        supporting_rows = [row for row in rows if row.get("stance") == "supports" and row.get("source") is not None]
        has_contradiction = any(row.get("stance") == "contradicts" and row.get("source") is not None for row in rows)
        if has_contradiction:
            return "contradicted"
        has_reviewed_support = any(row.get("review_status") in {"machine_checked", "human_reviewed"} for row in supporting_rows)
        has_unreviewed_support = any(row.get("review_status") == "unreviewed" for row in supporting_rows)
        if claim.get("assertion_type") != "reported":
            return "inferred_only" if supporting_rows else "unsupported"
        if has_reviewed_support:
            return "supported"
        if has_unreviewed_support:
            return "review_required"
        return "unsupported"

    def _claim_has_evidence(self, claim: dict[str, Any]) -> bool:
        return bool(self._evidence(claim))

    def _path_evidence(self, claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[Any, Any]] = set()
        for claim in claims:
            for row in self._evidence(claim):
                key = (row.get("id"), claim.get("id"))
                if key not in seen:
                    enriched = dict(row)
                    enriched["claim_id"] = claim.get("id")
                    result.append(enriched)
                    seen.add(key)
        return result

    def _mechanism_paths(self, disease_id: Any) -> list[dict[str, Any]]:
        """All asserted disease-to-mechanism paths, including non-supporting ones."""
        paths = []
        for claim in self._claims_between(disease_id, "INVOLVES"):
            if self._node_type(self._object(claim)) == "Mechanism":
                paths.append({"mechanism_id": self._object(claim), "claims": [claim], "route": "direct"})
        for link in self._claims_between(disease_id, "HAS_VARIANT"):
            variant_id = self._object(link)
            if self._node_type(variant_id) != "Variant":
                continue
            for effect in self._claims_between(variant_id, "HAS_EFFECT"):
                mechanism_id = self._object(effect)
                if self._node_type(mechanism_id) == "Mechanism":
                    paths.append({"mechanism_id": mechanism_id, "claims": [link, effect], "route": "variant"})
        return paths

    def _phenotypes(self, disease_id: Any) -> dict[Any, list[dict[str, Any]]]:
        out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for claim in self.claims:
            if (self._subject(claim) == disease_id
                    and self._predicate(claim) in self.PHENOTYPE_PREDICATES
                    and not self._context(claim).get("negated", False)
                    and self._claim_state(claim) == "supported"
                    and self._node_type(self._object(claim)) == "Phenotype"):
                out[self._object(claim)].append(claim)
        return out

    @staticmethod
    def _context(claim: dict[str, Any]) -> dict[str, Any]:
        context = claim.get("context")
        return context if isinstance(context, dict) else {}

    @staticmethod
    def _effect(claims: Iterable[dict[str, Any]]) -> str:
        # HAS_VARIANT merely connects an entity to a variant. Its context does
        # not state the variant's functional effect; read effect only from the
        # actual effect assertion (or a direct Disease INVOLVES assertion).
        contexts = [c for c in claims if str(c.get("predicate", "")).upper() in {"HAS_EFFECT", "INVOLVES"}]
        effects = {AtlasReasoner._context(c).get("effect", "unknown") for c in contexts}
        return next(iter(effects)) if len(effects) == 1 else "unknown"

    @staticmethod
    def _context_differences(left: Iterable[dict[str, Any]], right: Iterable[dict[str, Any]]) -> list[str]:
        """Flag context mismatches and incompleteness without implying transferability."""
        dimensions = ("species", "tissue", "stage")
        context_claims_left = [c for c in left if str(c.get("predicate", "")).upper() in {"HAS_EFFECT", "INVOLVES"}]
        context_claims_right = [c for c in right if str(c.get("predicate", "")).upper() in {"HAS_EFFECT", "INVOLVES"}]
        left_values = {key: {AtlasReasoner._context(c).get(key) for c in context_claims_left if AtlasReasoner._context(c).get(key) not in (None, "", "unknown")} for key in dimensions}
        right_values = {key: {AtlasReasoner._context(c).get(key) for c in context_claims_right if AtlasReasoner._context(c).get(key) not in (None, "", "unknown")} for key in dimensions}
        diffs = []
        for key in dimensions:
            a, b = left_values[key], right_values[key]
            if a and b and a.isdisjoint(b):
                diffs.append(f"{key}_mismatch: {', '.join(sorted(map(str, a)))} vs {', '.join(sorted(map(str, b)))}; transferability is unestablished")
            elif not a or not b:
                diffs.append(f"{key}_unknown_or_missing; context comparability requires review")
        return diffs

    def _candidate_mechanisms(self, disease_id: Any, candidate_id: Any,
                              disease_paths: list[dict[str, Any]],
                              candidate_paths: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        shared: dict[Any, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for a in disease_paths:
            for b in candidate_paths:
                if a["mechanism_id"] == b["mechanism_id"]:
                    shared[a["mechanism_id"]].append((a, b))
        mechanisms, evaluations = [], []
        for mechanism_id, pairs in shared.items():
            mechanisms.append(self._node(mechanism_id))
            for left, right in pairs:
                claims = left["claims"] + right["claims"]
                states = [self._claim_state(c) for c in claims]
                reasons = []
                effect_a, effect_b = self._effect(left["claims"]), self._effect(right["claims"])
                if effect_a != "unknown" and effect_b != "unknown" and effect_a != effect_b:
                    reasons.append("opposite_effect_contexts_disqualify_shared_mechanism")
                    compatibility = "rejected"
                elif effect_a == "unknown" or effect_b == "unknown":
                    reasons.append("effect_context_missing_or_unknown_requires_review")
                    compatibility = "needs_review"
                else:
                    compatibility = "supported"
                differences = self._context_differences(left["claims"], right["claims"])
                if differences and compatibility == "supported":
                    compatibility = "needs_review"
                    reasons.append("biological_context_differs_or_is_incomplete")
                if "contradicted" in states:
                    reasons.append("mechanistic_path_has_contradicting_evidence")
                    compatibility = "rejected"
                if "negated" in states:
                    reasons.append("negative_assertion_is_not_positive_mechanism_evidence")
                    compatibility = "rejected"
                if "review_required" in states:
                    reasons.append("supporting_evidence_is_unreviewed_and_requires_review")
                    if compatibility != "rejected":
                        compatibility = "needs_review"
                if any(c.get("assertion_type") != "reported" for c in claims) or "inferred_only" in states or "unsupported" in states:
                    reasons.append("mechanistic_path_lacks_reported_supported_evidence")
                    if compatibility != "rejected":
                        compatibility = "rejected"
                evaluations.append({
                    "mechanism_id": mechanism_id,
                    "claims": claims,
                    "status": compatibility,
                    "reasons": reasons,
                    "differences": differences,
                })
        return mechanisms, evaluations

    def _asset_opportunities(self, source_disease: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
        disease_id = candidate["disease"]["id"]
        all_candidate_claims = {c["id"]: c for c in self.claims if c.get("id") in candidate["path_claim_ids"]}
        review_ids = set(candidate.get("review_path_claim_ids", []))
        if candidate["status"] == "supported_lead":
            bridge_ids = set(candidate.get("supported_path_claim_ids", []))
        else:
            bridge_ids = review_ids
        candidate_claims = {cid: all_candidate_claims[cid] for cid in bridge_ids if cid in all_candidate_claims}
        opportunities = []
        for relevance in self._claims_between(predicate="RELEVANT_TO", object_id=disease_id):
            asset_id = self._subject(relevance)
            if self._node_type(asset_id) != "Asset" or self._claim_state(relevance) != "supported":
                continue
            maintainers = []
            owner_claims = []
            for owner in self._claims_between(predicate="MAINTAINS", object_id=asset_id):
                owner_id = self._subject(owner)
                if self._node_type(owner_id) == "Organization" and self._claim_state(owner) == "supported":
                    maintainers.append(self._node(owner_id))
                    owner_claims.append(owner)
            # Carry the biological bridge forward with the asset/owner edges so
            # an opportunity can be audited end to end from the original disease.
            path_claims = list(candidate_claims.values()) + [relevance] + owner_claims
            partners = []
            collaborators = []
            mechanisms = {m.get("id") for m in candidate.get("shared_mechanisms", [])}
            for study in self.claims:
                if self._predicate(study) != "STUDIES" or self._claim_state(study) != "supported":
                    continue
                person_id, studied_id = self._subject(study), self._object(study)
                if self._node_type(person_id) != "Person" or (studied_id != disease_id and studied_id not in mechanisms):
                    continue
                represented = []
                # Representation is an organization -> disease assertion; the
                # researcher link remains a separate, independently evidenced edge.
                for rep in self._claims_between(predicate="REPRESENTS", object_id=disease_id):
                    org_id = self._subject(rep)
                    if self._node_type(org_id) == "Organization" and self._claim_state(rep) == "supported":
                        represented.append((org_id, rep))
                if represented:
                    collaborators.append(self._node(person_id))
                    for org_id, rep in represented:
                        partners.append(self._node(org_id))
                        path_claims.extend([study, rep])
            asset = self._node(asset_id)
            props = asset.get("properties", {}) if asset else {}
            validation_questions = list(props.get("validation_questions", []))
            if not validation_questions:
                validation_questions = ["Does this asset's scope and data context fit the proposed research question?", "What approvals, access conditions, and current availability apply?"]
            contraindications = [c for c in self._claims_between(asset_id, "CONTRAINDICATED_FOR")
                                 if self._object(c) in {source_disease.get("id"), disease_id}
                                 and self._claim_state(c) == "supported"]
            if contraindications:
                rejected_claims = list(candidate_claims.values()) + [relevance] + owner_claims + contraindications
                opportunities.append({
                    "id": f"opportunity:{source_disease['id']}:{disease_id}:{asset_id}",
                    "candidate_id": disease_id,
                    "source_disease": source_disease,
                    "status": "rejected",
                    "reasons": ["asset_has_reported_supported_contraindication_for_source_or_candidate_disease"],
                    "asset": asset,
                    "organizations": self._unique_nodes(maintainers + partners),
                    "collaborators": self._unique_nodes(collaborators),
                    "path_claim_ids": list(dict.fromkeys(c["id"] for c in rejected_claims)),
                    "evidence": self._path_evidence(rejected_claims),
                    "proposal": None,
                    "next_step": "Do not present this asset as a route; ask domain experts to review the contraindication evidence.",
                    "validation_questions": validation_questions,
                    "reuse_scope": props.get("reuse_scope", "unknown; verify with the asset owner"),
                    "differences": list(dict.fromkeys(candidate.get("differences", []))) + list(props.get("limitations", [])),
                })
                continue
            if not maintainers:
                continue
            opportunities.append({
                "id": f"opportunity:{disease_id}:{asset_id}",
                "candidate_id": disease_id,
                "source_disease": source_disease,
                "status": "supported_route" if candidate["status"] == "supported_lead" else "needs_review",
                "asset": asset,
                "organizations": self._unique_nodes(maintainers + partners),
                "collaborators": self._unique_nodes(collaborators),
                "path_claim_ids": list(dict.fromkeys(c["id"] for c in path_claims)),
                "evidence": self._path_evidence(path_claims),
                "proposal": (f"Ask a qualified research team to review whether {asset.get('label', asset_id)} could inform research questions "
                             f"for {source_disease.get('label', source_disease.get('id'))} and {candidate['disease'].get('label', disease_id)}. "
                             "Shared evidence does not establish that the asset transfers between diseases."),
                "next_step": "Have disease-area experts assess the asset, evidence, access conditions, and required approvals before any research use.",
                "validation_questions": validation_questions,
                "reuse_scope": props.get("reuse_scope", "unknown; verify with the asset owner"),
                "differences": list(dict.fromkeys(candidate.get("differences", []))) + list(props.get("limitations", [])),
            })
        return opportunities

    @staticmethod
    def _unique_nodes(nodes: Iterable[dict[str, Any] | None]) -> list[dict[str, Any]]:
        result, seen = [], set()
        for node in nodes:
            if node and node.get("id") not in seen:
                result.append(node)
                seen.add(node.get("id"))
        return result

    def explore(self, disease_id: str) -> dict[str, Any]:
        disease = self._node(disease_id)
        if disease is None or disease.get("type") != "Disease":
            raise ValueError(f"Unknown Disease node: {disease_id}")

        disease_paths = self._mechanism_paths(disease_id)
        disease_phenotypes = self._phenotypes(disease_id)
        phenotype_ids = set(disease_phenotypes)
        candidate_ids = set()
        for other_id, other in self.nodes.items():
            if other.get("type") == "Disease" and other_id != disease_id:
                if any(path["mechanism_id"] == other_path["mechanism_id"]
                       for path in disease_paths for other_path in self._mechanism_paths(other_id)):
                    candidate_ids.add(other_id)
        for phenotype_id in phenotype_ids:
            candidate_ids.update(self._subject(c) for c in self.claims
                                 if self._object(c) == phenotype_id and self._subject(c) != disease_id
                                 and self._node_type(self._subject(c)) == "Disease"
                                 and self._predicate(c) in self.PHENOTYPE_PREDICATES)
        candidate_ids.discard(None)

        candidates = []
        for candidate_id in candidate_ids:
            candidate = self._node(candidate_id)
            candidate_paths = self._mechanism_paths(candidate_id)
            mechanisms, evaluations = self._candidate_mechanisms(disease_id, candidate_id, disease_paths, candidate_paths)
            candidate_phenotypes = self._phenotypes(candidate_id)
            shared_phenotype_ids = phenotype_ids.intersection(candidate_phenotypes)
            shared_phenotypes = [self._node(pid) for pid in sorted(shared_phenotype_ids, key=str) if self._node(pid)]
            path_claims = []
            supported_path_claims = []
            review_path_claims = []
            for evaluation in evaluations:
                path_claims.extend(evaluation["claims"])
                if evaluation["status"] == "supported":
                    supported_path_claims.extend(evaluation["claims"])
                elif evaluation["status"] == "needs_review":
                    review_path_claims.extend(evaluation["claims"])
            for phenotype_id in shared_phenotype_ids:
                path_claims.extend(disease_phenotypes[phenotype_id])
                path_claims.extend(candidate_phenotypes[phenotype_id])
            path_claims = list({c["id"]: c for c in path_claims}.values())
            reasons = []
            statuses = [ev["status"] for ev in evaluations]
            if evaluations and "supported" in statuses:
                status = "supported_lead"
                reasons.append("reported_mechanism_paths_have_supporting_evidence_and_matching_effect")
            elif evaluations and "needs_review" in statuses:
                status = "needs_review"
                reasons.extend(reason for ev in evaluations if ev["status"] == "needs_review" for reason in ev["reasons"])
            elif evaluations:
                status = "rejected"
                reasons.extend(reason for ev in evaluations for reason in ev["reasons"])
            elif shared_phenotypes:
                status = "rejected"
                reasons.append("phenotype_overlap_alone_is_insufficient_without_a_supported_shared_mechanism")
            else:
                continue
            differences = list(dict.fromkeys(diff for ev in evaluations for diff in ev["differences"]))
            if evaluations and "supported" in statuses:
                reasons.extend(reason for ev in evaluations if ev["status"] == "rejected" for reason in ev["reasons"])
            if shared_phenotypes:
                reasons.append("shared_phenotypes_are_context_only_and_do_not_establish_mechanism")
            score = (100 if status == "supported_lead" else 50 if status == "needs_review" else 0)
            score += min(20, 5 * len(mechanisms))
            score += min(5, len(shared_phenotypes))
            candidates.append({
                "disease": candidate,
                "status": status,
                "reasons": list(dict.fromkeys(reasons)),
                "shared_mechanisms": self._unique_nodes(mechanisms),
                "shared_phenotypes": shared_phenotypes,
                "path_claim_ids": [c["id"] for c in path_claims],
                "supported_path_claim_ids": list(dict.fromkeys(c["id"] for c in supported_path_claims)),
                "review_path_claim_ids": list(dict.fromkeys(c["id"] for c in review_path_claims)),
                "path_assessments": [{
                    "mechanism": self._node(ev["mechanism_id"]),
                    "status": ev["status"],
                    "claim_ids": list(dict.fromkeys(c["id"] for c in ev["claims"])),
                    "evidence": self._path_evidence(ev["claims"]),
                    "reasons": ev["reasons"],
                    "differences": ev["differences"],
                } for ev in evaluations],
                "evidence": self._path_evidence(path_claims),
                "differences": differences,
                "rank": score,
                "rank_explanation": f"Non-probability ordering score: {score} (status base {100 if status == 'supported_lead' else 50 if status == 'needs_review' else 0}; up to 20 for distinct shared mechanisms; up to 5 for phenotype overlap).",
            })

        order = {"supported_lead": 0, "needs_review": 1, "rejected": 2}
        candidates.sort(key=lambda item: (order[item["status"]], -item["rank"], str(item["disease"].get("label", "")), str(item["disease"].get("id", ""))))
        total_candidates = len(candidates)
        for index, candidate in enumerate(candidates, 1):
            candidate["rank"] = index
            candidate["rank_explanation"] = (f"Ordinal review priority {index} of {total_candidates}, ordered by evidence status, "
                                             "then shared mechanism and phenotype counts and disease label. This is not a probability.")

        opportunities = []
        for candidate in candidates:
            if candidate["status"] in {"supported_lead", "needs_review"}:
                opportunities.extend(self._asset_opportunities(disease, candidate))

        relevant_coverage = [c for c in self.coverage if c.get("entity_id") == disease_id]
        gaps = []
        if not relevant_coverage:
            gaps.append("No source coverage record is available for this disease; absence of a lead is not evidence of absence.")
        for record in relevant_coverage:
            if record.get("status") != "searched":
                gaps.append(f"Source {record.get('source_id', 'unknown')} coverage is {record.get('status', 'unknown')} for {record.get('scope', 'unspecified scope')}.")
        if any(c["status"] == "rejected" for c in candidates):
            gaps.append("Some nearby candidates were excluded because evidence was insufficient, inferred, contradicted, or phenotype-only.")
        if not opportunities:
            gaps.append("No fully evidenced asset-and-maintainer route was found; do not infer a contact, asset availability, or study eligibility.")
        questions = ["Which disease mechanisms and effect contexts are confirmed by disease-area experts?", "Are species, tissue, and developmental-stage contexts comparable for the intended research question?"]
        if not opportunities:
            questions.append("Which current, evidence-backed research assets and accountable maintainers should be evaluated?")
        else:
            questions.append("What permissions, limitations, and validation steps apply to the identified asset?")

        metadata = self.bundle.get("metadata", self.bundle.get("dataset", {}))
        synthetic = bool(metadata.get("synthetic", False)) if isinstance(metadata, dict) else False
        has_supported_route = any(item.get("status") == "supported_route" for item in opportunities)
        if any(item.get("status") == "rejected" for item in opportunities):
            gaps.append("A linked asset was excluded because it has a reported, supported contraindication for the source or candidate disease.")

        return {
            "disease": disease,
            "synthetic": synthetic,
            "status": "leads_found" if has_supported_route else "no_supported_route",
            "candidates": candidates,
            "opportunities": opportunities,
            "coverage": relevant_coverage,
            "gaps": list(dict.fromkeys(gaps)),
            "next_questions": questions,
            "ranking_note": "Ranks are deterministic review priorities based on evidence status and graph overlap. They are not probabilities, clinical predictions, treatment recommendations, or assertions of cross-species transferability.",
        }

"""Explainable exploratory clustering; membership never grants action eligibility."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import heapq
from .recommendations import RecommendationEngine


def discover(bundle: dict, *, threshold: float = 0.3) -> dict:
    """Complete-link clusters on typed, weighted Jaccard feature sets.

    Complete linkage avoids joining distant diseases through one bridge. Weights
    are explicit design choices, not learned probabilities. Unreviewed reported
    features can generate a candidate neighborhood but are visibly provisional.
    """
    if type(threshold) not in (int, float) or not 0 < threshold <= 1:
        raise ValueError('Discovery threshold must be in (0, 1]')
    engine = RecommendationEngine(bundle)
    disease_ids = sorted(n['id'] for n in bundle['nodes'] if n['type'] == 'Disease')
    if len(disease_ids) > 500:
        raise ValueError('Select a disease slice of at most 500 nodes for local clustering')
    features = {did: defaultdict(set) for did in disease_ids}
    provenance = defaultdict(set)
    for claim in bundle['claims']:
        disease = claim['subject']
        if disease not in features or claim['assertion_type'] != 'reported' or claim['context'].get('negated'):
            continue
        active_evidence = [e for e in engine.evidence[claim['id']]
                           if e['stance'] == 'supports'
                           and engine.sources[e['source_id']].get('status', 'active') == 'active']
        if not active_evidence or engine._claim_state(claim)['state'] == 'refuted':
            continue
        additions = []
        if claim['predicate'] == 'INVOLVES':
            additions.append(('mechanism', claim['object']))
            if claim['context'].get('mechanism_step'):
                additions.append(('step', claim['object'] + ':' + claim['context']['mechanism_step']))
        elif claim['predicate'] == 'HAS_PHENOTYPE':
            additions.append(('phenotype', claim['object']))
        for kind, value in additions:
            features[disease][kind].add(value)
            provenance[disease, kind, value].add(claim['id'])
    weights = {'mechanism': .35, 'step': .45, 'phenotype': .20}
    links, scores = [], {}
    for left, right in combinations(disease_ids, 2):
        score, reasons, claim_ids = 0., [], set()
        for kind, weight in weights.items():
            a, b = features[left][kind], features[right][kind]
            shared = a & b
            if shared:
                score += weight * len(shared) / len(a | b)
                reasons.append({'feature': kind, 'shared': sorted(shared), 'weight': weight})
                for value in shared:
                    claim_ids.update(provenance[left, kind, value] | provenance[right, kind, value])
        scores[left, right] = score
        if score:
            links.append({'source': left, 'target': right, 'similarity': round(score, 4),
                          'reasons': reasons, 'claim_ids': sorted(claim_ids),
                          'reviewed': all(engine._claim_state(engine.claims[cid])['state'] == 'supported' for cid in claim_ids)})
    groups = _complete_link_groups(disease_ids, scores, threshold)
    return {'method': 'Complete-link clustering of typed graph features using weighted Jaccard overlap',
            'threshold': threshold, 'weights': weights,
            'groups': [{'id': 'cluster:' + str(i + 1), 'disease_ids': list(group),
                        'label': ' · '.join(engine.nodes[did]['label'] for did in group)} for i, group in enumerate(groups)],
            'links': links, 'note': 'Exploratory research neighborhoods, not shared treatments or assay compatibility. Unreviewed features remain provisional; absent features are unknown. Weights and threshold are uncalibrated design choices.'}


def _complete_link_groups(identifiers, scores, threshold):
    """Cache linkage distances; merging A/B uses min(distance(A,C),distance(B,C)).

    Only above-threshold pairs can ever merge. Heap entries retain compact
    minimum-member tie keys: for disjoint clusters, these order candidate unions
    exactly like comparing every sorted member. Stale entries are skipped.
    """
    groups = {i: (identifier,) for i, identifier in enumerate(identifiers)}
    neighbors = {i: {} for i in groups}
    queue = []

    def connect(left, right, score):
        neighbors[left][right] = score
        neighbors[right][left] = score
        first, second = sorted((groups[left][0], groups[right][0]))
        heapq.heappush(queue, (-score, first, second, left, right))

    for left, right in combinations(groups, 2):
        score = scores[tuple(sorted((groups[left][0], groups[right][0])))]
        if score >= threshold:
            connect(left, right, score)
    next_id = len(groups)
    while queue:
        _, _, _, left, right = heapq.heappop(queue)
        if left not in groups or right not in groups:
            continue
        # A complete-link pair must meet the threshold to both merged clusters.
        common = neighbors[left].keys() & neighbors[right].keys()
        linked = {other: min(neighbors[left][other], neighbors[right][other]) for other in common}
        combined = tuple(sorted(groups.pop(left) + groups.pop(right)))
        for old in (left, right):
            for other in neighbors.pop(old):
                if other in neighbors:
                    neighbors[other].pop(old, None)
        groups[next_id] = combined
        neighbors[next_id] = {}
        for other, score in linked.items():
            connect(next_id, other, score)
        next_id += 1
    return sorted(groups.values())

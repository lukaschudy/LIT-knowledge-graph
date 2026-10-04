"""Explainable exploratory clustering; membership never grants action eligibility."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from .recommendations import RecommendationEngine


def discover(bundle: dict, *, threshold: float = 0.3) -> dict:
    """Complete-link clusters on typed, weighted Jaccard feature sets.

    Complete linkage avoids joining distant diseases through one bridge. Weights
    are explicit design choices, not learned probabilities. Unreviewed reported
    features can generate a candidate neighborhood but are visibly provisional.
    """
    if not 0 < threshold <= 1:
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
        if engine._claim_state(claim)['state'] == 'refuted':
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
    groups = [(did,) for did in disease_ids]
    while True:
        choices = []
        for i, j in combinations(range(len(groups)), 2):
            minimum = min(scores[tuple(sorted((a, b)))] for a in groups[i] for b in groups[j])
            if minimum >= threshold:
                choices.append((-minimum, tuple(sorted(groups[i] + groups[j])), i, j))
        if not choices:
            break
        _, combined, i, j = min(choices)
        groups = [group for k, group in enumerate(groups) if k not in (i, j)] + [combined]
        groups.sort()
    return {'method': 'Complete-link clustering of typed graph features using weighted Jaccard overlap',
            'threshold': threshold, 'weights': weights,
            'groups': [{'id': 'cluster:' + str(i + 1), 'disease_ids': list(group),
                        'label': ' · '.join(engine.nodes[did]['label'] for did in group)} for i, group in enumerate(groups)],
            'links': links, 'note': 'Exploratory research neighborhoods, not shared treatments or assay compatibility. Unreviewed features remain provisional; absent features are unknown. Weights and threshold are uncalibrated design choices.'}

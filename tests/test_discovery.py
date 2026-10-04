"""Complete-link results must retain scientific and deterministic semantics."""
from copy import deepcopy
from itertools import combinations
import random
import unittest

from atlas.discovery import discover, _complete_link_groups
from tests.test_recommendations import fixture


def exhaustive_groups(ids, scores, threshold):
    """Independent small-input reference matching the stated linkage policy."""
    groups = [(item,) for item in ids]
    while True:
        candidates = []
        for i, j in combinations(range(len(groups)), 2):
            score = min(scores[tuple(sorted((a, b)))] for a in groups[i] for b in groups[j])
            if score >= threshold:
                candidates.append((-score, tuple(sorted(groups[i] + groups[j])), i, j))
        if not candidates:
            return sorted(groups)
        _, merged, i, j = min(candidates)
        groups = sorted([g for k, g in enumerate(groups) if k not in (i, j)] + [merged])


class DiscoveryTests(unittest.TestCase):
    def test_cached_linkage_matches_exhaustive_reference_including_ties(self):
        rng = random.Random(814)
        for count in range(1, 18):
            ids = [f'd{i:02}' for i in range(count)]
            for run in range(12):
                scores = {pair: rng.choice([0, .2, .3, .5, .8, 1]) for pair in combinations(ids, 2)}
                threshold = rng.choice([.2, .3, .5, 1])
                with self.subTest(count=count, run=run):
                    expected = exhaustive_groups(ids, scores, threshold)
                    self.assertEqual(_complete_link_groups(ids, scores, threshold), expected)
                    self.assertEqual(_complete_link_groups(list(reversed(ids)), scores, threshold), expected)

    def test_bridge_does_not_merge_distant_members(self):
        ids = ['a', 'b', 'c']
        scores = {('a', 'b'): .8, ('a', 'c'): .1, ('b', 'c'): .8}
        self.assertEqual(_complete_link_groups(ids, scores, .3), [('a', 'b'), ('c',)])

    def test_retracted_only_features_cannot_create_provisional_cluster_links(self):
        bundle = fixture()
        self.assertTrue(discover(bundle)['links'])
        for source in bundle['sources']:
            source['status'] = 'retracted'
        result = discover(bundle)
        self.assertEqual(result['links'], [])
        self.assertTrue(all(len(group['disease_ids']) == 1 for group in result['groups']))

    def test_active_unreviewed_features_remain_visible_as_provisional(self):
        bundle = fixture()
        for evidence in bundle['evidence']:
            evidence['review_status'] = 'unreviewed'
        result = discover(bundle)
        self.assertTrue(result['links'])
        self.assertFalse(any(link['reviewed'] for link in result['links']))
        reverse = deepcopy(bundle)
        for key in ('nodes', 'claims', 'evidence', 'sources'):
            reverse[key].reverse()
        self.assertEqual(discover(reverse), result)

    def test_invalid_thresholds_fail_with_explicit_validation(self):
        for threshold in (True, None, '0.3', float('nan'), 0, 1.1):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                discover(fixture(), threshold=threshold)

    def test_only_active_counterevidence_cannot_create_positive_features(self):
        bundle = fixture()
        for source in bundle['sources']:
            source['status'] = 'retracted'
        active = deepcopy(bundle['sources'][0])
        active.update(id='active-counter-source', status='active')
        bundle['sources'].append(active)
        for evidence in list(bundle['evidence']):
            counter = deepcopy(evidence)
            counter.update(id='counter-' + evidence['id'], source_id=active['id'],
                           stance='contradicts', review_status='unreviewed')
            bundle['evidence'].append(counter)
        self.assertEqual(discover(bundle)['links'], [])

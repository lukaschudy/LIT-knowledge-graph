"""Adversarial decision cases, using exclusively fictional evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from atlas.model import require_valid_bundle, ValidationError
from atlas.recommendations import RecommendationEngine, ResearchRequest, SearchBudget
from atlas.server import create_server
from atlas.store import GraphStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'data' / 'fixtures'


def fixture():
    return json.loads((FIXTURES / 'recommendation-demo.json').read_text())


def request():
    return ResearchRequest.from_dict(json.loads((FIXTURES / 'recommendation-request.json').read_text()))


def record(result, asset='assay-fit'):
    return next(r for r in result['recommendations'] if r['asset_id'] == 'demo:' + asset)


def claim(bundle, suffix):
    return next(c for c in bundle['claims'] if c['id'] == 'demo:' + suffix)


def evidence(bundle, suffix):
    return next(e for e in bundle['evidence'] if e['claim_id'] == 'demo:' + suffix)


def clone_claim(bundle, suffix, new_id, *, context=None):
    c = deepcopy(claim(bundle, suffix)); c['id'] = 'demo:' + new_id
    if context is not None: c['context'] = context
    e = deepcopy(evidence(bundle, suffix)); e.update(id=c['id'] + '-evidence', claim_id=c['id'])
    bundle['claims'].append(c); bundle['evidence'].append(e)
    return c, e


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.bundle = fixture()
        self.request = request()

    def assess(self):
        return RecommendationEngine(self.bundle).assess(self.request)

    def test_expected_decisions_and_traceable_action(self):
        result = self.assess()
        self.assertTrue(result['synthetic'])
        self.assertEqual({r['asset_id']: r['status'] for r in result['recommendations']}, {
            'demo:assay-fit': 'ready_for_discussion', 'demo:assay-gap': 'needs_clarification',
            'demo:assay-wrong-step': 'not_supported', 'demo:assay-excluded': 'not_supported'})
        good = record(result)
        self.assertEqual(good['assertion_type'], 'inferred')
        self.assertEqual(good['partner']['organization_id'], 'demo:lab')
        self.assertIn('target-disease validation', good['next_action'])
        self.assertTrue(set(good['decision_claim_ids']) <= {e['claim_id'] for e in good['citations']})

    def test_same_pathway_and_loss_of_function_cannot_rescue_wrong_step(self):
        bad = record(self.assess(), 'assay-wrong-step')
        self.assertEqual(bad['status'], 'not_supported')
        self.assertTrue(any(g['code'] == 'mechanism_step' and g['state'] == 'block' for g in bad['gates']))

    def test_donor_effect_does_not_determine_measurement_capability(self):
        claim(self.bundle, 'neighbor-step')['context']['effect'] = 'gain_of_function'
        self.assertEqual(record(self.assess())['status'], 'ready_for_discussion')

    def test_anchor_missing_or_review_pending_is_not_ready(self):
        for field in ('mechanism_step',):
            claim(self.bundle, 'anchor-step')['context'].pop(field)
        self.assertEqual(record(self.assess())['status'], 'needs_clarification')

    def test_missing_maintainer_is_visible_not_silently_dropped(self):
        self.bundle['claims'] = [c for c in self.bundle['claims'] if c['id'] != 'demo:assay-fit-owner']
        self.bundle['evidence'] = [e for e in self.bundle['evidence'] if e['claim_id'] != 'demo:assay-fit-owner']
        result = record(self.assess())
        self.assertEqual(result['status'], 'needs_clarification')

    def test_followup_skips_review_only_and_dependent_capability_questions(self):
        for suffix in ('anchor-step', 'assay-fit-capability'):
            evidence(self.bundle, suffix)['review_status'] = 'machine_checked'
        result = self.assess()
        fit = record(result)
        self.assertFalse(next(g for g in fit['gates'] if g['code'] == 'anchor')['researchable'])
        self.assertFalse(next(g for g in fit['gates'] if g['code'] == 'readout')['researchable'])
        questions = RecommendationEngine._questions(result, 10)
        self.assertFalse(any(q['asset_id'] == 'demo:assay-fit' for q in questions))
        # The separate assay still has a genuinely undocumented tissue field.
        self.assertIn(('demo:assay-gap', 'tissue'), [(q['asset_id'], q['gate']) for q in questions])

    def test_followup_prioritizes_missing_access_and_context_facts(self):
        self.bundle['claims'] = [c for c in self.bundle['claims'] if c['id'] != 'demo:assay-fit-owner']
        self.bundle['evidence'] = [e for e in self.bundle['evidence'] if e['claim_id'] != 'demo:assay-fit-owner']
        result = self.assess()
        questions = RecommendationEngine._questions(result, 3)
        self.assertEqual(questions[0]['gate'], 'maintainer_evidence')
        self.assertIn(('demo:assay-gap', 'tissue'), [(q['asset_id'], q['gate']) for q in questions])
        self.assertIsNone(record(result)['partner'])

    def test_scoped_anchor_and_assay_stage_cannot_be_generalized_silently(self):
        claim(self.bundle, 'anchor-step')['context']['species'] = 'mouse'
        self.assertEqual(record(self.assess())['status'], 'needs_clarification')
        self.bundle = fixture()
        claim(self.bundle, 'assay-fit-capability')['context']['stage'] = 'mature'
        self.assertEqual(record(self.assess())['status'], 'needs_clarification')
        self.request = replace(self.request, stage='mature')
        self.assertEqual(record(self.assess())['status'], 'ready_for_discussion')

    def test_machine_check_or_unversioned_review_is_insufficient(self):
        for mode in ('machine_checked', 'unreviewed', 'missing_version'):
            with self.subTest(mode=mode):
                b = fixture(); e = evidence(b, 'assay-fit-capability')
                if mode == 'missing_version': e.pop('source_version')
                else: e['review_status'] = mode
                self.assertEqual(record(RecommendationEngine(b).assess(self.request))['status'], 'needs_clarification')

    def test_opposition_is_preserved_as_dispute_not_automatic_falsehood(self):
        counter = deepcopy(evidence(self.bundle, 'assay-fit-capability'))
        counter.update(id='demo:opposition', stance='contradicts', review_status='unreviewed')
        self.bundle['evidence'].append(counter)
        r = record(self.assess())
        self.assertEqual(r['status'], 'needs_clarification')
        self.assertIn('demo:opposition', {e['id'] for e in r['citations']})

    def test_negation_on_separate_equivalent_or_broader_claim_cannot_be_hidden(self):
        for broad in (False, True):
            with self.subTest(broad=broad):
                b = fixture()
                context = {} if broad else deepcopy(claim(b, 'assay-fit-capability')['context'])
                context['negated'] = True
                clone_claim(b, 'assay-fit-capability', 'separate-negation', context=context)
                r = record(RecommendationEngine(b).assess(self.request))
                self.assertEqual(r['status'], 'needs_clarification')
                self.assertIn('demo:separate-negation', r['decision_claim_ids'])

    def test_cannot_assemble_context_from_incompatible_protocols(self):
        c = claim(self.bundle, 'assay-fit-capability')
        c['context']['tissue'] = 'neuron'
        clone_claim(self.bundle, 'assay-fit-capability', 'other-protocol',
                    context={**c['context'], 'tissue': 'fibroblast', 'species': 'mouse'})
        self.assertEqual(record(self.assess())['status'], 'not_supported')

    def test_alternative_documented_protocol_can_work_but_mismatch_remains_visible(self):
        clone_claim(self.bundle, 'assay-fit-capability', 'other-protocol',
                    context={**claim(self.bundle, 'assay-fit-capability')['context'], 'species': 'mouse'})
        r = record(self.assess())
        self.assertEqual(r['status'], 'ready_for_discussion')
        self.assertEqual(len(r['capability_routes']), 2)

    def test_preferences_cannot_promote_blocked_candidate(self):
        normal = self.assess()
        self.request = replace(self.request, preferred_asset_ids=('demo:assay-wrong-step',))
        changed = self.assess()
        self.assertEqual(changed['recommendations'][0]['asset_id'], 'demo:assay-fit')
        self.assertEqual(record(normal)['id'], record(changed)['id'])

    def test_duplicated_citations_do_not_increase_rank(self):
        initial = self.assess()
        for i in range(20):
            e = deepcopy(evidence(self.bundle, 'assay-wrong-step-capability'))
            e['id'] = f'demo:duplicate-{i}'; self.bundle['evidence'].append(e)
        self.assertEqual([r['asset_id'] for r in initial['recommendations']],
                         [r['asset_id'] for r in self.assess()['recommendations']])

    def test_exclusion_is_scoped_to_action_and_context(self):
        exclusion = claim(self.bundle, 'assay-excluded-exclusion')
        exclusion['context']['action_type'] = 'therapy'
        self.assertEqual(record(self.assess(), 'assay-excluded')['status'], 'ready_for_discussion')
        exclusion['context'] = {'action_type': 'assay_reuse', 'species': 'mouse'}
        self.assertEqual(record(self.assess(), 'assay-excluded')['status'], 'ready_for_discussion')
        exclusion['context'] = {}
        self.assertEqual(record(self.assess(), 'assay-excluded')['status'], 'needs_clarification')

    def test_unknown_exclusion_scope_cannot_silently_disappear(self):
        for key, value in (('species', ''), ('tissue', 'unknown'), ('action_type', ''),
                           ('readout', 'n/a'), ('stage', 'not reported'), ('variant_id', 'specific-variant')):
            with self.subTest(key=key, value=value):
                b = fixture()
                claim(b, 'assay-excluded-exclusion')['context'] = {'action_type': 'assay_reuse', key: value}
                result = record(RecommendationEngine(b).assess(self.request), 'assay-excluded')
                self.assertEqual(result['status'], 'needs_clarification')
                self.assertEqual(next(g for g in result['gates'] if g['code'] == 'exclusion')['state'], 'unknown')

    def test_capability_scope_and_null_like_values_cannot_promote_readiness(self):
        for key, value in (('variant_id', 'specific-variant'), ('variant_id', ''), ('action_type', 'therapy'),
                           ('action_type', 'unknown'), ('species', 'unknown'), ('tissue', 'null'), ('stage', '')):
            with self.subTest(key=key, value=value):
                b = fixture()
                claim(b, 'assay-fit-capability')['context'][key] = value
                self.assertEqual(record(RecommendationEngine(b).assess(self.request))['status'], 'needs_clarification')
        b = fixture()
        claim(b, 'assay-fit-capability')['context']['species'] = 'unknown'
        self.assertEqual(record(RecommendationEngine(b).assess(replace(self.request, species='unknown')))['status'], 'needs_clarification')

    def test_access_is_bound_to_the_requested_context(self):
        for key, value in (('species', 'mouse'), ('species', ''), ('action_type', 'therapy'),
                           ('variant_id', 'specific-variant'), ('stage', 'mature')):
            with self.subTest(key=key, value=value):
                b = fixture()
                claim(b, 'assay-fit-owner')['context'][key] = value
                result = record(RecommendationEngine(b).assess(self.request))
                self.assertEqual(result['status'], 'needs_clarification')
                self.assertIsNone(result['partner']['contact_url'])
        claim(self.bundle, 'assay-fit-owner')['context']['species'] = self.request.species
        self.assertEqual(record(self.assess())['status'], 'ready_for_discussion')

    def test_pending_access_counterevidence_is_retained_but_inactive_scope_is_not(self):
        for status, expected in (('active', 'needs_clarification'), ('retracted', 'ready_for_discussion'),
                                 ('superseded', 'ready_for_discussion')):
            with self.subTest(status=status):
                b = fixture()
                c, e = clone_claim(b, 'assay-fit-owner', 'pending-unavailable',
                                  context={**claim(b, 'assay-fit-owner')['context'], 'access_status': 'unavailable'})
                source = deepcopy(next(s for s in b['sources'] if s['id'] == e['source_id']))
                source.update(id='demo:pending-source', status=status)
                b['sources'].append(source)
                e.update(source_id=source['id'], review_status='unreviewed')
                self.assertEqual(record(RecommendationEngine(b).assess(self.request))['status'], expected)
        clone_claim(self.bundle, 'assay-fit-owner', 'mouse-unavailable',
                    context={**claim(self.bundle, 'assay-fit-owner')['context'], 'access_status': 'unavailable', 'species': 'mouse'})
        self.assertEqual(record(self.assess())['status'], 'ready_for_discussion')

    def test_unknown_qualifier_cannot_hide_separate_negated_counterclaim(self):
        context = {**claim(self.bundle, 'assay-fit-capability')['context'], 'species': 'unknown', 'negated': True}
        clone_claim(self.bundle, 'assay-fit-capability', 'pending-scope-negation', context=context)
        self.assertEqual(record(self.assess())['status'], 'needs_clarification')

    def test_unusable_contact_urls_cannot_make_assay_ready(self):
        for url in ('https://:secret@example.org', 'https://example.org:bad',
                    'https://example .org', 'https://example.org/path\nnext'):
            with self.subTest(url=url):
                claim(self.bundle, 'assay-fit-owner')['context']['contact_url'] = url
                assessment = record(self.assess())
                self.assertEqual(assessment['status'], 'needs_clarification')
                self.assertIsNone(assessment['partner']['contact_url'])
                self.assertEqual(next(g for g in assessment['gates'] if g['code']=='contact')['state'], 'unknown')

    def test_conflicting_availability_does_not_cherry_pick_open_access(self):
        clone_claim(self.bundle, 'assay-fit-owner', 'owner-unavailable',
                    context={**claim(self.bundle, 'assay-fit-owner')['context'], 'access_status': 'unavailable'})
        self.assertEqual(record(self.assess())['status'], 'needs_clarification')

    def test_source_revision_or_retraction_downgrades_and_invalidates(self):
        initial = self.assess()
        for modification in ({'version':'fixture-v2'}, {'status':'retracted'}, {'status':'superseded'}):
            with self.subTest(modification=modification):
                b = fixture(); b['sources'][1].update(modification)
                engine = RecommendationEngine(b)
                self.assertFalse(engine.is_current(initial))
                updated = engine.reassess(initial)
                self.assertEqual(record(updated)['status'], 'needs_clarification')
                self.assertTrue(updated['changes'])

    def test_new_exclusion_invalidates_even_without_old_positive_dependency(self):
        initial = self.assess()
        c, _ = clone_claim(self.bundle, 'assay-excluded-exclusion', 'new-exclusion')
        c['subject'] = 'demo:assay-fit'
        engine = RecommendationEngine(self.bundle)
        self.assertFalse(engine.is_current(initial))
        self.assertEqual(record(engine.reassess(initial))['status'], 'not_supported')

    def test_order_invariance_and_snapshot_isolation(self):
        engine = RecommendationEngine(self.bundle); initial = engine.assess(self.request)
        for collection in ('nodes','sources','claims','evidence','coverage'): self.bundle[collection].reverse()
        self.assertEqual(initial, self.assess())
        self.bundle['sources'][0]['version'] = 'mutated'
        record(initial)['citations'][0]['source']['version'] = 'also-mutated'
        self.assertEqual(record(engine.assess(self.request))['status'], 'ready_for_discussion')
        self.assertNotEqual(record(engine.assess(self.request))['citations'][0]['source']['version'], 'also-mutated')

    def test_no_candidate_and_truncation_are_honest(self):
        self.bundle['claims'] = [c for c in self.bundle['claims'] if c['predicate'] not in ('MEASURES','RELEVANT_TO')]
        ids = {c['id'] for c in self.bundle['claims']}
        self.bundle['evidence'] = [e for e in self.bundle['evidence'] if e['claim_id'] in ids]
        result = self.assess()
        self.assertEqual(result['recommendations'], [])
        self.assertEqual(result['status'], 'no_ready_candidate')
        result = RecommendationEngine(fixture()).assess(self.request, SearchBudget(max_candidates=1))
        self.assertEqual(result['candidates_not_assessed'], 3)

    def test_validation_rejects_wrong_endpoint_types_and_malformed_qualifiers(self):
        for bad in ('wrong_endpoint','bad_context','bad_version','bad_status'):
            with self.subTest(bad=bad):
                b = fixture()
                if bad == 'wrong_endpoint': claim(b, 'assay-fit-capability')['subject'] = 'demo:anchor'
                if bad == 'bad_context': claim(b, 'assay-fit-capability')['context']['readout'] = []
                if bad == 'bad_version': b['sources'][0]['version'] = False
                if bad == 'bad_status': b['sources'][0]['status'] = []
                with self.assertRaises(ValidationError): RecommendationEngine(b)
        with self.assertRaises(ValueError): ResearchRequest.from_dict({'unexpected':True})
        with self.assertRaises(ValueError): SearchBudget(max_candidates=True)
        with self.assertRaises(ValueError): SearchBudget(max_followup_rounds=2)


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.engine = RecommendationEngine(fixture())
        self.delta = json.loads((FIXTURES / 'recommendation-proposals.json').read_text())
        self.calls = []

    def retriever(self, value=None, error=None):
        parent = self
        class Retriever:
            def retrieve(self, questions, *, max_claims):
                parent.calls.append((questions, max_claims))
                if error: raise error
                return deepcopy(parent.delta if value is None else value)
        return Retriever()

    def test_one_followup_preserves_review_boundary_even_if_adapter_claims_review(self):
        initial = self.engine.assess(request())
        result = self.engine.run(request(), retriever=self.retriever())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.calls[0][0]), 1)
        self.assertEqual(self.calls[0][0][0]['seek'], ['supporting evidence','opposing evidence'])
        self.assertEqual(result['followup']['status'], 'evidence_requires_review')
        self.assertEqual(record(result, 'assay-gap')['status'], 'needs_clarification')
        self.assertEqual(result['evidence_proposals']['evidence'][0]['review_status'], 'unreviewed')
        self.assertEqual(self.engine.assess(request()), initial)

    def test_offline_review_can_complete_the_loop(self):
        result = self.engine.run(request(), retriever=self.retriever())
        b = fixture()
        for name, rows in result['evidence_proposals'].items(): b[name].extend(rows)
        evidence(b, 'assay-gap-new-capability')['review_status'] = 'human_reviewed'
        refreshed = RecommendationEngine(b).reassess(result)
        self.assertEqual(record(refreshed, 'assay-gap')['status'], 'ready_for_discussion')

    def test_zero_budget_or_only_hard_mismatches_skips_search(self):
        for budget in (SearchBudget(max_followup_queries=0), SearchBudget(max_followup_rounds=0), SearchBudget(max_new_claims=0)):
            result = self.engine.run(request(), budget=budget, retriever=self.retriever())
            self.assertEqual(result['followup']['status'], 'budget_exhausted')
        self.assertEqual(self.calls, [])
        self.engine.run(replace(request(), species='mouse'), retriever=self.retriever())
        self.assertEqual(self.calls, [])

    def test_connector_failure_or_invalid_delta_returns_original_assessment(self):
        original = self.engine.assess(request())
        bad_deltas = [None, {'sources':[fixture()['sources'][0]]}, {'claims':[self.delta['claims'][0]]}, {'coverage':[]}]
        for delta in bad_deltas:
            result = self.engine.run(request(), retriever=self.retriever(value=delta, error=TimeoutError() if delta is None else None))
            self.assertEqual(result['followup']['status'], 'failed')
            self.assertEqual(result['recommendations'], original['recommendations'])
        result = self.engine.run(request(), budget=SearchBudget(max_new_claims=1),
                                 retriever=self.retriever(value={'claims':self.delta['claims'] * 2}))
        self.assertEqual(result['followup']['status'], 'failed')

    def test_pending_opposition_can_downgrade_an_existing_ready_candidate(self):
        e = deepcopy(evidence(fixture(), 'assay-fit-capability'))
        e.update(id='demo:new-opposition', stance='contradicts')
        result = self.engine.run(request(), retriever=self.retriever(value={'evidence':[e]}))
        self.assertEqual(record(result)['status'], 'needs_clarification')


class IntegrationTests(unittest.TestCase):
    def test_cli_ingest_recommend_and_reassess_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, saved = str(Path(tmp)/'atlas.sqlite'), str(Path(tmp)/'result.json')
            def run(*args):
                return subprocess.run([sys.executable,'-m','atlas',*args],cwd=ROOT,text=True,capture_output=True,check=True)
            run('ingest',str(FIXTURES/'recommendation-demo.json'),'--db',db)
            run('recommend',str(FIXTURES/'recommendation-request.json'),'--db',db,'--output',saved,
                '--followup-proposals',str(FIXTURES/'recommendation-proposals.json'))
            result = json.loads(Path(saved).read_text())
            self.assertEqual(result['followup']['rounds'], 1)
            refreshed = json.loads(run('reassess',saved,'--db',db).stdout)
            self.assertEqual(record(refreshed)['status'], 'ready_for_discussion')

    def test_read_only_http_uses_the_new_decision_engine(self):
        with GraphStore() as store:
            store.load_bundle(fixture())
            server = create_server(store, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                host, port = server.server_address
                base = f'http://{host}:{port}/api/recommend'
                q = json.loads((FIXTURES/'recommendation-request.json').read_text())
                with urlopen(base+'?'+urlencode(q),timeout=2) as response:
                    result = json.load(response)
                self.assertEqual(record(result)['status'], 'ready_for_discussion')
                self.assertEqual(result['followup']['status'], 'not_configured')
                for query in ('', '?'+urlencode({**q,'tissue':'','unexpected':'true'}), '?'+urlencode({**q,'disease_id':'missing'})):
                    with self.assertRaises(HTTPError) as exc: urlopen(base+query,timeout=2)
                    self.assertEqual(exc.exception.code, 400)
                    exc.exception.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

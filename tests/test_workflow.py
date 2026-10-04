"""Full local workflow tests; model outputs are explicit mocks, science fictional."""
from copy import deepcopy
from hashlib import sha256
import json
import os
import socket
import stat
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from atlas.ai import ModelError
from atlas.discovery import discover
from atlas.server import create_server
from atlas.store import GraphStore
from atlas.retrieval import TopKError, TopKRetriever
from atlas.workflow import ResearchWorkspace, WorkflowError

ROOT = Path(__file__).resolve().parents[1]


def inputs():
    b = json.loads((ROOT/'data/fixtures/recommendation-demo.json').read_text())
    r = json.loads((ROOT/'data/fixtures/recommendation-request.json').read_text())
    documents = []
    for s in b['sources']:
        rows = [e for e in b['evidence'] if e['source_id'] == s['id']]
        text = '\n\n'.join(e['excerpt'] for e in rows)
        s['version'] = sha256(text.encode()).hexdigest()
        for e in rows:
            e['source_version'] = s['version']
            start = text.index(e['excerpt'])
            e['locator'] = f"characters [{start},{start + len(e['excerpt'])})"
            e['review_status'] = 'machine_checked'
        documents.append({'source_id': s['id'], 'title': s['title'], 'url': s['url'], 'text': text,
                          'version': s['version'], 'license': s['license']})
    return b, documents, r


class FakeClient:
    def __init__(self, *, block=None, error=False, bad_citation=False):
        self.calls = []; self.prompts = []; self.extraction_proposal = None
        self.block = block; self.error = error; self.bad_citation = bad_citation
    def status(self):
        return {'available': True, 'provider': 'test_mock', 'model': 'fixture', 'mode': 'mock'}
    def generate_json(self, prompt, schema, schema_name):
        self.calls.append(schema_name)
        self.prompts.append(prompt)
        if self.block: self.block.wait(timeout=5)
        if self.error: raise ModelError('test_failure', 'Simulated model failure.')
        if schema_name == 'research_brief':
            ids = schema['properties']['paragraphs']['items']['properties']['claim_ids']['items']['enum']
            data = {'paragraphs': [{'text': 'The fictional protocol needs feasibility review.',
                                    'claim_ids': ['unknown'] if self.bad_citation else ids[:1]}]}
        else:
            if self.extraction_proposal is not None:
                data = {'proposals': [self.extraction_proposal]}
            else:
                b, docs, _ = inputs()
                e = b['evidence'][0]
                data = {'proposals': [{'subject': 'demo:anchor', 'predicate': 'INVOLVES', 'object': 'demo:transport',
                                      'assertion_type': 'reported', 'effect': 'loss_of_function', 'negated': False,
                                      'qualifiers': {'mechanism_step': 'vesicle-fusion'}, 'excerpt': e['excerpt'], 'start': None, 'end': None}]}
        return {'data': data, 'metadata': {'provider': 'test_mock', 'model': 'fixture', 'mode': 'mock'}}


class MockTopKRetriever:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []
        self.last_metadata = {'provider': 'topk', 'mode': 'test_mock', 'indexed_chunks': 4}

    def search(self, query, top_k=5):
        self.calls.append((query, top_k))
        if self.error:
            raise self.error
        return [{'source_id': 'demo:source-protocols', 'title': 'Remote protocol hit',
                 'text': 'Verified remote hit passage.', 'start': 0, 'end': 29,
                 'score': 0.87, 'source_version': 'test-snapshot'}]


def wait_job(workspace, job):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        state = workspace.job(job['id'])
        if state['status'] != 'running': return state
        time.sleep(.01)
    raise AssertionError('Mock job did not terminate')


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.bundle, self.docs, self.request = inputs()
        self.client = FakeClient()
        self.workspace = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client)

    def approve(self, cid):
        return self.workspace.review(claim_id=cid, decision='approve', reviewer='Fixture reviewer',
                note='Checked fictional source and interpretation for this test.', attested=True,
                revision=self.workspace.state()['revision'])

    def test_real_workflow_extraction_review_decision_edit_and_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'session.json'
            self.workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            initial = self.workspace.state()
            self.assertEqual(initial['analysis']['status'], 'no_ready_candidate')
            job = self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
            done = wait_job(self.workspace, job)
            self.assertEqual(done['status'], 'completed')
            new = done['outcome']['new_claim_ids']
            self.assertEqual(len(new), 1)
            extracted = next(c for c in self.workspace.state()['claims'] if c['id'] == new[0])
            self.assertEqual(extracted['review_status'], 'unreviewed')
            for cid in ('demo:anchor-step', 'demo:assay-fit-capability', 'demo:assay-fit-owner'):
                state = self.approve(cid)
            good = next(r for r in state['analysis']['recommendations'] if r['asset_id'] == 'demo:assay-fit')
            self.assertEqual(good['status'], 'ready_for_discussion')
            self.assertEqual(state['coverage']['reviewed_claims'], 3)
            state = self.workspace.save_brief(markdown='My edited research discussion draft.', revision=state['revision'])
            self.assertTrue(state['brief']['edited'])
            self.approve('demo:assay-gap-capability')
            self.assertTrue(self.workspace.state()['brief']['stale'])
            reopened = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            self.assertEqual(reopened.state()['brief']['markdown'], 'My edited research discussion draft.')
            self.assertTrue(reopened.state()['brief']['stale'])
            self.assertEqual(len(reopened.data['reviews']), 4)
            self.assertEqual(reopened.state()['runs'][0]['metadata']['mode'], 'mock')

    def test_review_requires_attestation_and_matching_source(self):
        with self.assertRaises(WorkflowError):
            self.workspace.review(claim_id='demo:anchor-step', decision='approve', reviewer='Tester', note='checked', revision=0)
        self.workspace.data['bundle']['evidence'][0]['excerpt'] = 'not in the document'
        with self.assertRaises(WorkflowError): self.approve('demo:anchor-step')

    def test_approval_requires_evidence_rows(self):
        self.workspace.data['bundle']['evidence'] = [
            row for row in self.workspace.data['bundle']['evidence']
            if row['claim_id'] != 'demo:anchor-step'
        ]
        with self.assertRaisesRegex(WorkflowError, 'at least one source-linked evidence row'):
            self.workspace.review(claim_id='demo:anchor-step', decision='approve', reviewer='Fixture reviewer',
                                  note='Checked fictional source and interpretation for this test.', attested=True,
                                  revision=0)
        self.assertEqual(self.workspace.data['reviews'], [])

    def test_approval_rejects_locator_that_does_not_point_to_quote(self):
        row = next(e for e in self.workspace.data['bundle']['evidence'] if e['claim_id'] == 'demo:anchor-step')
        end = len(row['excerpt'])
        row['locator'] = f'characters [1,{end + 1})'
        with self.assertRaisesRegex(WorkflowError, 'locator must point to the exact quote'):
            self.approve('demo:anchor-step')
        self.assertEqual(self.workspace.data['reviews'], [])

    def test_reject_removes_active_claim_but_keeps_audit_and_original_evidence(self):
        state = self.workspace.review(claim_id='demo:assay-fit-capability', decision='reject', reviewer='Tester', note='Extraction misinterprets source.', revision=0)
        c = next(c for c in state['claims'] if c['id'] == 'demo:assay-fit-capability')
        self.assertEqual(c['review_status'], 'rejected')
        self.assertEqual(c['evidence'][0]['stance'], 'supports')
        self.assertNotIn(c['id'], {c['id'] for c in self.workspace._active_bundle()['claims']})
        self.assertEqual(len(self.workspace.data['reviews']), 1)

    def test_attestation_is_bound_to_claim_and_source_not_just_id(self):
        self.approve('demo:anchor-step')
        self.workspace.data['bundle']['claims'][0]['context']['mechanism_step'] = 'different'
        active = self.workspace._active_bundle()
        self.assertNotEqual(active['evidence'][0]['review_status'], 'human_reviewed')

    def test_stale_revision_rejected(self):
        self.approve('demo:anchor-step')
        with self.assertRaises(WorkflowError) as error:
            self.workspace.save_brief(markdown='old draft', revision=0)
        self.assertEqual(error.exception.status, 409)

    def test_imported_sources_replace_search_snapshot_and_invalidate_cached_hits(self):
        self.assertEqual(self.workspace._retrieve('uniqueimporttoken')['hits'], [])
        hit = {'id': 'new-passage', 'kind': 'source_passage', 'title': 'Imported protocol',
               'url': 'https://example.org/new', 'text': 'uniqueimporttoken protocol evidence'}
        self.workspace.catalog = SimpleNamespace(get=lambda _: hit)
        state = self.workspace.import_source(revision=0, hit_id=hit['id'])
        retrieval = self.workspace._retrieve('uniqueimporttoken')
        self.assertEqual([h['source_id'] for h in retrieval['hits']], ['source:passage:new-passage'])
        self.assertEqual(retrieval['searched_documents'], len(self.docs) + 1)
        self.assertEqual(state['coverage']['indexed_documents'], len(self.workspace.retriever.documents))

    def test_failed_import_persistence_keeps_old_search_snapshot(self):
        self.workspace._retrieve('uniqueimporttoken')
        previous_retriever = self.workspace.retriever
        hit = {'id': 'new-passage', 'kind': 'source_passage', 'title': 'Imported protocol',
               'url': 'https://example.org/new', 'text': 'uniqueimporttoken protocol evidence'}
        self.workspace.catalog = SimpleNamespace(get=lambda _: hit)
        with patch.object(self.workspace, '_persist', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.workspace.import_source(revision=0, hit_id=hit['id'])
        self.assertIs(self.workspace.retriever, previous_retriever)
        self.assertEqual(self.workspace.data['revision'], 0)
        self.assertEqual(len(self.workspace.data['documents']), len(self.docs))
        self.assertEqual(self.workspace._retrieve('uniqueimporttoken')['hits'], [])

    def test_second_workspace_cannot_overwrite_a_saved_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            first = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            second = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            first.review(claim_id='demo:anchor-step', decision='reject', reviewer='Tester',
                         note='Review made in the first server.', revision=0)
            with self.assertRaises(WorkflowError) as caught:
                second.save_brief(markdown='Stale second-server draft.', revision=0)
            self.assertEqual(caught.exception.code, 'workspace_file_changed')
            self.assertEqual(second.data['revision'], 0)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['revision'], 1)
            self.assertEqual(saved['reviews'][0]['note'], 'Review made in the first server.')
            self.assertIsNone(saved['brief'])

    def test_partial_snapshot_write_keeps_saved_and_in_memory_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            original = path.read_bytes()
            def fail_after_partial_write(data, handle, **kwargs):
                handle.write('{"incomplete":')
                raise OSError('disk full')
            with patch('atlas.workflow.json.dump', side_effect=fail_after_partial_write):
                with self.assertRaises(OSError):
                    workspace.save_brief(markdown='Must not persist.', revision=0)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(workspace.data['revision'], 0)
            self.assertIsNone(workspace.data['brief'])
            self.assertEqual(list(path.parent.glob('*.tmp')), [])
            workspace.save_brief(markdown='Retry after storage recovers.', revision=0)
            reopened = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            self.assertEqual(reopened.data['brief']['markdown'], 'Retry after storage recovers.')

    def test_snapshot_file_sync_failure_rolls_back_before_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            original = path.read_bytes()
            with patch('atlas.workflow.os.fsync', side_effect=OSError('file sync failed')):
                with self.assertRaises(OSError):
                    workspace.save_brief(markdown='Not committed.', revision=0)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(workspace.data['revision'], 0)
            self.assertEqual(workspace._disk_snapshot['revision'], 0)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_directory_sync_failure_keeps_committed_state_and_new_search_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            workspace._retrieve('uniqueimporttoken')
            old_retriever = workspace.retriever
            hit = {'id': 'new-passage', 'kind': 'source_passage', 'title': 'Imported protocol',
                   'url': 'https://example.org/new', 'text': 'uniqueimporttoken protocol evidence'}
            workspace.catalog = SimpleNamespace(get=lambda _: hit)
            real_fsync = os.fsync
            synced = []
            def fail_directory_sync(fd):
                is_directory = stat.S_ISDIR(os.fstat(fd).st_mode)
                synced.append('directory' if is_directory else 'file')
                if is_directory:
                    self.assertEqual(json.loads(path.read_text())['revision'], 1)
                    raise OSError('directory sync failed')
                return real_fsync(fd)
            with patch('atlas.workflow.os.fsync', side_effect=fail_directory_sync):
                with self.assertRaises(WorkflowError) as caught:
                    workspace.import_source(revision=0, hit_id=hit['id'])
            self.assertEqual(caught.exception.code, 'workspace_durability_unconfirmed')
            self.assertIn('was saved', str(caught.exception))
            self.assertEqual(synced, ['file', 'directory'])
            self.assertEqual(workspace.data, json.loads(path.read_text()))
            self.assertEqual(workspace.data, workspace._disk_snapshot)
            self.assertIsNot(workspace.retriever, old_retriever)
            self.assertTrue(workspace._retrieve('uniqueimporttoken')['hits'])
            reopened = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            self.assertEqual(reopened.data, workspace.data)
            with self.assertRaises(WorkflowError) as stale:
                workspace.save_brief(markdown='Old revision must fail.', revision=0)
            self.assertEqual(stale.exception.code, 'stale_revision')
            workspace.save_brief(markdown='Continue from committed revision.', revision=1)
            self.assertEqual(json.loads(path.read_text())['revision'], 2)
            self.assertEqual(len(workspace.data['documents']), len(self.docs) + 1)

    def test_model_commit_directory_sync_failure_is_terminal_and_not_a_second_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            real_fsync = os.fsync
            def fail_directory_sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError('directory sync failed')
                return real_fsync(fd)
            with patch('atlas.workflow.os.fsync', side_effect=fail_directory_sync):
                done = wait_job(workspace, workspace.start_job('explain', revision=0))
            self.assertEqual(done['status'], 'failed')
            self.assertTrue(done['state_saved'])
            self.assertFalse(done['durability_confirmed'])
            self.assertIn('was saved', done['message'])
            self.assertIn('brief', done['outcome'])
            self.assertEqual(workspace.data['revision'], 1)
            self.assertEqual([r['status'] for r in workspace.data['runs']], ['completed'])
            self.assertEqual(json.loads(path.read_text()), workspace.data)
            reopened = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            self.assertEqual(len(reopened.data['runs']), 1)
            self.assertEqual(reopened.data['brief'], done['outcome']['brief'])

    def test_failed_model_audit_reports_post_rename_sync_failure_truthfully(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspace = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=FakeClient(error=True))
            real_fsync = os.fsync
            def fail_directory_sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError('directory sync failed')
                return real_fsync(fd)
            with patch('atlas.workflow.os.fsync', side_effect=fail_directory_sync):
                done = wait_job(workspace, workspace.start_job('explain', revision=0))
            self.assertEqual(done['status'], 'failed')
            self.assertIn('failure audit was saved', done['message'])
            self.assertNotIn('could not be saved', done['message'])
            self.assertTrue(done['state_saved'])
            self.assertEqual(workspace.data, json.loads(path.read_text()))
            self.assertEqual([r['status'] for r in workspace.data['runs']], ['failed'])

    def test_simultaneous_workspace_writers_preserve_exactly_one_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            workspaces = [ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
                          for _ in range(2)]
            ready = threading.Barrier(2)
            results = []
            def write(workspace, draft):
                ready.wait(timeout=2)
                try:
                    workspace.save_brief(markdown=draft, revision=0)
                    results.append(('saved', draft))
                except WorkflowError as exc:
                    results.append((exc.code, draft))
            threads = [threading.Thread(target=write, args=(workspace, f'Draft {i}'))
                       for i, workspace in enumerate(workspaces)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=3)
            self.assertEqual(sorted(result[0] for result in results), ['saved', 'workspace_file_changed'])
            saved = json.loads(path.read_text())
            self.assertEqual(saved['revision'], 1)
            self.assertEqual(saved['brief']['markdown'], next(draft for status, draft in results if status == 'saved'))

    def test_late_model_result_cannot_overwrite_another_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            release = threading.Event()
            first = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=FakeClient(block=release))
            second = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
            job = first.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
            second.save_brief(markdown='Newer saved draft.', revision=0)
            release.set()
            done = wait_job(first, job)
            self.assertEqual(done['status'], 'failed')
            self.assertIn('Another process changed', done['message'])
            self.assertIn('failure audit could not be saved', done['message'])
            saved = json.loads(path.read_text())
            self.assertEqual(saved['brief']['markdown'], 'Newer saved draft.')
            self.assertEqual(saved['bundle']['claims'], self.bundle['claims'])

    def test_restart_does_not_restore_inflight_job_as_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.json'
            release = threading.Event()
            first = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=FakeClient(block=release))
            job = first.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
            try:
                reopened = ResearchWorkspace(self.bundle, self.docs, self.request, path=path, client=self.client)
                self.assertEqual(reopened.state()['jobs'], [])
                with self.assertRaises(WorkflowError) as caught:
                    reopened.job(job['id'])
                self.assertEqual(caught.exception.status, 404)
            finally:
                release.set()
                wait_job(first, job)

    def test_analysis_failure_does_not_leave_running_job(self):
        with patch.object(self.workspace, '_analysis', side_effect=RuntimeError('retrieval unavailable')):
            with self.assertRaises(RuntimeError):
                self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        self.assertEqual(self.workspace.jobs, {})
        job = self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        self.assertEqual(wait_job(self.workspace, job)['status'], 'completed')

    def test_thread_start_failure_does_not_leave_running_job(self):
        with patch('atlas.workflow.threading.Thread.start', side_effect=RuntimeError('thread unavailable')):
            with self.assertRaises(WorkflowError) as error:
                self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        self.assertEqual(error.exception.code, 'job_start_failed')
        self.assertEqual(self.workspace.jobs, {})
        job = self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        self.assertEqual(wait_job(self.workspace, job)['status'], 'completed')

    def test_policy_change_marks_saved_brief_stale(self):
        self.workspace.save_brief(markdown='A reviewed-by-user draft.', revision=0)
        self.workspace.data['brief']['policy_version'] = 'older-decision-policy'
        self.assertTrue(self.workspace.state()['brief']['stale'])

    def test_concurrent_model_job_cannot_overwrite_a_new_review(self):
        event = threading.Event()
        self.workspace.client = FakeClient(block=event)
        job = self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        with self.assertRaises(WorkflowError):
            self.workspace.start_job('extract', revision=0, source_id=self.docs[0]['source_id'])
        self.approve('demo:anchor-step')
        event.set()
        done = wait_job(self.workspace, job)
        self.assertEqual(done['status'], 'failed')
        self.assertEqual(self.workspace.state()['coverage']['reviewed_claims'], 1)
        self.assertEqual(len(self.workspace.state()['claims']), len(self.bundle['claims']))
        self.assertEqual(self.workspace.state()['runs'][-1]['status'], 'failed')

    def test_investigate_is_one_bounded_questioned_call_and_does_not_promote(self):
        before = self.workspace.state()
        queries = before['analysis']['followup']['queries']
        self.assertTrue(queries)
        self.assertLessEqual(len(queries), 3)

        source_id = before['analysis']['retrieval']['hits'][0]['source_id']
        evidence = next(e for e in self.bundle['evidence']
                        if e['source_id'] == source_id and e['claim_id'] == 'demo:assay-wrong-step-capability')
        claim = next(c for c in self.bundle['claims'] if c['id'] == evidence['claim_id'])
        self.client.extraction_proposal = {
            'subject': claim['subject'], 'predicate': claim['predicate'], 'object': claim['object'],
            'assertion_type': claim['assertion_type'], 'effect': claim['context'].get('effect'),
            'negated': claim['context'].get('negated', False),
            'qualifiers': {k: v for k, v in claim['context'].items() if k not in ('effect', 'negated')},
            'excerpt': evidence['excerpt'],
        }
        job = self.workspace.start_job('investigate', revision=before['revision'])
        done = wait_job(self.workspace, job)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(self.client.calls, ['atlas_extraction'])
        self.assertEqual(done['metadata']['model_calls'], 1)
        self.assertEqual(done['metadata']['followup_rounds'], 1)
        self.assertEqual(done['metadata']['questions'], queries)
        prompt = self.client.prompts[0]
        self.assertIn('RESEARCH_GAPS=' + json.dumps(queries[:3], ensure_ascii=False), prompt)
        self.assertEqual(len(done['outcome']['new_claim_ids']), 1)

        state = self.workspace.state()
        new_id = done['outcome']['new_claim_ids'][0]
        added = next(c for c in state['claims'] if c['id'] == new_id)
        self.assertEqual(added['review_status'], 'unreviewed')
        self.assertTrue(all(e['review_status'] == 'unreviewed' for e in added['evidence']))
        self.assertEqual(state['analysis']['status'], before['analysis']['status'])
        self.assertEqual(
            {r['asset_id']: r['status'] for r in state['analysis']['recommendations']},
            {r['asset_id']: r['status'] for r in before['analysis']['recommendations']},
        )

    def test_topk_success_is_scoped_and_reuses_same_query(self):
        retriever = MockTopKRetriever()
        workspace = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client,
                                      retrieval='topk', retriever=retriever)
        initial = workspace.state()
        retrieval = initial['analysis']['retrieval']
        self.assertEqual(retrieval['provider'], 'topk')
        self.assertEqual(retrieval['status'], 'completed')
        self.assertEqual(retrieval['hits'][0]['source_id'], 'demo:source-protocols')
        self.assertIsNone(retrieval['searched_documents'])
        self.assertIsNone(initial['coverage']['indexed_documents'])
        self.assertEqual(len(retriever.calls), 1)

        workspace.state()
        saved = workspace.save_brief(markdown='A local draft edit.', revision=initial['revision'])
        self.assertEqual(saved['brief']['markdown'], 'A local draft edit.')
        self.assertEqual(len(retriever.calls), 1)

    def test_topk_failure_keeps_graph_assessment_and_does_not_fallback(self):
        retriever = MockTopKRetriever(error=TopKError('Mock remote index is unavailable.'))
        workspace = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client,
                                      retrieval='topk', retriever=retriever)
        state = workspace.state()
        retrieval = state['analysis']['retrieval']
        self.assertEqual(retrieval['provider'], 'topk')
        self.assertEqual(retrieval['status'], 'failed')
        self.assertIn('Mock remote index is unavailable.', retrieval['error'])
        self.assertEqual(retrieval['hits'], [])
        self.assertEqual(state['analysis']['status'], 'no_ready_candidate')
        graph_only = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client).state()
        self.assertEqual(state['analysis']['recommendations'], graph_only['analysis']['recommendations'])
        self.assertEqual(len(retriever.calls), 1)

    def test_topk_failures_retry_after_ttl_without_requerying_each_poll(self):
        retriever = MockTopKRetriever(error=TopKError('Temporary provider outage.'))
        workspace = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client,
                                      retrieval='topk', retriever=retriever)
        with patch('atlas.workflow.perf_counter', return_value=0) as clock:
            first = workspace.state()['analysis']['retrieval']
            self.assertEqual(first['retry_after_seconds'], 60)
            for now in (1, 30, 59):
                clock.return_value = now
                self.assertEqual(workspace.state()['analysis']['retrieval']['status'], 'failed')
            self.assertEqual(len(retriever.calls), 1)
            retriever.error = None
            clock.return_value = 60
            self.assertEqual(workspace.state()['analysis']['retrieval']['status'], 'completed')
            self.assertEqual(len(retriever.calls), 2)
            clock.return_value = 10000
            workspace.state()
            self.assertEqual(len(retriever.calls), 2)

    def test_topk_import_reports_changed_unverified_corpus_without_index_writes(self):
        workspace = ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client, retrieval='topk')
        hit = {'id': 'new-passage', 'kind': 'source_passage', 'title': 'Imported protocol',
               'url': 'https://example.org/new', 'text': 'uniqueimporttoken protocol evidence'}
        workspace.catalog = SimpleNamespace(get=lambda _: hit)
        with patch.object(TopKRetriever, 'search', return_value=[]), patch.object(TopKRetriever, 'index_documents') as index:
            before = workspace.state()['analysis']['retrieval']['snapshot']
            state = workspace.import_source(revision=0, hit_id=hit['id'])
            retrieval = state['analysis']['retrieval']
            self.assertNotEqual(before['corpus_id'], retrieval['snapshot']['corpus_id'])
            self.assertTrue(retrieval['snapshot']['changed_since_seed'])
            self.assertIsNone(retrieval['snapshot']['index_verified'])
            self.assertIsNone(retrieval['snapshot']['query_verified'])
            self.assertIsNone(state['coverage']['indexed_documents'])
            self.assertIsNone(retrieval['searched_documents'])
            self.assertIn('Prior TopK index receipts do not verify this corpus', retrieval['note'])
            index.assert_not_called()

    def test_ai_brief_has_resolvable_citations_and_cannot_change_decisions(self):
        before = self.workspace.state()['analysis']['recommendations']
        job = self.workspace.start_job('explain', revision=0)
        self.assertEqual(wait_job(self.workspace, job)['status'], 'completed')
        state = self.workspace.state()
        self.assertTrue(state['brief']['ai_draft'])
        self.assertIn('[claims:', state['brief']['markdown'])
        self.assertEqual(state['analysis']['recommendations'], before)
        self.workspace.client = FakeClient(bad_citation=True)
        job = self.workspace.start_job('explain', revision=state['revision'])
        self.assertEqual(wait_job(self.workspace, job)['status'], 'failed')
        self.assertEqual(self.workspace.state()['brief']['markdown'], state['brief']['markdown'])

    def test_source_hash_mismatch_and_seed_replacement_are_rejected(self):
        self.docs[0]['text'] += 'new text'
        with self.assertRaises(WorkflowError): ResearchWorkspace(self.bundle, self.docs, self.request, client=self.client)

    def test_edited_request_survives_reopen_of_original_seed(self):
        bundle, docs, request = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'session.json'
            workspace = ResearchWorkspace(bundle, docs, request, path=path, client=self.client)
            edited = dict(request, readout='edited-local-readout')
            saved = workspace.analyze(request=edited, revision=0)
            self.assertEqual(saved['request']['readout'], 'edited-local-readout')

            reopened = ResearchWorkspace(bundle, docs, request, path=path, client=self.client)
            self.assertEqual(reopened.state()['request']['readout'], 'edited-local-readout')
            with self.assertRaisesRegex(WorkflowError, 'another seed snapshot'):
                ResearchWorkspace(bundle, docs, dict(request, tissue='different-seed'), path=path, client=self.client)

    def test_cluster_membership_is_explained_and_not_eligibility(self):
        result = discover(self.bundle)
        self.assertEqual(len(result['groups']), 1)
        self.assertEqual(result['links'][0]['similarity'], .35)
        self.assertFalse(result['links'][0]['reviewed'])
        self.assertEqual(self.workspace.state()['analysis']['status'], 'no_ready_candidate')
        reverse = deepcopy(self.bundle)
        reverse['claims'].reverse(); reverse['nodes'].reverse()
        self.assertEqual(discover(reverse), result)


class WorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        bundle, docs, request = inputs()
        self.workspace = ResearchWorkspace(bundle, docs, request, client=FakeClient())
        self.store = GraphStore(); self.store.load_bundle(bundle)
        self.server = create_server(self.store, port=0, workspace=self.workspace)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_address[1])
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.store.close()
    def post(self, path, data, headers=None):
        return urlopen(Request(self.base+path, data=json.dumps(data).encode(), method='POST',
                headers={'Content-Type':'application/json','X-Atlas-Token':self.workspace.token, **(headers or {})}), timeout=2)
    def test_page_and_api_integrate_without_mutating_legacy_store(self):
        with urlopen(self.base+'/research') as response:
            self.assertEqual(response.url, self.base+'/explore')
            self.assertIn(b'graph.js', response.read())
        with self.assertRaises(HTTPError) as retired:
            urlopen(self.base+'/research.js')
        self.assertEqual(retired.exception.code, 404)
        with urlopen(self.base+'/api/research/state') as response: state = json.load(response)
        with self.post('/api/research/brief', {'revision':state['revision'], 'markdown':'Edited text'}) as response:
            saved = json.load(response)
        self.assertEqual(saved['brief']['markdown'], 'Edited text')
        self.assertEqual(self.store.bundle(), inputs()[0])
    def test_bad_origin_token_and_payload_do_not_mutate(self):
        for headers in ({'Origin':'https://evil.example'}, {'X-Atlas-Token':'bad'}, {'Host':'evil.example'}):
            with self.assertRaises(HTTPError) as exc:
                self.post('/api/research/brief', {'revision':0,'markdown':'attack'}, headers)
            self.assertEqual(exc.exception.code, 403); exc.exception.close()
        with self.assertRaises(HTTPError) as exc: self.post('/api/research/brief', {'extra':True})
        self.assertEqual(exc.exception.code, 400); exc.exception.close()
        self.assertEqual(self.workspace.state()['revision'], 0)
    def test_model_job_through_http(self):
        with self.post('/api/research/extract', {'revision':0,'source_id':inputs()[1][0]['source_id']}) as response:
            self.assertEqual(response.status, 202); job = json.load(response)
        self.assertEqual(wait_job(self.workspace, job)['status'], 'completed')
        with urlopen(self.base+'/api/research/jobs/'+job['id']) as response:
            self.assertEqual(json.load(response)['status'], 'completed')

    def test_incomplete_json_upload_is_rejected_without_mutation(self):
        body = json.dumps({'revision': 0, 'markdown': 'Must not save a truncated upload.'}).encode()
        with socket.create_connection(self.server.server_address, timeout=2) as connection:
            headers = (f'POST /api/research/brief HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_address[1]}\r\n'
                       f'Content-Type: application/json\r\nX-Atlas-Token: {self.workspace.token}\r\n'
                       f'Content-Length: {len(body) + 10}\r\n\r\n').encode()
            connection.sendall(headers + body)
            connection.shutdown(socket.SHUT_WR)
            response = connection.makefile('rb').read()
        self.assertIn(b'400 Bad Request', response)
        self.assertIn(b'upload was incomplete', response)
        self.assertEqual(self.workspace.data['revision'], 0)

    def test_stalled_json_upload_times_out_without_mutation(self):
        with patch('atlas.server.REQUEST_BODY_TIMEOUT_SECONDS', .05):
            with socket.create_connection(self.server.server_address, timeout=2) as connection:
                headers = (f'POST /api/research/brief HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_address[1]}\r\n'
                           f'Content-Type: application/json\r\nX-Atlas-Token: {self.workspace.token}\r\n'
                           'Content-Length: 100\r\n\r\n').encode()
                connection.sendall(headers)
                response = connection.makefile('rb').read()
        self.assertIn(b'408 Request Timeout', response)
        self.assertIn(b'upload_timeout', response)
        self.assertEqual(self.workspace.data['revision'], 0)

    def test_trickling_json_upload_cannot_extend_the_upload_deadline(self):
        with patch('atlas.server.REQUEST_BODY_TIMEOUT_SECONDS', .1):
            with socket.create_connection(self.server.server_address, timeout=2) as connection:
                headers = (f'POST /api/research/brief HTTP/1.0\r\nHost: 127.0.0.1:{self.server.server_address[1]}\r\n'
                           f'Content-Type: application/json\r\nX-Atlas-Token: {self.workspace.token}\r\n'
                           'Content-Length: 100\r\n\r\n').encode()
                connection.sendall(headers)
                stopped = threading.Event()
                def trickle():
                    while not stopped.wait(.02):
                        try:
                            connection.sendall(b' ')
                        except OSError:
                            break
                thread = threading.Thread(target=trickle, daemon=True)
                thread.start()
                started = time.monotonic()
                try:
                    response = connection.makefile('rb').read()
                finally:
                    stopped.set()
                    thread.join(timeout=1)
                self.assertLess(time.monotonic() - started, 1)
        self.assertIn(b'408 Request Timeout', response)
        self.assertEqual(self.workspace.data['revision'], 0)
    def test_workflow_rejects_external_bind(self):
        with self.assertRaises(ValueError): create_server(self.store, host='0.0.0.0', port=0, workspace=self.workspace)

"""Integration tests for the combined graph UI and local research workspace API."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atlas.server import create_server
from atlas.store import GraphStore
from atlas.workflow import ResearchWorkspace

ROOT = Path(__file__).resolve().parents[1]


def workspace_inputs():
    bundle = json.loads((ROOT / 'data/fixtures/recommendation-demo.json').read_text())
    request = json.loads((ROOT / 'data/fixtures/recommendation-request.json').read_text())
    docs = []
    for source in bundle['sources']:
        evidence = [e for e in bundle['evidence'] if e['source_id'] == source['id']]
        text = '\n\n'.join(e['excerpt'] for e in evidence)
        version = sha256(text.encode()).hexdigest()
        source['version'] = version
        for row in evidence:
            row['source_version'] = version
            row['review_status'] = 'machine_checked'
            start = text.index(row['excerpt'])
            row['locator'] = f'characters [{start},{start + len(row["excerpt"])})'
        docs.append({'source_id': source['id'], 'title': source['title'], 'url': source['url'],
                     'text': text, 'version': version, 'license': source['license']})
    return bundle, docs, request


class TestClient:
    def __init__(self):
        self.calls = []

    def status(self):
        return {'available': True, 'provider': 'test', 'model': 'fixture', 'mode': 'mock'}

    def generate_json(self, prompt, schema, schema_name):
        self.calls.append(schema_name)
        return {'data': {'proposals': []}, 'metadata': {'provider': 'test', 'mode': 'mock'}}


class TestAssistant:
    def __init__(self):
        self.calls = []

    def answer(self, bundle, question, node_id, claim_ids, analysis):
        self.calls.append((deepcopy(bundle), question, node_id, list(claim_ids), deepcopy(analysis)))
        return {'answer': 'A graph-grounded answer.', 'claims': claim_ids,
                'sources': [{'title': 'Verified source', 'url': 'https://example.org/source'}],
                'metadata': {'provider': 'test', 'mode': 'mock'}}


class TestCatalog:
    provider = 'fixture_catalog'

    def __init__(self):
        self.search_calls = []
        self.record = {'id': 'verified-hit-1', 'title': 'Canonical passage title',
                       'url': 'https://example.org/canonical', 'license': 'CC BY 4.0',
                       'published_at': None, 'text': 'Canonical passage from the verified catalog.',
                       'original_locator': 'paragraph 4', 'kind': 'source_passage',
                       'source_id': 'catalog:paper-1', 'version': 'origin-v3'}

    def search(self, query, top_k=8):
        self.search_calls.append((query, top_k))
        return {'hits': [{'id': self.record['id'], 'kind': self.record['kind'], 'title': self.record['title'],
                          'url': self.record['url'], 'license': self.record['license'],
                          'original_locator': self.record['original_locator']}],
                'provider': self.provider, 'scopes': ['fixture-index']}

    def get(self, hit_id):
        if hit_id != self.record['id']:
            raise KeyError(hit_id)
        return deepcopy(self.record)

    def status(self):
        return {'provider': self.provider, 'scopes': [{'id': 'fixture-index'}], 'loaded_passages': 1}


class IntegratedAPITests(unittest.TestCase):
    def setUp(self):
        bundle, docs, request = workspace_inputs()
        self.assistant = TestAssistant()
        self.client = TestClient()
        self.catalog = TestCatalog()
        self.workspace = ResearchWorkspace(bundle, docs, request, client=self.client,
                                           assistant=self.assistant, catalog=self.catalog)
        self.store = GraphStore()
        self.store.load_bundle(bundle)
        self.server = create_server(self.store, port=0, workspace=self.workspace)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.close()

    def get(self, path):
        return urlopen(self.base + path, timeout=3)

    def post(self, path, data, *, token=True, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Atlas-Token'] = self.workspace.token
        if origin is not None:
            headers['Origin'] = origin
        return urlopen(Request(self.base + path, data=json.dumps(data).encode(), method='POST', headers=headers), timeout=3)

    def json_post(self, path, data):
        with self.post(path, data) as response:
            return response.status, json.load(response)

    def test_graph_frontend_routes_and_live_graph_follow_active_workspace(self):
        self.assertEqual(self.workspace.state()['catalog']['provider'], 'fixture_catalog')
        for path, marker in (('/', b'Enter Atlas'), ('/explore', b'graph.js'), ('/records', b'app.js')):
            with self.get(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(marker, response.read())
        with self.get('/research') as response:
            self.assertEqual(response.url, self.base + '/explore')
        with self.assertRaises(HTTPError) as missing:
            self.get('/research.js')
        self.assertEqual(missing.exception.code, 404)

        before = json.loads(self.get('/api/graph').read())
        self.assertEqual(len(before['claims']), len(self.workspace.data['bundle']['claims']))
        self.workspace.review(claim_id='demo:assay-wrong-step-capability', decision='reject',
                              reviewer='Fixture reviewer', note='Test rejection.', revision=0)
        after = json.loads(self.get('/api/graph').read())
        self.assertNotIn('demo:assay-wrong-step-capability', {c['id'] for c in after['claims']})
        with self.assertRaises(HTTPError) as missing_claim:
            self.get('/api/claim?id=demo%3Aassay-wrong-step-capability')
        self.assertEqual(missing_claim.exception.code, 404)
        stats = json.loads(self.get('/api/stats').read())
        self.assertEqual(stats['stats']['claims'], len(after['claims']))
        self.assertIn('coverage', stats['stats'])
        request = self.workspace.state()['request']
        fields = ('disease_id', 'mechanism_id', 'mechanism_step', 'readout', 'species', 'tissue', 'stage')
        query = urlencode({key: request[key] for key in fields if request.get(key) is not None})
        recommendations = json.loads(self.get('/api/recommend?' + query).read())['recommendations']
        self.assertNotIn('demo:assay-wrong-step-capability',
                         {cid for row in recommendations for cid in row['decision_claim_ids']})

    def test_ask_is_async_cited_and_bound_to_current_revision_and_graph_ids(self):
        state = self.workspace.state()
        node_id = 'demo:anchor'
        claim_id = 'demo:anchor-step'
        status, job = self.json_post('/api/atlas/ask', {'revision': state['revision'],
            'question': 'What does the graph record?', 'node_id': node_id, 'claim_ids': [claim_id]})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = json.loads(self.get('/api/research/jobs/' + job['id']).read())
            if current['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(current['status'], 'completed')
        answer = current['outcome']['answer']
        self.assertEqual(answer['answer'], 'A graph-grounded answer.')
        self.assertTrue(answer['sources'])
        self.assertEqual(self.assistant.calls[0][1:4], ('What does the graph record?', node_id, [claim_id]))
        with self.assertRaises(HTTPError) as stale:
            self.post('/api/atlas/ask', {'revision': 0, 'question': 'stale request'})
        self.assertEqual(stale.exception.code, 409)
        with self.assertRaises(HTTPError) as invalid:
            self.post('/api/atlas/ask', {'revision': self.workspace.data['revision'],
                'question': 'bad context', 'claim_ids': ['claim:forged']})
        self.assertEqual(invalid.exception.code, 400)
        state = self.workspace.state()
        self.assertEqual(len(state['ask_history']), 1)

    def test_search_and_source_import_use_verified_catalog_record_then_extract(self):
        status, result = self.json_post('/api/atlas/search', {'q': 'WDR45', 'top_k': 8})
        self.assertEqual(status, 200)
        self.assertEqual(result['provider'], 'fixture_catalog')
        self.assertEqual(result['scopes'], ['fixture-index'])
        hit_id = result['hits'][0]['id']
        state = self.workspace.state()
        _, imported = self.json_post('/api/atlas/source', {'revision': state['revision'], 'hit_id': hit_id,
            'text': 'forged browser passage', 'url': 'https://attacker.invalid/fake'})
        source = next(s for s in imported['sources'] if s['id'] == 'source:passage:' + hit_id)
        document = next(d for d in imported['documents'] if d['source_id'] == source['id'])
        self.assertEqual(document['text'], self.catalog.record['text'])
        self.assertEqual(source['url'], self.catalog.record['url'])
        self.assertEqual(source['version'], sha256(self.catalog.record['text'].encode()).hexdigest())
        self.assertEqual(source['catalog_passage_id'], hit_id)
        self.assertEqual(source['original_source_id'], 'catalog:paper-1')
        self.assertEqual(source['original_source_version'], 'origin-v3')
        self.assertEqual(document['snapshot_kind'], 'source_passage')
        self.assertEqual(source['snapshot_scope'], 'Indexed source passage excerpt; not a complete article')
        self.assertEqual(len(imported['documents']), len(state['documents']) + 1)

        _, again = self.json_post('/api/atlas/source', {'revision': imported['revision'], 'hit_id': hit_id})
        self.assertEqual(again['revision'], imported['revision'])
        with self.assertRaises(HTTPError) as unknown:
            self.post('/api/atlas/source', {'revision': again['revision'], 'hit_id': 'browser-forged-id',
                                            'text': 'forged', 'url': 'https://attacker.invalid/'})
        self.assertEqual(unknown.exception.code, 404)

        self.catalog.record['id'] = 'curated-card'
        self.catalog.record['kind'] = 'curated_evidence'
        with self.assertRaises(HTTPError) as curated:
            self.post('/api/atlas/source', {'revision': again['revision'], 'hit_id': 'curated-card'})
        self.assertEqual(curated.exception.code, 400)
        self.assertIn(b'already a graph evidence card', curated.exception.read())

        status, job = self.json_post('/api/research/extract', {'revision': again['revision'], 'source_id': source['id']})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = json.loads(self.get('/api/research/jobs/' + job['id']).read())
            if current['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(current['status'], 'completed')

    def test_investigation_uses_one_catalog_passage_and_commits_snapshot_atomically(self):
        before = self.workspace.state()
        questions = before['analysis']['followup']['queries']
        self.assertTrue(questions)
        job = self.workspace.start_job('investigate', revision=before['revision'])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.workspace.job(job['id'])
            if current['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(current['status'], 'completed')
        self.assertEqual(len(self.catalog.search_calls), 1)
        self.assertEqual(self.catalog.search_calls[0][1], 8)
        self.assertIn(questions[0]['question'], self.catalog.search_calls[0][0])
        self.assertIn('Aurora syndrome', self.catalog.search_calls[0][0])
        self.assertIn('Intracellular transport', self.catalog.search_calls[0][0])
        self.assertEqual(self.client.calls, ['atlas_extraction'])
        self.assertEqual(current['metadata']['model_calls'], 1)
        self.assertEqual(current['metadata']['selected_source_id'], 'source:passage:verified-hit-1')
        state = self.workspace.state()
        self.assertEqual(len(state['documents']), len(before['documents']) + 1)
        self.assertEqual(state['documents'][-1]['text'], self.catalog.record['text'])
        self.assertEqual(current['outcome']['new_claim_ids'], [])

    def test_investigation_skips_curated_cards_when_no_original_passage_is_available(self):
        before = self.workspace.state()
        self.catalog.record['kind'] = 'curated_evidence'
        job = self.workspace.start_job('investigate', revision=before['revision'])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.workspace.job(job['id'])
            if current['status'] != 'running':
                break
            time.sleep(.01)
        self.assertEqual(current['status'], 'completed')
        self.assertEqual(current['metadata']['eligible_passage_found'], False)
        self.assertEqual(current['metadata']['model_calls'], 0)
        self.assertEqual(current['outcome']['new_claim_ids'], [])
        self.assertEqual(self.client.calls, [])
        self.assertEqual(len(self.workspace.state()['documents']), len(before['documents']))

    def test_csrf_and_local_host_guards_cover_new_routes(self):
        state = self.workspace.state()
        with self.assertRaises(HTTPError) as no_token:
            self.post('/api/atlas/search', {'q': 'neuro'}, token=False)
        self.assertEqual(no_token.exception.code, 403)
        with self.assertRaises(HTTPError) as foreign_origin:
            self.post('/api/atlas/ask', {'revision': state['revision'], 'question': 'test'},
                      origin='https://attacker.example')
        self.assertEqual(foreign_origin.exception.code, 403)


if __name__ == '__main__':
    unittest.main()

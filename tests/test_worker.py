"""Exercise the deployment entrypoint without network access or live inbox writes."""
import asyncio
from email.message import Message
import gzip
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from atlas.cloud_bundle import reviewed_graph
from atlas.proposals import MAX_BYTES

ROOT = Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, body, *, status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}

    def json(self):
        return json.loads(self.body)


class Entrypoint:
    def __init__(self, ctx=None, env=None):
        self.ctx, self.env = ctx, env


class SQL:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row

    def exec(self, sql, *args):
        rows = [dict(row) for row in self.db.execute(sql, args).fetchall()]
        return SimpleNamespace(toArray=lambda: rows)


class Chunk:
    def __init__(self, data):
        self.data, self.byteLength, self.converted = data, len(data), False

    def to_bytes(self):
        self.converted = True
        return self.data


class Stream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.reads, self.cancelled, self.released = 0, False, False

    def getReader(self):
        return self

    async def read(self):
        self.reads += 1
        if not self.chunks:
            return SimpleNamespace(done=True)
        return SimpleNamespace(done=False, value=self.chunks.pop(0))

    async def cancel(self):
        self.cancelled = True

    def releaseLock(self):
        self.released = True


def request(path, *, method='GET', body=None, headers=None, chunks=None):
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    if isinstance(body, str):
        body = body.encode('utf-8')
    stream = Stream(chunks if chunks is not None else [Chunk(body or b'')])
    return SimpleNamespace(url='https://atlas.example' + path, method=method,
                           headers=message, body=stream)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cluster = json.loads((ROOT / 'data/curated/grin_cluster_demo_v2.json').read_text())
        graph = reviewed_graph(json.loads((ROOT / 'data/curated/grin_atlas_bundle.json').read_text()), cluster)
        dense = json.loads(gzip.decompress((ROOT / 'data/curated/hgnc_dense_snapshot.json.gz').read_bytes()))
        span = cluster['observations'][0]['evidence'][0]
        cls.excerpts = {f"{span['unit_id']}:{span['start']}:{span['end']}": 'Published test excerpt'}
        modules = {}
        for name, attributes in {
            'workers': dict(WorkerEntrypoint=Entrypoint, DurableObject=Entrypoint, Response=Response),
            'snapshot': dict(BUNDLE=graph, STATS={}),
            'dense_snapshot': dict(BUNDLE=dense),
            'cluster_snapshot': dict(CLUSTER=cluster, EXCERPTS=cls.excerpts),
        }.items():
            module = ModuleType(name)
            module.__dict__.update(attributes)
            modules[name] = module
        spec = importlib.util.spec_from_file_location('atlas_test_worker', ROOT / 'deploy/cloudflare/worker.py')
        cls.worker = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(cls.worker)

    def setUp(self):
        self.sql = SQL()
        self.inbox = self.worker.ProposalInbox(SimpleNamespace(storage=SimpleNamespace(sql=self.sql)), None)
        self.bindings = []

        def binding(name):
            self.bindings.append(name)
            return self.inbox

        self.app = self.worker.Default(env=SimpleNamespace(PROPOSAL_INBOX=SimpleNamespace(getByName=binding)))
        self.data = dict(request_id=str(uuid.uuid4()), query='new paper', name='Missing paper',
                         kind='paper', description='A published source to review.',
                         source_url='https://doi.org/10.123/example', entry='search')

    def tearDown(self):
        self.sql.db.close()

    async def submit(self, data=None, headers=None, body=None):
        body = json.dumps(self.data if data is None else data) if body is None else body
        base = {'Origin': 'https://atlas.example', 'Content-Type': 'application/json'}
        base.update(headers or {})
        return await self.app.fetch(request('/api/proposals', method='POST', body=body, headers=base))

    async def test_submit_retry_and_receipt_keep_payload_private(self):
        first, retry = await self.submit(), await self.submit()
        self.assertEqual((first.status, retry.status), (201, 200))
        self.assertEqual(first.json(), retry.json())
        receipt = await self.app.fetch(request('/api/proposals/' + first.json()['id']))
        self.assertEqual(receipt.json(), first.json())
        self.assertEqual(set(first.json()), {'id', 'status', 'created_at'})
        self.assertEqual(self.bindings, ['review-inbox-v1'] * 3)
        for response in (first, retry, receipt):
            self.assertEqual(response.headers['Cache-Control'], 'no-store')

    async def test_receipt_survives_inbox_reconstruction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'inbox.sqlite')
            sql = SQL(path)
            inbox = self.worker.ProposalInbox(SimpleNamespace(storage=SimpleNamespace(sql=sql)), None)
            first = json.loads(await inbox.submit(json.dumps(self.data)))
            sql.db.close()
            sql = SQL(path)
            try:
                restarted = self.worker.ProposalInbox(SimpleNamespace(storage=SimpleNamespace(sql=sql)), None)
                retry = json.loads(await restarted.submit(json.dumps(self.data)))
                receipt = json.loads(await restarted.receipt(first['payload']['id']))
                self.assertEqual(retry['status'], 200)
                self.assertEqual(first['payload'], retry['payload'])
                self.assertEqual(first['payload'], receipt['payload'])
                self.assertEqual(sql.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0], 1)
            finally:
                sql.db.close()

    async def test_concurrent_retries_create_one_durable_row(self):
        responses = await asyncio.gather(*(self.submit() for _ in range(12)))
        self.assertEqual(sum(response.status == 201 for response in responses), 1)
        self.assertEqual(len({response.json()['id'] for response in responses}), 1)
        self.assertEqual(self.sql.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0], 1)

    async def test_header_validation_happens_before_inbox_rpc(self):
        for headers, expected in [({'Origin': 'https://other.example'}, 403),
                                  ({'Content-Type': 'text/plain'}, 415),
                                  ({'Content-Length': '12001'}, 413),
                                  ({'Content-Length': '-1'}, 400),
                                  ({'Content-Length': '²'}, 400),
                                  ({'Content-Length': '9' * 5000}, 400),
                                  ({'Content-Length': '1'}, 400)]:
            with self.subTest(headers=headers):
                response = await self.submit(headers=headers)
                self.assertEqual(response.status, expected)
                self.assertIsInstance(response.json()['error'], dict)
        self.assertEqual(self.bindings, [])

    async def test_streamed_body_is_bounded_before_copying_oversized_chunk(self):
        oversized = Chunk(b'x' * (MAX_BYTES + 1))
        req = request('/api/proposals', method='POST', chunks=[Chunk(b'{'), oversized, Chunk(b'}')],
                      headers={'Origin': 'https://atlas.example', 'Content-Type': 'application/json',
                               'Content-Length': '1'})
        response = await self.app.fetch(req)
        self.assertEqual(response.status, 413)
        self.assertFalse(oversized.converted)
        self.assertEqual(req.body.reads, 2)
        self.assertTrue(req.body.cancelled)
        self.assertTrue(req.body.released)
        self.assertEqual(self.bindings, [])

    async def test_utf8_can_cross_stream_chunk_boundaries(self):
        self.data['name'] = 'Paper 🧬'
        raw = json.dumps(self.data, ensure_ascii=False).encode('utf-8')
        req = request('/api/proposals', method='POST', chunks=[Chunk(bytes([b])) for b in raw],
                      headers={'Origin': 'https://atlas.example', 'Content-Type': 'Application/JSON; charset=utf-8',
                               'Content-Length': str(len(raw))})
        response = await self.app.fetch(req)
        self.assertEqual(response.status, 201)
        self.assertTrue(req.body.released)

    async def test_invalid_json_and_utf8_never_reach_inbox(self):
        valid = json.dumps(self.data)
        for body in [b'\xff', '{', '[]', valid[:-1] + ',"name":"other"}',
                     json.dumps({**self.data, 'name': '\ud800'}),
                     '[' * 1100 + ']' * 1100, valid[:-1] + ',"extra":NaN}']:
            with self.subTest(body=str(body)[:60]):
                response = await self.submit(body=body)
                self.assertEqual(response.status, 400)
        self.assertEqual(self.bindings, [])

    async def test_durable_rpc_also_rejects_invalid_or_oversized_envelopes(self):
        for body, expected in [('{', 400), ('x' * (MAX_BYTES + 1), 413),
                               (json.dumps({**self.data, 'name': '\ud800'}), 400)]:
            response = json.loads(await self.inbox.submit(body))
            self.assertEqual(response['status'], expected)
        self.assertEqual(self.sql.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0], 0)

    async def test_invalid_receipt_does_not_touch_inbox(self):
        for identifier in ['bad', 'x' * 10000, str(uuid.uuid4()) + '/payload', '']:
            response = await self.app.fetch(request('/api/proposals/' + identifier))
            self.assertEqual(response.status, 404)
        self.assertEqual(self.bindings, [])

    async def test_inbox_failure_never_claims_confirmation_or_exposes_exception(self):
        async def broken(_):
            raise RuntimeError('secret database detail')
        with patch.object(self.inbox, 'submit', broken):
            response = await self.submit()
        self.assertEqual(response.status, 503)
        self.assertEqual(response.headers['Retry-After'], '60')
        self.assertIn('not been confirmed', response.json()['error']['message'])
        self.assertNotIn('secret', response.body)
        self.assertNotIn('id', response.json())

    async def test_retry_recovers_when_transport_loses_durable_confirmation(self):
        submit = self.inbox.submit

        async def confirmation_lost(body):
            await submit(body)
            raise RuntimeError('Response connection lost after durable insert')

        with patch.object(self.inbox, 'submit', confirmation_lost):
            response = await self.submit()
        self.assertEqual(response.status, 503)
        recovered = await self.submit()
        self.assertEqual(recovered.status, 200)
        self.assertEqual(recovered.json()['status'], 'pending_review')
        self.assertEqual(self.sql.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0], 1)

    async def test_full_inbox_rate_window_still_allows_receipts_and_retries(self):
        for _ in range(120):
            self.data['request_id'] = str(uuid.uuid4())
            saved = await self.submit()
            self.assertEqual(saved.status, 201)
        retry = await self.submit()
        self.assertEqual(retry.status, 200)
        receipt = await self.app.fetch(request('/api/proposals/' + retry.json()['id']))
        self.assertEqual(receipt.status, 200)
        self.data['request_id'] = str(uuid.uuid4())
        blocked = await self.submit()
        self.assertEqual(blocked.status, 429)
        self.assertEqual(blocked.headers['Retry-After'], '60')
        self.assertEqual(self.sql.db.execute('SELECT COUNT(*) FROM proposals').fetchone()[0], 120)

    async def test_harvested_context_never_inherits_global_reviewed_claims(self):
        node = next(node for node in self.worker.PUBLIC.nodes.values() if node['id'] not in self.worker.API.nodes)
        response = await self.app.fetch(request('/api/ask?q=Any+conflicting+evidence%3F&node=' + node['id']))
        self.assertEqual(response.status, 200)
        self.assertIn('outside the reviewed GRIN', response.json()['answer'])
        self.assertEqual(response.json()['claim_ids'], [])
        self.assertEqual(response.json()['node_ids'], [])
        self.assertEqual(response.json()['answer_scope']['id'], 'grin-reduced-function-v1')
        self.assertNotIn('observation_ids', response.json())

    async def test_global_search_does_not_change_the_demo_answer_scope(self):
        search = await self.app.fetch(request('/api/harvest/search?q=ARX'))
        self.assertEqual(search.status, 200)
        outside = next(n for n in search.json()['results'] if n['label'] == 'ARX')
        answer = await self.app.fetch(request('/api/ask?q=Explain+GRIN2B+S541R&node=' + outside['id']))
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.json()['mode'], 'source_annotation_lookup')
        self.assertNotIn(outside['id'], answer.json()['node_ids'])
        self.assertIn('9.1 (7.2, 11)', answer.json()['answer'])
        self.assertEqual(answer.json()['answer_scope']['id'], 'grin-reduced-function-v1')

    async def test_prefilled_demo_question_returns_annotation_evidence(self):
        from html import unescape
        import re
        from urllib.parse import urlencode
        page = (ROOT / 'atlas/web/explore.html').read_text()
        question = unescape(re.search(r'<textarea id="question"[^>]*>(.*?)</textarea>', page).group(1))
        self.assertTrue(question)
        response = await self.app.fetch(request('/api/ask?' + urlencode({'q': question})))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()['mode'], 'source_annotation_lookup')
        self.assertIn('9.1 (7.2, 11)', response.json()['answer'])
        self.assertIn('Cys461Phe', response.json()['answer'])

    async def test_grin2b_help_overview_works_for_public_and_reviewed_gene(self):
        from urllib.parse import urlencode
        question = 'What is known about GRIN2B from this knowledge graph, and where can I seek help?'
        public = next(n for n in self.worker.PUBLIC.nodes.values() if n['id'].startswith('HGNC:') and n['label'] == 'GRIN2B')
        reviewed = next(n for n in self.worker.API.nodes.values() if n['label'] == 'GRIN2B')
        for context in (None, public['id'], reviewed['id']):
            with self.subTest(context=context):
                query = {'q': question, **({'node': context} if context else {})}
                response = await self.app.fetch(request('/api/ask?' + urlencode(query)))
                answer = response.json()
                self.assertEqual(response.status, 200)
                self.assertEqual(answer['mode'], 'curated_gene_overview')
                self.assertIn('7 selected protein variants', answer['answer'])
                self.assertIn('Possible LoF', answer['answer'])
                self.assertEqual(len(answer['sections']), 3)
                self.assertTrue(answer['citations'])
                self.assertTrue(all('GRIN2A' not in n for n in answer['node_ids']))
                self.assertEqual(answer['support_resources']['status'], 'external_signposts_not_graph_claims')
                self.assertEqual(len(answer['sections'][-1]['links']), 3)

    async def test_public_gene_identity_maps_to_its_demo_gene(self):
        public = next(n for n in self.worker.PUBLIC.nodes.values() if n['id'].startswith('HGNC:') and n['label'] == 'GRIN2B')
        response = await self.app.fetch(request('/api/ask?q=What+evidence+is+available&node=' + public['id']))
        self.assertEqual(response.status, 200)
        self.assertNotEqual(response.json()['mode'], 'demo_scope_boundary')
        self.assertEqual(response.json()['answer_scope']['id'], 'grin-reduced-function-v1')

    async def test_mentioning_demo_gene_cannot_import_an_outside_gene(self):
        response = await self.app.fetch(request('/api/ask?q=Compare+ARX+and+GRIN2B+variants'))
        self.assertEqual(response.json()['mode'], 'demo_scope_boundary')
        self.assertEqual(response.json()['claim_ids'], [])

    async def test_unknown_and_ambiguous_contexts_do_not_get_hgnc_fallback(self):
        node = next(iter(self.worker.API.nodes))
        for query, expected in [('q=Evidence&node=unknown', 404),
                                ('q=Evidence&node=unknown&claim=unknown', 400),
                                ('q=Evidence&node=', 400),
                                ('q=Evidence&node=unknown&node=' + node, 400),
                                ('q=Evidence&node=' + node + '&node=unknown', 400),
                                ('q=Evidence&q=Other', 400)]:
            with self.subTest(query=query):
                response = await self.app.fetch(request('/api/ask?' + query))
                self.assertEqual(response.status, expected)
                self.assertNotIn('answer', response.json())

    async def test_evidence_keeps_comparator_spans_and_only_allowlisted_quotes(self):
        record = next(record for record in self.worker.RECORDS.values() if record.get('comparator', {}).get('evidence'))
        response = await self.app.fetch(request('/api/evidence?id=' + record['id']))
        self.assertEqual(response.status, 200)
        expected = {f"{s['unit_id']}:{s['start']}:{s['end']}"
                    for s in record['evidence'] + record['comparator']['evidence']}
        spans = response.json()['spans']
        self.assertEqual(len(spans), len(expected))
        for span in spans:
            key = f"{span['unit_id']}:{span['start']}:{span['end']}"
            self.assertIn(key, expected)
            self.assertEqual(span['quote'], self.excerpts.get(key))

    async def test_evidence_errors_have_consistent_envelopes(self):
        for query, expected in [('', 400), ('?id=', 400), ('?id=missing', 404), ('?id=a&id=b', 400)]:
            response = await self.app.fetch(request('/api/evidence' + query))
            self.assertEqual(response.status, expected)
            self.assertEqual(set(response.json()['error']), {'code', 'message'})

    async def test_queries_and_methods_have_bounded_consistent_failures(self):
        for path, expected in [('/api/health?' + '&'.join('x=1' for _ in range(151)), 400),
                               ('/api/health?q=' + 'x' * 16385, 414),
                               ('/api/proposals?q=' + 'x' * 16385, 414),
                               ('/api/search?q=%FF', 400),
                               ('/api/harvest/graph?limit=NaN', 400)]:
            response = await self.app.fetch(request(path))
            self.assertEqual(response.status, expected)
            self.assertIsInstance(response.json()['error'], dict)
        for path, method, allow in [('/api/health', 'POST', 'GET'),
                                     ('/api/proposals', 'GET', 'POST'),
                                     ('/api/proposals/x', 'DELETE', 'GET')]:
            response = await self.app.fetch(request(path, method=method))
            self.assertEqual(response.status, 405)
            self.assertEqual(response.headers['Allow'], allow)


if __name__ == '__main__':
    unittest.main()

"""Cloudflare entrypoint for Atlas's shared, read-only Python API."""
import json
from urllib.parse import parse_qs, urlsplit
from workers import WorkerEntrypoint, Response, DurableObject
from atlas.http_api import AtlasAPI
from atlas.proposals import SCHEMA, INDEX, MAX_BYTES, ProposalError, submit_proposal, proposal_status
from snapshot import BUNDLE, STATS
from cluster_snapshot import CLUSTER, EXCERPTS

API = AtlasAPI(BUNDLE, STATS, CLUSTER)
RECORDS = {r['id']: r for r in CLUSTER['observations'] + CLUSTER['claims']}
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class ProposalInbox(DurableObject):
    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self.sql = ctx.storage.sql
        self.sql.exec(SCHEMA)
        self.sql.exec(INDEX)

    def execute(self, query, *args):
        return self.sql.exec(query, *args).toArray()

    async def submit(self, body):
        try:
            status, receipt = submit_proposal(json.loads(body), self.execute)
            return json.dumps({'status': status, 'payload': receipt})
        except ProposalError as error:
            return json.dumps({'status': error.status, 'payload': {'error': {'message': str(error)}}})

    async def receipt(self, identifier):
        try:
            return json.dumps({'status': 200, 'payload': proposal_status(identifier, self.execute)})
        except ProposalError as error:
            return json.dumps({'status': error.status, 'payload': {'error': {'message': str(error)}}})


class Default(WorkerEntrypoint):
    async def proposals(self, request, url):
        if request.method == 'POST' and url.path == '/api/proposals':
            if request.headers.get('Origin') != f'{url.scheme}://{url.netloc}':
                raise ProposalError('Submit the form from this Atlas site.', 403)
            if (request.headers.get('Content-Type') or '').split(';')[0].strip() != 'application/json':
                raise ProposalError('Use the proposal form to submit JSON.', 415)
            length = request.headers.get('Content-Length')
            if not length or not length.isdigit():
                raise ProposalError('A bounded request body is required.', 411)
            if int(length) > MAX_BYTES:
                raise ProposalError('This proposal is too large.', 413)
            body = await request.text()
            if len(body.encode()) > MAX_BYTES:
                raise ProposalError('This proposal is too large.', 413)
            try:
                json.loads(body)
            except ValueError:
                raise ProposalError('Invalid JSON submission.') from None
            result = await self.env.PROPOSAL_INBOX.getByName('review-inbox-v1').submit(body)
        elif request.method == 'GET' and url.path.startswith('/api/proposals/'):
            result = await self.env.PROPOSAL_INBOX.getByName('review-inbox-v1').receipt(url.path.removeprefix('/api/proposals/'))
        else:
            raise ProposalError('Proposal lists are private. Use the submission form.', 405)
        result = json.loads(result)
        return result['status'], result['payload']

    async def fetch(self, request):
        url = urlsplit(request.url)
        if not url.path.startswith('/api/'):
            return await self.env.ASSETS.fetch(request)
        if url.path == '/api/proposals' or url.path.startswith('/api/proposals/'):
            try:
                status, payload = await self.proposals(request, url)
            except ProposalError as error:
                status, payload = error.status, {'error': {'message': str(error)}}
            except Exception:
                status, payload = 503, {'error': {'message': 'The inbox is temporarily unavailable. Your proposal has not been confirmed; retry this form.'}}
        elif request.method != 'GET':
            status, payload = 405, {"error": {"code": "method_not_allowed", "message": "This atlas is read-only."}}
        elif len(url.query) > 16384:
            status, payload = 414, {"error": {"code": "query_too_long", "message": "Shorten this request."}}
        else:
            try:
                query = parse_qs(url.query, keep_blank_values=True, max_num_fields=150)
                if url.path == '/api/evidence':
                    record = RECORDS.get(query.get('id', [''])[0])
                    if record is None:
                        status, payload = 404, {'error': 'Unknown observation or claim'}
                    else:
                        spans, seen = [], set()
                        for s in record['evidence'] + record.get('comparator', {}).get('evidence', []):
                            key = f"{s['unit_id']}:{s['start']}:{s['end']}"
                            if key not in seen:
                                spans.append({**s, 'quote': EXCERPTS.get(key)})
                                seen.add(key)
                        status, payload = 200, {'record': record, 'spans': spans,
                            'notice': 'Published table cells and selected supplement rows are shown below. Longer source passages remain in the reviewed local snapshot; use the paper link and locators to inspect them.'}
                else:
                    status, payload = API.request(url.path, query)
            except ValueError:
                status, payload = 400, {"error": {"code": "invalid_query", "message": "Use fewer query parameters."}}
            except Exception:
                status, payload = 500, {"error": {"code": "internal_error", "message": "The atlas could not complete that request."}}
        return Response(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), status=status, headers=HEADERS)

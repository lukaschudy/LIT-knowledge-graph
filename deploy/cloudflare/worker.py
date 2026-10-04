"""Cloudflare entrypoint for Atlas's bounded public API and private review inbox."""
import json
from urllib.parse import parse_qs, urlsplit
from workers import WorkerEntrypoint, Response, DurableObject
from atlas.http_api import AtlasAPI, error, query_error
from atlas.proposals import SCHEMA, INDEX, MAX_BYTES, ProposalError, parse_proposal, submit_proposal, proposal_status, validate_receipt_id
from snapshot import BUNDLE, STATS
from dense_snapshot import BUNDLE as DENSE
from atlas.public_graph import PublicGraphAPI
from atlas.demo_scope import question_in_scope, mentions_scope, scope_boundary, mentioned_external_genes
from cluster_snapshot import CLUSTER, EXCERPTS

PUBLIC = PublicGraphAPI(DENSE, BUNDLE)
API = AtlasAPI(BUNDLE, STATS, CLUSTER)
RECORDS = {r['id']: r for r in CLUSTER['observations'] + CLUSTER['claims']}
HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def proposal_error(exc):
    return error(exc.status, 'proposal_rejected', str(exc))


async def proposal_body(request):
    """Enforce the limit while reading, including bodies without Content-Length."""
    length = request.headers.get('Content-Length')
    if length is not None:
        if not length or len(length) > 10 or not length.isascii() or not length.isdigit():
            raise ProposalError('Invalid request body length.')
        if int(length) > MAX_BYTES:
            raise ProposalError('This proposal is too large.', 413)
    data = bytearray()
    stream = request.body
    if stream:
        reader = stream.getReader()
        try:
            while True:
                chunk = await reader.read()
                if chunk.done:
                    break
                if len(data) + chunk.value.byteLength > MAX_BYTES:
                    await reader.cancel()
                    raise ProposalError('This proposal is too large.', 413)
                data.extend(chunk.value.to_bytes())
        finally:
            reader.releaseLock()
    if length is not None and len(data) != int(length):
        raise ProposalError('The request body length did not match.')
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        raise ProposalError('Use valid UTF-8 JSON text.') from None


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
            # Keep all SQL operations synchronous: the Durable Object serializes
            # retries and new submissions, and its output gate confirms durability.
            status, receipt = submit_proposal(parse_proposal(body), self.execute)
        except ProposalError as exc:
            status, receipt = proposal_error(exc)
        return json.dumps({'status': status, 'payload': receipt})

    async def receipt(self, identifier):
        try:
            status, payload = 200, proposal_status(identifier, self.execute)
        except ProposalError as exc:
            status, payload = proposal_error(exc)
        return json.dumps({'status': status, 'payload': payload})


def evidence_response(query):
    invalid = query_error(query)
    if invalid:
        return invalid
    identifier = query.get('id', [''])[0].strip()
    if not identifier:
        return error(400, 'missing_evidence', 'Choose an observation or claim to inspect.')
    record = RECORDS.get(identifier)
    if record is None:
        return error(404, 'evidence_not_found', 'That observation or claim is not in this snapshot.')
    spans, seen = [], set()
    for span in record['evidence'] + record.get('comparator', {}).get('evidence', []):
        key = f"{span['unit_id']}:{span['start']}:{span['end']}"
        if key not in seen:
            spans.append({**span, 'quote': EXCERPTS.get(key)})
            seen.add(key)
    return 200, {'record': record, 'spans': spans,
                 'notice': 'Published table cells and selected supplement rows are shown below. Longer source passages remain in the reviewed local snapshot; use the paper link and locators to inspect them.'}


def atlas_response(path, query):
    status, payload = API.request(path, query)
    if path == '/api/ask' and status == 200:
        outside = mentioned_external_genes(API._one(query, 'q'), PUBLIC.nodes.values(), API.nodes)
        if outside:
            return 200, scope_boundary(API._one(query, 'q'), selected_label=outside[0]['label'])
    # Only a known public entity can receive the HGNC scope response. Validate
    # the complete request first so malformed IDs/claims cannot be discarded.
    context = API._one(query, 'node') if path == '/api/ask' else None
    if (status == 404 and payload.get('error', {}).get('code') == 'node_not_found'
            and PUBLIC.canonical_id(context) in PUBLIC.nodes):
        node = PUBLIC.nodes[PUBLIC.canonical_id(context)]
        question = API._one(query, 'q')
        canonical = PUBLIC.canonical_id(context)
        canonical = canonical if canonical in API.nodes else None
        if canonical:
            return API.request(path, {**query, 'node': [canonical]})
        outside = mentioned_external_genes(question, PUBLIC.nodes.values(), API.nodes)
        if outside:
            return 200, scope_boundary(question, selected_label=outside[0]['label'])
        # Search selection never changes the fixed answer scope. Explicit
        # cluster questions still work after browsing an unrelated public node.
        if (mentions_scope(question, API.nodes.values())
                or 'cluster' in question.casefold() and question_in_scope(question)):
            return API.request(path, {key: value for key, value in query.items() if key != 'node'})
        return 200, scope_boundary(question, selected_label=node['label'])
    return status, payload


class Default(WorkerEntrypoint):
    async def proposals(self, request, url):
        if request.method == 'POST' and url.path == '/api/proposals':
            if request.headers.get('Origin') != f'{url.scheme}://{url.netloc}':
                raise ProposalError('Submit the form from this Atlas site.', 403)
            if (request.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
                raise ProposalError('Use the proposal form to submit JSON.', 415)
            body = await proposal_body(request)
            parse_proposal(body)  # Reject invalid submissions before touching the inbox.
            result = await self.env.PROPOSAL_INBOX.getByName('review-inbox-v1').submit(body)
        elif request.method == 'GET' and url.path.startswith('/api/proposals/'):
            identifier = url.path.removeprefix('/api/proposals/')
            # Receipt shape is validated before RPC; existing receipts stay private.
            validate_receipt_id(identifier)
            result = await self.env.PROPOSAL_INBOX.getByName('review-inbox-v1').receipt(identifier)
        else:
            raise ProposalError('Proposal lists are private. Use the submission form.', 405)
        result = json.loads(result)
        return result['status'], result['payload']

    async def fetch(self, request):
        url = urlsplit(request.url)
        if not url.path.startswith('/api/'):
            return await self.env.ASSETS.fetch(request)
        proposal_route = url.path == '/api/proposals' or url.path.startswith('/api/proposals/')
        if len(url.query.encode('utf-8')) > 16384:
            status, payload = error(414, 'query_too_long', 'Shorten this request.')
        elif proposal_route:
            try:
                status, payload = await self.proposals(request, url)
            except ProposalError as exc:
                status, payload = proposal_error(exc)
            except Exception:
                status, payload = error(503, 'inbox_unavailable', 'The inbox is temporarily unavailable. Your proposal has not been confirmed; retry this form.')
        elif request.method != 'GET':
            status, payload = error(405, 'method_not_allowed', 'This atlas is read-only.')
        else:
            try:
                query = parse_qs(url.query, keep_blank_values=True, max_num_fields=150, errors='strict')
                if url.path.startswith('/api/harvest/') or url.path in ('/api/voice/status', '/api/resolved/status'):
                    status, payload = PUBLIC.request(url.path, query)
                elif url.path == '/api/evidence':
                    status, payload = evidence_response(query)
                else:
                    status, payload = atlas_response(url.path, query)
            except ValueError:
                status, payload = error(400, 'invalid_query', 'Use valid UTF-8 text and at most 150 query parameters.')
            except Exception:
                status, payload = error(500, 'internal_error', 'The atlas could not complete that request.')
        headers = dict(HEADERS)
        if status == 405:
            headers['Allow'] = 'POST' if url.path == '/api/proposals' else 'GET'
        if status in (429, 503):
            headers['Retry-After'] = '60'
        return Response(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), status=status, headers=headers)

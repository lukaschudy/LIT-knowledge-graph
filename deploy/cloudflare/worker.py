"""Cloudflare entrypoint for Atlas's shared, read-only Python API."""
import json
from urllib.parse import parse_qs, urlsplit
from workers import WorkerEntrypoint, Response
from atlas.http_api import AtlasAPI
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


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlsplit(request.url)
        if not url.path.startswith('/api/'):
            return await self.env.ASSETS.fetch(request)
        if request.method != 'GET':
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

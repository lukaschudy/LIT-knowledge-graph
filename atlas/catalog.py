"""One source catalog for graph chat, passage search and source import.

The indexed export is the authority for citations. Remote hits must match it;
retrieval never creates claims or silently converts full text into graph facts.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import threading
import time

from .model import require_valid_bundle
from .retrieval import SourceRetriever, TopKRetriever, TopKError
from .search.passages import canonical, file_sha, read_rows, bundle_documents
from .search.topk import DEFAULT_REGION, FIELDS, make_query, resolve_filters, fuse, settings


class CatalogError(ValueError):
    pass


def combined_bundle(root: Path) -> dict:
    root = Path(root)
    parts = [json.loads((root / 'data/curated' / name).read_text())
             for name in ('neuro_bundle.json', 'grin_atlas_bundle.json')]
    result = deepcopy(parts[0])
    result['dataset'] = {'id': 'atlas-connected-evidence-v1', 'title': 'Atlas · published neuro research evidence',
        'description': 'Selected EPG5/Vici, WDR45/BPAN, AP4B1/SPG47 and GRIN evidence. Graph assertions and indexed discovery passages retain separate provenance and review status.',
        'synthetic': False, 'created_at': '2026-10-04'}
    for name in ('nodes', 'claims', 'evidence', 'sources', 'coverage'):
        rows = {}
        for part in parts:
            for row in part[name]:
                if row['id'] in rows and rows[row['id']] != row:
                    raise CatalogError(f'Conflicting {name} identity during graph assembly.')
                rows[row['id']] = deepcopy(row)
        result[name] = list(rows.values())
    require_valid_bundle(result)
    return result


class EvidenceCatalog:
    def __init__(self, root: str | Path, *, env_file=None, mode='auto', client=None):
        if mode not in ('auto', 'local', 'topk'):
            raise ValueError('Catalog mode must be auto, local or topk.')
        self.root = Path(root)
        self.mode = mode
        self._lock = threading.RLock()
        self._network_lock = threading.Lock()
        self._next_request = 0.0
        self._cache = {}
        self.rows = {}
        self.scopes = []
        self.config = {}
        if mode != 'local' and client is None:
            try:
                self.config = settings(env_file)
            except ValueError:
                if mode == 'topk':
                    raise CatalogError('TopK credentials are required for --search topk.') from None
        self.remote = mode != 'local' and bool(self.config or client)
        self.client = client
        self.neuro_documents = json.loads((self.root/'data/curated/neuro_documents.json').read_text())
        self.neuro = TopKRetriever(self.neuro_documents,
            api_key=self.config.get('TOPK_API_KEY'), region=self.config.get('TOPK_REGION') or DEFAULT_REGION,
            collection='lit-neuro-evidence-v1', client=client, timeout=8)
        for chunk in self.neuro._chunks:
            doc = next(d for d in self.neuro_documents if d['source_id'] == chunk['source_id'])
            self.rows[chunk['_id']] = {
                'id': chunk['_id'], 'source_id': doc['source_id'], 'title': doc['title'], 'url': doc['url'],
                'text': chunk['passage'], 'locator': f"Snapshot {doc['version']}; characters [{chunk['start']},{chunk['end']})",
                'original_locator': f"neuro_documents.json; characters [{chunk['start']},{chunk['end']})",
                'license': doc['license'], 'kind': 'source_passage', 'review_status': 'unreviewed',
                'claim_ids': [], 'node_ids': [], 'scope': 'neuro', 'version': doc['version']}
        receipt_path = self.root/'data/curated/topk-neuro-index.json'
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        neuro_verified = (receipt.get('corpus_id') == self.neuro._corpus_id
                          and receipt.get('status') == 'verified'
                          and receipt.get('collection') == 'lit-neuro-evidence-v1'
                          and type(receipt.get('verified_documents')) is int
                          and receipt.get('verified_documents') == len(self.neuro._chunks))
        self.scopes.append({'id': 'neuro', 'label': 'EPG5 / WDR45 / AP4B1 source snapshots',
            'loaded_passages': len(self.neuro._chunks), 'indexed_passages': receipt.get('verified_documents') if neuro_verified else None,
            'index_status': 'verified_snapshot' if neuro_verified else 'not_verified',
            'collection': 'lit-neuro-evidence-v1', 'verified_at': receipt.get('verified_at') if neuro_verified else None})
        try:
            self.grin_manifest = json.loads((self.root/'data/curated/topk-grin-index.json').read_text())
        except (OSError, json.JSONDecodeError):
            raise CatalogError('GRIN index receipt is missing or invalid.') from None
        if (not isinstance(self.grin_manifest, dict)
                or self.grin_manifest.get('version') != 'grin-passages-v1'
                or self.grin_manifest.get('live_topk_status') != 'verified'
                or not isinstance(self.grin_manifest.get('snapshot_id'), str)
                or not isinstance(self.grin_manifest.get('collection'), str)
                or not self.grin_manifest.get('collection')
                or not isinstance(self.grin_manifest.get('verified_at'), str)
                or type(self.grin_manifest.get('verified_documents')) is not int
                or self.grin_manifest.get('verified_documents') != self.grin_manifest.get('documents')
                or type(self.grin_manifest.get('documents')) is not int
                or self.grin_manifest.get('documents') < 0
                or not isinstance(self.grin_manifest.get('input_sha256'), dict)
                or not isinstance(self.grin_manifest.get('export_sha256'), str)
                or len(self.grin_manifest.get('export_sha256', '')) != 64):
            raise CatalogError('GRIN index receipt is incomplete or not verified.')
        input_hashes = self.grin_manifest['input_sha256']
        if (not input_hashes or any(not isinstance(name, str) or not isinstance(value, str) or len(value) != 64
                                    for name, value in input_hashes.items())
                or 'data/curated/grin_atlas_bundle.json' not in input_hashes):
            raise CatalogError('GRIN index receipt has invalid input checksums.')
        expected_snapshot = sha256(canonical({'version': self.grin_manifest['version'], 'inputs': input_hashes}).encode()).hexdigest()[:24]
        if self.grin_manifest['snapshot_id'] != expected_snapshot:
            raise CatalogError('GRIN index receipt snapshot checksum is invalid.')
        graph_path = self.root/'data/curated/grin_atlas_bundle.json'
        expected = input_hashes['data/curated/grin_atlas_bundle.json']
        if file_sha(graph_path) != expected:
            raise CatalogError('GRIN graph differs from the verified passage export. Rebuild before connecting it.')
        export_path = self.root/'data/processed/search/grin-passages.jsonl.gz'
        self.grin_rows = {}
        if export_path.exists():
            if file_sha(export_path) != self.grin_manifest['export_sha256']:
                raise CatalogError('Local passage export checksum differs from the verified index receipt.')
            self.grin_rows = {row['_id']: row for row in read_rows(export_path)}
            if len(self.grin_rows) != self.grin_manifest['documents']:
                raise CatalogError('Local passage export count differs from its receipt.')
        elif self.remote:
            raise CatalogError('Download or prepare the verified local GRIN passage export before enabling remote search; citations must be checked locally.')
        else:
            for row in bundle_documents(json.loads(graph_path.read_text())):
                row['_id'] = 'local-' + sha256(canonical(row).encode()).hexdigest()
                self.grin_rows[row['_id']] = row
        for row in self.grin_rows.values():
            self.rows[row['_id']] = self._normalize_grin(row)
        self.scopes.append({'id': 'grin', 'label': 'GRIN published evidence and licensed literature',
            'loaded_passages': len(self.grin_rows), 'indexed_passages': self.grin_manifest['verified_documents'],
            'index_status': 'verified_snapshot', 'collection': self.grin_manifest['collection'],
            'verified_at': self.grin_manifest['verified_at']})
        self._local = {scope: SourceRetriever([{'source_id': r['id'], 'title': r['title'], 'text': r['text']}
                                              for r in self.rows.values() if r['scope'] == scope])
                       for scope in ('neuro', 'grin')}

    @staticmethod
    def _normalize_grin(row):
        curated = row.get('kind') == 'curated_evidence'
        return {'id': row['_id'], 'source_id': row['source_id'], 'title': row['title'], 'url': row['url'],
                'text': row['content'], 'locator': row['locator'], 'original_locator': row['locator'],
                'license': row['license'], 'kind': row['kind'], 'review_status': row['review_status'],
                'claim_ids': [row['claim_id']] if curated and row.get('claim_id') else [],
                'claim_id': row.get('claim_id') if curated else None,
                'evidence_id': row.get('evidence_id') if curated else None,
                'node_ids': row.get('node_ids', []) if curated else [], 'scope': 'grin',
                'snapshot_id': row.get('snapshot_id'), 'stance': row.get('stance'),
                'context': row.get('context_json')}

    def status(self):
        return {'provider': 'topk' if self.remote else 'local_lexical', 'configured': self.remote,
                'scopes': deepcopy(self.scopes), 'loaded_passages': len(self.rows), 'full_harvest_indexed': False,
                'note': 'Graph assertions, indexed passages and harvested records are different counts. Index receipts describe verified snapshots, not current scientific approval.'}

    def get(self, hit_id):
        if not isinstance(hit_id, str) or hit_id not in self.rows:
            raise CatalogError('Unknown passage identifier; search the loaded evidence catalog first.')
        return deepcopy(self.rows[hit_id])

    def _client(self):
        if self.client is None:
            from topk_sdk import Client
            self.client = Client(api_key=self.config['TOPK_API_KEY'], region=self.config.get('TOPK_REGION') or DEFAULT_REGION,
                                 retry_config={'timeout': 8000, 'max_retries': 0})
        return self.client

    def _call(self, function):
        # One bounded call per second also covers separate corpus collections.
        with self._network_lock:
            time.sleep(max(0, self._next_request - time.monotonic()))
            try:
                return function()
            finally:
                self._next_request = time.monotonic() + 1.05

    @staticmethod
    def _query_scopes(query):
        import re
        grin = bool(re.search(r'\b(?:GRIN|GluN|NMDA)', query, re.I))
        neuro = bool(re.search(r'\b(?:EPG5|Vici|WDR45|BPAN|AP4B1|SPG47|AP-?4|autophag)', query, re.I))
        return (['grin', 'neuro'] if grin and neuro or not grin and not neuro else ['grin'] if grin else ['neuro'])

    def search(self, query: str, top_k: int = 8):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000 or type(top_k) is not int or not 1 <= top_k <= 20:
            raise CatalogError('Search needs 1–2,000 characters and a result limit between 1 and 20.')
        key = (query.strip(), top_k)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 120:
                return deepcopy(cached[1]) | {'cached': True}
        started = time.monotonic()
        selected_scopes = self._query_scopes(query)
        rankings = {}
        try:
            for scope in selected_scopes:
                if not self.remote:
                    found = self._local[scope].search(query, top_k=top_k)
                    rankings[scope] = [{'_id': h['source_id']} for h in found]
                elif scope == 'neuro':
                    # This adapter verifies every field against the local chunk manifest.
                    self.neuro._client = self._client()
                    hits = self._call(lambda: self.neuro.search(query, top_k=top_k))
                    match = {(r['source_id'], r['start'], r['end']): r['_id'] for r in self.neuro._chunks}
                    rankings[scope] = [{'_id': match[(h['source_id'], h['start'], h['end'])]} for h in hits]
                else:
                    gene, protein = resolve_filters(query)
                    for mode in ('semantic', 'keyword'):
                        q = make_query(query, self.grin_manifest['snapshot_id'], mode, max(20, top_k), gene=gene, protein=protein)
                        found = self._call(lambda: self._client().collection(self.grin_manifest['collection']).query(q))
                        verified = []
                        for hit in found:
                            original = self.grin_rows.get(hit.get('_id'))
                            if original is None or any(hit.get(field) != original.get(field) for field in FIELDS):
                                raise CatalogError('A TopK passage differs from the verified source export; no answer was generated from it.')
                            verified.append({'_id': hit['_id']})
                        rankings[f'{scope}:{mode}'] = verified
        except CatalogError:
            raise
        except ValueError as exc:
            # Known query validation is safe; do not include SDK transport details.
            if type(exc) is ValueError:
                raise CatalogError('Use an unambiguous gene when specifying a protein variant.') from None
            raise CatalogError('Evidence retrieval could not be completed.') from None
        except Exception:
            raise CatalogError('TopK search is unavailable. No local search was substituted for a live result.') from None
        # Fuse GRIN semantic and keyword ranks within its own scope first, so an
        # extra channel does not automatically double GRIN's cross-scope weight.
        scope_rankings = {}
        for scope in selected_scopes:
            channels = {k: v for k, v in rankings.items() if k == scope or k.startswith(scope + ':')}
            scope_rankings[scope] = fuse(channels, k=top_k)
        ranked = fuse(scope_rankings, k=top_k)
        hits = [self.get(row['_id']) | {'rank': i + 1, 'ranking_score': row['rrf_score']} for i, row in enumerate(ranked)]
        result = {'query': query, 'provider': 'topk' if self.remote else 'local_lexical', 'hits': hits,
                  'scopes': [deepcopy(s) for s in self.scopes if s['id'] in selected_scopes],
                  'latency_ms': round((time.monotonic() - started) * 1000), 'cached': False,
                  'graph_write_performed': False, 'note': 'Relevance ranks identify passages to inspect, not biological confidence. Full text and table text do not establish graph edges.'}
        with self._lock:
            self._cache[key] = (time.monotonic(), deepcopy(result))
            while len(self._cache) > 64:
                self._cache.pop(next(iter(self._cache)))
        return result


def index_neuro(root: str | Path, *, env_file=None) -> dict:
    """Explicitly index and read back every neuro passage; never touch GRIN data."""
    root = Path(root)
    catalog = EvidenceCatalog(root, env_file=env_file, mode='topk')
    catalog.neuro._client = catalog._client()
    metadata = catalog.neuro.index_documents()
    return verify_neuro(catalog, lsn=metadata['lsn'])


def verify_neuro(catalog, *, lsn=None):
    """Read the strongly consistent corpus and verify semantic retrieval separately."""
    from datetime import datetime, timezone
    from .search.topk import request
    from topk_sdk.query import select, field
    root = catalog.root
    manifest = {row['_id']: row for row in catalog.neuro._chunks}
    expected_fields = list(next(iter(manifest.values())))
    query = select(*expected_fields).filter(field('corpus_id') == catalog.neuro._corpus_id).limit(len(manifest) + 1)
    rows = request(catalog._client().collection('lit-neuro-evidence-v1').query, query,
                   **({'lsn': lsn} if lsn else {}), consistency='strong')
    if len(rows) != len(manifest) or len({r['_id'] for r in rows}) != len(manifest):
        raise CatalogError('Neuro index read-back count differs from its source manifest.')
    if any(row != manifest.get(row['_id']) for row in rows):
        raise CatalogError('Neuro index read-back differs from the source manifest.')
    catalog.neuro._client = catalog._client()
    hits = request(catalog.neuro.search, 'EPG5 Vici autophagy fusion', top_k=4)
    if not hits:
        raise CatalogError('Neuro passages are stored but semantic retrieval returned no verified passages.')
    receipt = {'status': 'verified', 'collection': 'lit-neuro-evidence-v1',
               'region': catalog.config.get('TOPK_REGION') or DEFAULT_REGION,
               'corpus_id': catalog.neuro._corpus_id, 'verified_documents': len(rows),
               'source_documents': len(catalog.neuro_documents),
               'verified_at': datetime.now(timezone.utc).isoformat(),
               'verification': 'Every chunk ID and field compared to the local manifest using a strongly consistent read; semantic query returned source-validated passages.',
               'full_harvest_indexed': False, 'scope': 'Selected EPG5/Vici, WDR45/BPAN and AP4B1/SPG47 primary-source excerpts',
               'documents_sha256': file_sha(root/'data/curated/neuro_documents.json')}
    (root/'data/curated/topk-neuro-index.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt

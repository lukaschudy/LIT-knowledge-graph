"""Read-only, bounded public HGNC projection; distinct from reviewed GRIN evidence."""
import re

from .http_api import error, query_error


class PublicGraphAPI:
    def __init__(self, harvested, reviewed):
        self.harvested = harvested
        self.reviewed = reviewed
        self.nodes = {n['id']: n for n in harvested['nodes'] + reviewed['nodes']}
        self.claims = {c['id']: c for c in harvested['claims'] + reviewed['claims']}
        self.datasets = {d['id']: d for d in harvested['public_datasets']}
        self.records = {}
        self.records_by_dataset = {}
        self.neighbors = {}
        for node in harvested['nodes']:
            provenance = node.get('provenance', {})
            if provenance.get('id'):
                self.records.setdefault(provenance['id'], node)
            self.records_by_dataset.setdefault(provenance.get('dataset'), []).append(provenance)
        for claim in self.claims.values():
            self.neighbors.setdefault(claim['subject'], set()).add(claim['object'])
            self.neighbors.setdefault(claim['object'], set()).add(claim['subject'])

    def provenance(self, row):
        p = dict(row.get('provenance', {}))
        d = self.datasets.get(p.get('dataset'), {})
        p.update(d.get('metadata', {}))
        p['sha256'] = d.get('sha256')
        return p

    def request(self, path, query):
        invalid = query_error(query)
        if invalid:
            return invalid
        try:
            return self._request(path, query)
        except ValueError as exc:
            return error(400, 'invalid_query', str(exc))

    def _request(self, path, query):
        def one(key, default=''):
            return query.get(key, [default])[0].strip()

        def integer(key, default, maximum=None):
            value = one(key, str(default))
            # Bound conversion itself as well as the resulting page size.
            if not re.fullmatch(r'-?[0-9]{1,10}', value):
                raise ValueError(f'Use a whole number for {key} (at most 10 digits).')
            value = max(0, int(value))
            return min(maximum, max(1, value)) if maximum is not None else value

        missing = error(404, 'not_in_snapshot', 'This record is outside the published snapshot.')
        if path == '/api/harvest/status':
            return 200, {'total_nodes': len(self.nodes), 'total_edges': len(self.claims), 'total_datasets': len(self.datasets), 'total_records': 0, 'datasets': list(self.datasets.values()), 'build_status': 'published HGNC snapshot plus reviewed GRIN graph'}
        if path == '/api/harvest/graph':
            limit = integer('limit', 10000, 10000)
            offset = integer('offset', 0)
            focus = one('focus')
            rows = self.harvested['nodes']
            if focus:
                if focus not in self.nodes:
                    return missing
                # Keep the requested anchor on the first page even when its ID
                # sorts after its neighbors (e.g. a protein focused from search).
                ids = [focus, *sorted(self.neighbors.get(focus, set()) - {focus})]
                rows = [self.nodes[n] for n in ids if n in self.nodes]
            page = rows[offset:offset+limit]
            selected = {n['id']: n for n in page + self.reviewed['nodes']}
            claims = [c for c in self.claims.values() if c['subject'] in selected and c['object'] in selected]
            return 200, {**{k:v for k,v in self.reviewed.items() if k not in ['nodes','claims']}, 'dataset': {**self.reviewed['dataset'], 'title': 'Public HGNC snapshot and reviewed GRIN evidence'}, 'nodes': list(selected.values()), 'claims': claims, 'harvest': {'total_nodes': len(rows), 'shown_nodes': len(selected), 'shown_edges': len(claims), 'next_offset': offset+limit if offset+limit<len(rows) else None, 'offset': offset, 'limit': limit, 'focus': focus or None, 'note': 'Public HGNC snapshot. Harvest relationships remain unreviewed.'}}
        if path == '/api/harvest/search':
            term = one('q').casefold()
            if len(term) > 1000:
                return error(400, 'invalid_query', 'Search using at most 1000 characters.')
            results, total = [], 0
            for node in self.nodes.values():
                terms = [node['id'], node.get('label', ''), *node.get('aliases', [])]
                if term and any(term in str(value).casefold() for value in terms):
                    total += 1
                    if len(results) < 40:
                        results.append(node)
            return 200, {'results': results, 'total': total}
        if path == '/api/harvest/node':
            n = self.nodes.get(one('id'))
            return (200, {'node': n, 'provenance': self.provenance(n)}) if n else missing
        if path == '/api/harvest/claim':
            c = self.claims.get(one('id'))
            return (200, {'claim': c, 'provenance': self.provenance(c)}) if c else missing
        if path == '/api/harvest/datasets':
            return 200, {'datasets': list(self.datasets.values())}
        if path == '/api/harvest/records':
            # Published graph entities and source pointers, not hosted source rows.
            dataset = one('dataset')
            page = integer('page', 0)
            limit = integer('limit', 50, 100)
            if dataset not in self.datasets:
                return missing
            rows = self.records_by_dataset.get(dataset, [])
            return 200, {'records': rows[page*limit:(page+1)*limit], 'total': len(rows), 'limit': limit, 'page': page, 'note': 'Published entity provenance pointers only.'}
        if path == '/api/harvest/record':
            n = self.records.get(one('id'))
            if n:
                return 200, {'node':n,'provenance':self.provenance(n),'record':{'data':{'id':n['id'],'label':n['label'],'type':n['type'],'notice':'Published entity projection; follow the HGNC source URL for the original row.'}}}
            return missing
        if path == '/api/voice/status':
            return 200, {'available':False,'message':'Voice dictation is available in the local workspace.'}
        if path == '/api/resolved/status':
            return 200, {'available':False}
        return missing

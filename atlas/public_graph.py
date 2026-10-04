"""Read-only, bounded public HGNC projection; distinct from reviewed GRIN evidence."""
class PublicGraphAPI:
    def __init__(self, harvested, reviewed):
        self.harvested = harvested
        self.reviewed = reviewed
        self.nodes = {n['id']: n for n in harvested['nodes'] + reviewed['nodes']}
        self.claims = {c['id']: c for c in harvested['claims'] + reviewed['claims']}
        self.datasets = {d['id']: d for d in harvested['public_datasets']}

    def provenance(self, row):
        p = dict(row.get('provenance', {}))
        d = self.datasets.get(p.get('dataset'), {})
        p.update(d.get('metadata', {}))
        p['sha256'] = d.get('sha256')
        return p

    def request(self, path, query):
        one = lambda key, default='': query.get(key, [default])[0]
        missing = (404, {'error': {'code': 'not_in_snapshot', 'message': 'This record is outside the published snapshot.'}})
        if path == '/api/harvest/status':
            return 200, {'total_nodes': len(self.nodes), 'total_edges': len(self.claims), 'total_datasets': len(self.datasets), 'total_records': 0, 'datasets': list(self.datasets.values()), 'build_status': 'published HGNC snapshot plus reviewed GRIN graph'}
        if path == '/api/harvest/graph':
            limit = max(1, min(10000, int(one('limit', '10000'))))
            offset = max(0, int(one('offset', '0')))
            focus = one('focus')
            rows = self.harvested['nodes']
            if focus:
                ids = {focus}
                for c in self.claims.values():
                    if focus in (c['subject'], c['object']): ids.update((c['subject'], c['object']))
                rows = [self.nodes[n] for n in sorted(ids) if n in self.nodes]
            page = rows[offset:offset+limit]
            selected = {n['id']: n for n in page + self.reviewed['nodes']}
            claims = [c for c in self.claims.values() if c['subject'] in selected and c['object'] in selected]
            return 200, {**{k:v for k,v in self.reviewed.items() if k not in ['nodes','claims']}, 'dataset': {**self.reviewed['dataset'], 'title': 'Public HGNC snapshot and reviewed GRIN evidence'}, 'nodes': list(selected.values()), 'claims': claims, 'harvest': {'total_nodes': len(rows), 'shown_nodes': len(selected), 'shown_edges': len(claims), 'next_offset': offset+limit if offset+limit<len(rows) else None, 'offset': offset, 'limit': limit, 'focus': focus or None, 'note': 'Public HGNC snapshot. Harvest relationships remain unreviewed.'}}
        if path == '/api/harvest/search':
            term = one('q').strip().casefold()
            results = [n for n in self.nodes.values() if term and any(term in str(n.get(k,'')).casefold() for k in ['id','label','aliases'])]
            return 200, {'results': results[:40], 'total': len(results)}
        if path == '/api/harvest/node':
            n = self.nodes.get(one('id'))
            return (200, {'node': n, 'provenance': self.provenance(n)}) if n else missing
        if path == '/api/harvest/claim':
            c = self.claims.get(one('id'))
            return (200, {'claim': c, 'provenance': self.provenance(c)}) if c else missing
        if path == '/api/harvest/datasets':
            return 200, {'datasets': list(self.datasets.values())}
        if path == '/api/harvest/records':
            # Published graph entities and source pointers, not an assertion that full source rows are hosted.
            dataset = one('dataset'); page = max(0,int(one('page','0'))); limit = min(100,max(1,int(one('limit','50'))))
            rows = [n['provenance'] for n in self.harvested['nodes'] if n.get('provenance',{}).get('dataset')==dataset]
            return 200, {'records': rows[page*limit:(page+1)*limit], 'total': len(rows), 'limit': limit, 'page': page, 'note': 'Published entity provenance pointers only.'}
        if path == '/api/harvest/record':
            n = next((n for n in self.harvested['nodes'] if n.get('provenance',{}).get('id')==one('id')),None)
            if n:
                return 200, {'node':n,'provenance':self.provenance(n),'record':{'data':{'id':n['id'],'label':n['label'],'type':n['type'],'notice':'Published entity projection; follow the HGNC source URL for the original row.'}}}
            return missing
        if path == '/api/voice/status':
            return 200, {'available':False,'message':'Voice dictation is available in the local workspace.'}
        if path == '/api/resolved/status':
            return 200, {'available':False}
        return missing

"""Read-only neighborhood views of a versioned, resolved entity artifact."""
from collections import defaultdict, deque
from contextlib import closing
import sqlite3
from copy import deepcopy
import json
from pathlib import Path


class ResolvedGraph:
    def __init__(self, path, *, harvest=None):
        self.path = Path(path)
        self.bundle = json.loads(self.path.read_text())
        self.harvest = harvest
        self.resolution = self.bundle['resolution']
        if harvest is not None:
            with closing(sqlite3.connect(harvest.path.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
                row=conn.execute("SELECT value FROM metadata WHERE key='build_id'").fetchone()
            if not row or row[0] != self.resolution.get('harvest_snapshot_id'):
                raise ValueError('Resolved layer belongs to a different harvest snapshot; rebuild it before serving.')
        self.aliases = self.resolution['alias_map']
        self.nodes = {n['id']:n for n in self.bundle['nodes']}
        self.claims = {c['id']:c for c in self.bundle['claims']}
        self.sources = {s['id']:s for s in self.bundle['sources']}
        self.evidence = defaultdict(list)
        self.adjacency = defaultdict(set)
        for row in self.bundle['evidence']: self.evidence[row['claim_id']].append(row)
        for claim in self.claims.values():
            a,b = claim['subject'],claim['object']
            if a not in self.nodes or b not in self.nodes: raise ValueError('Resolved claim has missing endpoint')
            self.adjacency[a].add(b); self.adjacency[b].add(a)
        self.summary = {k:v for k,v in self.resolution.items() if k not in {'decisions','conflicts','model_runs'}}
        # Put the biological anchors and source-backed entities first; large
        # ontology/variant sets remain available through expansion/pagination.
        order = {'Disease':0,'Gene':1,'Publication':2,'Asset':3,'Person':4,'Mechanism':5,'Variant':6}
        self.rank = lambda identifier:(order.get(self.nodes[identifier]['type'],10), self.nodes[identifier]['label'].casefold(),identifier)
        seeds = [s for s in self.resolution['seeds'] if s in self.nodes]
        seen=set(seeds); frontier=seeds; self.overview=list(seeds)
        while frontier:
            adjacent=set().union(*(self.adjacency[i] for i in frontier))-seen
            # Round-robin entity types within each BFS layer. A high-degree gene
            # must not hide papers, researchers, variants or assets at 120 nodes.
            buckets=defaultdict(deque)
            for identifier in sorted(adjacent,key=self.rank): buckets[self.nodes[identifier]['type']].append(identifier)
            frontier=[]
            while any(buckets.values()):
                for kind in sorted(buckets,key=lambda k:(order.get(k,10),k)):
                    if buckets[kind]: frontier.append(buckets[kind].popleft())
            self.overview.extend(frontier); seen.update(frontier)
        self.overview.extend(sorted(self.nodes.keys()-seen,key=self.rank))

    def status(self):
        return {'available':True,**self.summary}

    def _node(self, identifier):
        node=deepcopy(self.nodes[identifier]); node.setdefault('properties',{})['resolved']=True
        return node

    def graph(self, *, limit=120, offset=0, focus=None):
        limit=max(2,min(1000,int(limit))); offset=max(0,int(offset))
        focus=self.aliases.get(focus,focus)
        if focus:
            if focus not in self.nodes: raise KeyError(focus)
            candidates=sorted(self.adjacency[focus],key=self.rank)
            page=candidates[offset:offset+limit-1]
            selected=[focus,*page]; following=offset+len(page)
        else:
            candidates=self.overview
            selected=candidates[offset:offset+limit]; following=offset+len(selected)
        selected_set=set(selected)
        claims=[deepcopy(c) for c in self.claims.values() if c['subject'] in selected_set and c['object'] in selected_set]
        evidence=[deepcopy(e) for c in claims for e in self.evidence[c['id']]]
        source_ids={e['source_id'] for e in evidence}
        # Raw documents are only returned on inspection, not every graph load.
        sources=[{k:v for k,v in self.sources[s].items() if k!='text'} for s in sorted(source_ids)]
        return {'schema_version':'1.0','dataset':self.bundle['dataset'], 'nodes':[self._node(i) for i in selected],
                'claims':claims,'evidence':evidence,'sources':sources,'coverage':[], 'resolution':self.summary,
                'harvest':{'shown_nodes':len(selected),'shown_edges':len(claims),'limit':limit,'focus':focus,
                           'next_offset':following if following<len(candidates) else None,'truncated':following<len(candidates),
                           'total_nodes':len(self.nodes),'total_edges':len(self.claims),'neighborhood_nodes':len(candidates)+(1 if focus else 0)}}

    def search(self, query, *, limit=40):
        query=query.strip().casefold()
        if not query: return {'nodes':[],'total':0}
        matches=[]
        for node in self.nodes.values():
            members=node.get('properties',{}).get('identity_resolution',{}).get('member_ids',[])
            names=[node['id'],node['label'],*node.get('aliases',[]),*members]
            if any(query in str(name).casefold() for name in names): matches.append(node['id'])
        matches.sort(key=lambda i:(not any(query==str(x).casefold() for x in [i,self.nodes[i]['label'],*self.nodes[i].get('aliases',[]),*self.nodes[i].get('properties',{}).get('identity_resolution',{}).get('member_ids',[])]),self.rank(i)))
        return {'nodes':[self._node(i) for i in matches[:limit]],'total':len(matches)}

    def node(self, identifier):
        identifier=self.aliases.get(identifier,identifier)
        if identifier not in self.nodes: return None
        node=self._node(identifier)
        resolution=node['properties']['identity_resolution']; members=set(resolution['member_ids'])
        decisions=[]; conflicts=[]
        for decision in self.resolution['decisions']:
            link=decision['link']
            if link['subject'] in members or link['object'] in members:
                value={**deepcopy(decision),'rationale':f"{link['subject']} ↔ {link['object']} ({link['rule']}).",
                       'provenance':link.get('provenance')}
                (decisions if decision['status'] in {'merged','already_connected'} else conflicts).append(value)
        conflicts.extend(c for c in self.resolution['conflicts'] if c.get('node_id') in members)
        if node['properties'].get('resolution_status')=='unresolved_source_mention':
            conflicts.append({'kind':'unresolved_source_mention','message':node['properties'].get('identity_note','Source-scoped mention; no verified cross-source identity link.')})
        node['identity']={'members':sorted(members),'decisions':decisions,'conflicts':conflicts}
        node['provenance']={'original_nodes':resolution['node_provenance'],'identity_links':resolution['link_provenance'],
                            'mention':node['properties'].get('provenance')}
        return node

    def claim(self, identifier):
        claim=self.claims.get(identifier)
        if claim is None: return None
        rows=self.evidence[identifier]
        return {'claim':deepcopy(claim),'support':[deepcopy(e) for e in rows if e['stance']=='supports'],
                'contradictions':[deepcopy(e) for e in rows if e['stance']=='contradicts'],
                'sources':[deepcopy(self.sources[s]) for s in sorted({e['source_id'] for e in rows})]}

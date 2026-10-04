import gzip
import json
import unittest
from pathlib import Path
from atlas.public_graph import PublicGraphAPI

ROOT=Path(__file__).resolve().parents[1]

class PublicGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harvested=json.loads(gzip.decompress((ROOT/'data/curated/hgnc_dense_snapshot.json.gz').read_bytes()))
        reviewed=json.loads((ROOT/'data/curated/grin_atlas_bundle.json').read_text())
        cls.api=PublicGraphAPI(harvested,reviewed)

    def test_dense_page_retains_reviewed_evidence_and_has_no_dangling_edges(self):
        status,data=self.api.request('/api/harvest/graph',{'limit':['10000']})
        self.assertEqual(status,200)
        self.assertGreaterEqual(len(data['nodes']),10000)
        self.assertIsNone(data['harvest']['next_offset'])
        ids={n['id'] for n in data['nodes']}
        self.assertTrue(all(c['subject'] in ids and c['object'] in ids for c in data['claims']))
        self.assertEqual(data['evidence'],self.api.reviewed['evidence'])

    def test_page_and_focus_are_bounded(self):
        _,first=self.api.request('/api/harvest/graph',{'limit':['120']})
        self.assertEqual(first['harvest']['next_offset'],120)
        focus=self.api.harvested['claims'][0]['subject']
        _,data=self.api.request('/api/harvest/graph',{'focus':[focus],'limit':['120']})
        self.assertIn(focus,{n['id'] for n in data['nodes']})
        self.assertLessEqual(len(data['nodes']),120+len(self.api.reviewed['nodes']))

    def test_public_provenance_and_unknown_record(self):
        node=self.api.harvested['nodes'][0]
        _,data=self.api.request('/api/harvest/node',{'id':[node['id']]})
        self.assertTrue(data['provenance']['source_urls'])
        self.assertTrue(data['provenance']['licenses'])
        self.assertEqual(self.api.request('/api/harvest/record',{'id':['private:missing']})[0],404)
        self.assertEqual(self.api.request('/api/research/state',{})[0],404)

    def test_snapshot_sources_are_public_hgnc_only(self):
        self.assertTrue(all(d['key'].startswith('hgnc/') for d in self.api.datasets.values()))
        self.assertTrue(all(n['type'] in ['Gene','Protein'] for n in self.api.harvested['nodes']))
        self.assertFalse(self.api.harvested['dataset']['synthetic'])

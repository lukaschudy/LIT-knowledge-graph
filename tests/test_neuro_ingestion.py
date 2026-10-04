import gzip
from hashlib import sha256
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from atlas import neuro_ingestion


ROOT = Path(__file__).resolve().parents[1]


class FakeHarvest:
    def __init__(self, root, anchors):
        self.source_root = Path(root)
        self.path = self.source_root / 'index.sqlite'
        self.dataset_id = 1
        self.anchor_by_id = {item['registry_id']: item for item in anchors}

    def datasets(self):
        return [{'id': f'dataset:{self.dataset_id}', 'dataset_id': self.dataset_id, 'key': 'europe_pmc_diseases/articles',
                 'path': 'articles.jsonl.gz', 'sha256': 'snapshot-articles', 'processed_rows': 1}]

    def record(self, dataset_id, row):
        return {'dataset_id': dataset_id, 'row': row, 'path': 'articles.jsonl.gz'}

    def node(self, identifier):
        item = self.anchor_by_id.get(identifier)
        if item is None:
            return None
        return {'id': item['registry_id'], 'type': item['type'], 'label': item['registry_label'],
                'aliases': [], 'properties': {}, 'provenance': {'dataset_id': 2, 'row': 1,
                'path': 'registry.jsonl.gz', 'sha256': 'registry-snapshot'}}

    def graph(self, focus=None, limit=180):
        node = self.node(focus)
        return {'nodes': [node] if node else [], 'claims': []}

    def status(self):
        return {'stats': {'build_id': 'fixture-build', 'status': 'complete'}}


class NeuroIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'out'
        self.output.mkdir()
        config = json.loads((ROOT / 'data/curated/neuro-identities.json').read_text())
        self.anchors = config['anchors']
        self.harvest = FakeHarvest(self.root, self.anchors)
        with gzip.open(self.root / 'articles.jsonl.gz', 'wt', encoding='utf-8') as stream:
            # Deliberately has no rows for the curated PMCIDs.
            stream.write(json.dumps({'pmcid': 'PMC0000000', 'title': 'Unrelated'}) + '\n')
        with closing(sqlite3.connect(self.harvest.path)) as db:
            db.execute('CREATE TABLE nodes(nid INTEGER PRIMARY KEY,id TEXT,type TEXT)')
            db.execute('CREATE TABLE edges(eid INTEGER PRIMARY KEY,subject INTEGER,object INTEGER)')
            db.commit()

    def test_prepare_uses_checked_anchor_ids_and_keeps_pmcid_only_when_metadata_absent(self):
        proof = {'data': {'ensembl_gene_id': '', 'entrez_id': '', 'omim_id': '', 'tags': {'property_value': []}}}
        with patch('atlas.neuro_ingestion.read_record', return_value=proof):
            prepared = neuro_ingestion.prepare_neuro(ROOT, self.harvest, self.output)
        link_map = {(link['subject'], link['object'], link['rule']) for link in prepared['links']}
        for anchor in self.anchors:
            self.assertIn((anchor['local_id'], anchor['registry_id'], 'curated_identifier'), link_map)
            anchor_link = next(link for link in prepared['links']
                               if link['subject'] == anchor['local_id'] and link['object'] == anchor['registry_id'])
            self.assertEqual(anchor_link['provenance']['record']['path'], 'registry.jsonl.gz')
        by_id = {node['id']: node for node in prepared['nodes']}
        docs = prepared['documents']
        for doc in docs:
            publication_id = doc['publication_id']
            self.assertTrue(publication_id.startswith('PMCID:'))
            publication = by_id[publication_id]
            self.assertIn('author and DOI metadata unavailable', publication['properties']['metadata_status'])
            self.assertEqual(publication['provenance']['source_id'], doc['source_id'])
            self.assertEqual(publication['provenance']['url'], doc['url'])
            self.assertEqual(publication['provenance']['version'], doc['version'])
        curated = json.loads((ROOT / 'data/curated/neuro_bundle.json').read_text())
        self.assertFalse(any(node['type'] == 'Person' for node in prepared['nodes']))
        self.assertTrue({source['id'] for source in curated['sources']} <= {source['id'] for source in prepared['sources']})
        self.assertTrue({item['id'] for item in curated['evidence']} <= {item['id'] for item in prepared['evidence']})
        self.assertFalse(any(claim['predicate'] == 'AUTHORED' for claim in prepared['claims']))
        prepared_claim_ids = {claim['id'] for claim in prepared['claims']}
        self.assertTrue({claim['id'] for claim in curated['claims']} <= prepared_claim_ids,
                        'Curated neuro evidence claims must survive ingestion.')
        nodes_by_id = {node['id']: node for node in prepared['nodes']}
        for claim in curated['claims']:
            self.assertIn(claim['subject'], nodes_by_id)
            self.assertIn(claim['object'], nodes_by_id)

    def test_anchor_registry_mismatch_fails_closed(self):
        bad = FakeHarvest(self.root, self.anchors)
        original_node = bad.node

        def wrong_label(identifier):
            result = original_node(identifier)
            if result:
                result['label'] = 'wrong label'
            return result

        bad.node = wrong_label
        with patch('atlas.neuro_ingestion.read_record', return_value={'data': {}}):
            with self.assertRaisesRegex(ValueError, 'Registry anchor differs'):
                neuro_ingestion.prepare_neuro(ROOT, bad, self.output)

    def test_paper_record_cache_is_bound_to_dataset_identity(self):
        with gzip.open(self.root / 'articles.jsonl.gz', 'wt', encoding='utf-8') as stream:
            stream.write(json.dumps({'pmcid': 'PMC123', 'title': 'Exact identifier match'}) + '\n')
        doc = [{'source_id': 'paper:test', 'url': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/'}]
        cache = self.output / 'paper-cache.json'
        first = neuro_ingestion.paper_records(self.harvest, doc, cache)
        self.assertEqual(first[0]['pointer']['dataset_id'], 1)
        self.harvest.dataset_id = 7
        second = neuro_ingestion.paper_records(self.harvest, doc, cache)
        self.assertEqual(second[0]['pointer']['dataset_id'], 7)

    def test_build_remaps_claim_endpoints_and_deduplicates_extracted_known_nodes(self):
        prepared = {
            'nodes': [
                {'id': 'HP:0001103', 'type':'Disease','label':'Abnormal macular morphology'},
                {'id': 'gene:EPG5', 'type': 'Gene', 'label': 'EPG5', 'aliases': [], 'properties': {}},
                {'id': 'HGNC:29331', 'type': 'Gene', 'label': 'EPG5', 'aliases': [], 'properties': {}},
                {'id': 'disease:vici', 'type': 'Disease', 'label': 'Vici syndrome', 'aliases': [], 'properties': {}},
                {'id': 'MONDO:0009452', 'type': 'Disease', 'label': 'Vici syndrome', 'aliases': [], 'properties': {}},
                {'id': 'mechanism:autophagy', 'type': 'Mechanism', 'label': 'Autophagy', 'aliases': [], 'properties': {}},
                {'id': 'PMCID:PMC1', 'type': 'Publication', 'label': 'Paper', 'aliases': [], 'properties': {}},
                {'id': 'phenotype:a', 'type': 'Phenotype', 'label': 'Feature', 'aliases': [], 'properties': {}},
                {'id': 'phenotype:b', 'type': 'Phenotype', 'label': 'Feature', 'aliases': [], 'properties': {}},
                {'id': 'HP:0001', 'type': 'Phenotype', 'label': 'Feature', 'aliases': [], 'properties': {}},
            ],
            'links': [
                {'subject': 'gene:EPG5', 'object': 'HGNC:29331', 'rule': 'curated_identifier', 'provenance': {'source': 'curated mapping'}},
                {'subject': 'disease:vici', 'object': 'MONDO:0009452', 'rule': 'curated_identifier', 'provenance': {'source': 'curated mapping'}},
                {'subject': 'phenotype:a', 'object': 'HP:0001', 'rule': 'curated_identifier', 'provenance': {'source': 'curated mapping'}},
                {'subject': 'phenotype:b', 'object': 'HP:0001', 'rule': 'curated_identifier', 'provenance': {'source': 'curated mapping'}},
            ],
            'claims': [{'id': 'claim:prepared', 'subject': 'gene:EPG5', 'predicate': 'ASSOCIATED_WITH_DISEASE',
                        'object': 'disease:vici', 'assertion_type': 'reported', 'context': {}, 'extraction_confidence': None}],
            'evidence': [], 'sources': [],
            'documents': [{'source_id': 'paper:one', 'title': 'Paper', 'text': 'Text', 'url': 'https://example.org/paper',
                           'license': 'CC BY 4.0', 'version': sha256(b'Text').hexdigest(), 'publication_id': 'PMCID:PMC1'}],
            'seeds': ['gene:EPG5', 'disease:vici', 'mechanism:autophagy'],
            'harvest_snapshot': {'status': 'complete'}, 'scope': 'test',
        }
        extracted = {
            # This repeats the already known HGNC node ID with an inconsistent
            # model label. It must not create a duplicate or overwrite registry data.
            'nodes': [
                {'id': 'HGNC:29331', 'type': 'Gene', 'label': 'Wrong model label', 'aliases': [], 'properties': {}},
                {'id': 'mention:paper:mechanism', 'type': 'Mechanism', 'label': 'Autophagy flux', 'aliases': [],
                 'properties': {'resolution_status': 'unresolved_source_mention','provenance':{'source_id':'paper:one','source_version':sha256(b'Text').hexdigest(),'excerpt':'Text'}}},
            ],
            'claims': [{'id': 'claim:extracted', 'subject': 'gene:EPG5', 'predicate': 'HAS_EFFECT',
                        'object': 'mention:paper:mechanism', 'assertion_type': 'reported', 'context': {},
                        'extraction_confidence': 0.8},
                       {'id': 'claim:self', 'subject': 'phenotype:a', 'predicate': 'IS_A',
                        'object': 'phenotype:b', 'assertion_type': 'reported', 'context': {},
                        'extraction_confidence': 0.7}],
            'evidence': [
                {'id': 'evidence:extracted', 'claim_id': 'claim:extracted', 'source_id': 'paper:one',
                 'source_version': sha256(b'Text').hexdigest(), 'locator': 'chars 0-4', 'excerpt': 'Text', 'stance': 'supports',
                 'review_status': 'unreviewed'},
                {'id': 'evidence:self', 'claim_id': 'claim:self', 'source_id': 'paper:one',
                 'source_version': sha256(b'Text').hexdigest(), 'locator': 'chars 0-4', 'excerpt': 'Text', 'stance': 'supports',
                 'review_status': 'unreviewed'},
            ],
            'sources': [{'id': 'paper:one', 'title': 'Paper', 'url': 'https://example.org/paper', 'kind': 'paper',
                         'retrieved_at': '2026-10-04', 'published_at': None, 'license': 'CC BY 4.0',
                         'version': sha256(b'Text').hexdigest(), 'synthetic': False}],
            'metadata': {'review_status': 'unreviewed'},
        }
        db = self.root / 'harvest.sqlite'
        with closing(sqlite3.connect(db)) as conn:
            conn.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            conn.execute("INSERT INTO metadata(key,value) VALUES('source_root',?)", (str(self.root),))
            conn.execute("INSERT INTO metadata(key,value) VALUES('build_id','fixture-build')")
            conn.commit()
        output_path = self.output / 'resolved.json'
        with patch('atlas.neuro_ingestion.HarvestGraph', return_value=self.harvest), \
             patch('atlas.neuro_ingestion.prepare_neuro', return_value=prepared), \
             patch('atlas.entity_extraction.extract_entities_and_relationships', return_value=extracted):
            result = neuro_ingestion.build_neuro(ROOT, db, output_path, client=object(), extract=True)
        node_rows = [node for node in result['nodes'] if node['id'] == 'HGNC:29331']
        self.assertEqual(len(node_rows), 1)
        self.assertEqual(node_rows[0]['label'], 'EPG5')
        hpo=next(n for n in result['nodes'] if n['id']=='HP:0001103')
        self.assertEqual(hpo['type'],'Phenotype')
        self.assertEqual(hpo['properties']['type_resolution']['source_type'],'Disease')
        claims = {claim['id']: claim for claim in result['claims']}
        self.assertEqual(claims['claim:prepared']['subject'], 'HGNC:29331')
        self.assertEqual(claims['claim:prepared']['object'], 'MONDO:0009452')
        self.assertEqual(claims['claim:extracted']['subject'], 'HGNC:29331')
        self.assertEqual(claims['claim:extracted']['object'], 'mention:paper:mechanism')
        self.assertNotIn('claim:self', claims)
        self.assertEqual(sum(row['claim_id'] == 'claim:extracted' for row in result['evidence']), 1)
        self.assertNotIn('evidence:self', {row['id'] for row in result['evidence']})

        # A cached extraction still crosses the integrity boundary. Corruption
        # must fail before the previously valid artifact is replaced.
        before=output_path.read_bytes()
        cache=next((output_path.parent/'entity-extractions').glob('*.json'))
        corrupted=json.loads(cache.read_text())
        corrupted['evidence'][0]['excerpt']='Invented quotation'
        cache.write_text(json.dumps(corrupted))
        with patch('atlas.neuro_ingestion.HarvestGraph', return_value=self.harvest), \
             patch('atlas.neuro_ingestion.prepare_neuro', return_value=prepared), \
             patch('atlas.entity_extraction.extract_entities_and_relationships') as extractor:
            with self.assertRaisesRegex(ValueError, 'does not match its source snapshot'):
                neuro_ingestion.build_neuro(ROOT,db,output_path,client=object(),extract=True)
            extractor.assert_not_called()
        self.assertEqual(output_path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()

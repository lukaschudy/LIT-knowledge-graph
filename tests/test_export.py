"""Exports retain enough provenance to distinguish current from stale review."""
import json
from pathlib import Path
import unittest

from atlas.export import to_jsonld


class JsonLdProvenanceTests(unittest.TestCase):
    def test_reviewed_evidence_preserves_current_and_stale_version_binding(self):
        bundle = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
        evidence = bundle['evidence'][0]
        source = next(s for s in bundle['sources'] if s['id'] == evidence['source_id'])
        source['version'] = 'fixture-v1'
        evidence.update(source_version='fixture-v1', review_status='human_reviewed')
        for version, status in ((source['version'], 'active'), ('newer-source-version', 'superseded')):
            with self.subTest(version=version):
                source.update(version=version, status=status)
                exported = to_jsonld(bundle)
                records = {row['@id']: row for row in exported['@graph']}
                exported_evidence, exported_source = records[evidence['id']], records[source['id']]
                self.assertEqual(exported_evidence['sourceVersion'], evidence['source_version'])
                self.assertEqual(exported_source['version'], version)
                self.assertEqual(exported_source['status'], status)
                self.assertEqual(exported_evidence['reviewStatus'], 'human_reviewed')
                self.assertEqual(exported['@context']['sourceVersion'], 'atlas:sourceVersion')
                self.assertEqual(exported['@context']['version'], 'atlas:version')
                self.assertEqual(exported_evidence['source']['@id'], exported_source['@id'])

    def test_unversioned_evidence_does_not_acquire_an_invented_version(self):
        bundle = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
        exported = to_jsonld(bundle)
        evidence_ids = {e['id'] for e in bundle['evidence']}
        self.assertTrue(all('sourceVersion' not in row for row in exported['@graph'] if row['@id'] in evidence_ids))

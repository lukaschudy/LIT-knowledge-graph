"""The validation result covers JSON compatibility of the complete payload."""
import json
from pathlib import Path
import unittest

from atlas.model import validate_bundle


class ModelJsonBoundaryTests(unittest.TestCase):
    def test_non_json_extension_metadata_is_rejected_at_every_record_boundary(self):
        for bucket in ('bundle', 'dataset', 'nodes', 'sources', 'claims', 'evidence', 'coverage'):
            for value in (float('nan'), float('inf'), {1, 2}, b'opaque bytes', {1: 'non-string key'}):
                with self.subTest(bucket=bucket, value=type(value).__name__):
                    bundle = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
                    target = bundle if bucket == 'bundle' else bundle['dataset'] if bucket == 'dataset' else bundle[bucket][0]
                    target['extra_metadata'] = {'nested': [value]}
                    self.assertTrue(validate_bundle(bundle))

    def test_json_compatible_extension_metadata_remains_allowed(self):
        bundle = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
        bundle['sources'][0]['extra_metadata'] = {'nested': [None, True, 1, 1.5, 'text']}
        self.assertEqual(validate_bundle(bundle), [])

    def test_cyclic_and_excessively_deep_payloads_return_validation_errors(self):
        for mode in ('cycle', 'depth'):
            with self.subTest(mode=mode):
                bundle = json.loads((Path(__file__).parents[1] / 'data/fixtures/atlas-demo.json').read_text())
                if mode == 'cycle':
                    bundle['extra_metadata'] = bundle
                else:
                    nested = bundle
                    for _ in range(2000):
                        nested['extra_metadata'] = {}
                        nested = nested['extra_metadata']
                errors = validate_bundle(bundle)
                self.assertTrue(errors)
                self.assertIn('RecursionError', errors[0])
                if mode == 'cycle':
                    self.assertIs(bundle['extra_metadata'], bundle)

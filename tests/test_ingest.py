import unittest
from atlas.ingest import hpoa_to_bundle

HEADER='#database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tbiocuration\n'
class HPOAAdapterTests(unittest.TestCase):
    def convert(self,text):
        return hpoa_to_bundle(text,source_url='https://example.org/hpoa',retrieved_at='2026-10-03',source_version='test-fixture',license='test')
    def test_negative_and_timing_are_preserved(self):
        b=self.convert('#version: test\n'+HEADER+'OMIM:1\tTest disease\tNOT\tHP:0000001\tPMID:123\tTAS\tHP:0003577\t1/2\tcurator[2026-01-01]\n')
        c=b['claims'][0]
        self.assertTrue(c['context']['negated'])
        self.assertEqual(c['context']['frequency'],'1/2')
        self.assertEqual(c['context']['onset'],'HP:0003577')
        self.assertIn('PMID:123',b['evidence'][0]['locator'])
        self.assertEqual(b['evidence'][0]['stance'],'supports') # supports NEGATIVE assertion
    def test_duplicate_rows_idempotent(self):
        row='OMIM:1\tTest\t\tHP:0000001\tPMID:1\tTAS\t\t\t\n'
        self.assertEqual(len(self.convert(HEADER+row+row)['claims']),1)
    def test_unknown_qualifier_rejected(self):
        with self.assertRaises(ValueError): self.convert(HEADER+'OMIM:1\tTest\tMAYBE\tHP:1\tPMID:1\tTAS\t\t\t\n')
    def test_missing_header_rejected(self):
        with self.assertRaises(ValueError): self.convert('not a dataset')
    def test_short_row_rejected(self):
        with self.assertRaises(ValueError): self.convert(HEADER+'OMIM:1\tTest\n')

    def test_locator_tracks_original_lines_including_comments(self):
        row='OMIM:1\tTest\t\tHP:0000001\tPMID:1\tTAS\t\t\t\n'
        b=self.convert('#version: test\n'+HEADER+'#comment\n'+row)
        self.assertIn('HPOA row 4;',b['evidence'][0]['locator'])

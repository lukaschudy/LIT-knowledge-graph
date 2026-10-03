import gzip
import tempfile
import unittest
from pathlib import Path

from harvest.biology import obo_stanzas, tsv_rows, xml_records


class BiologyParserTests(unittest.TestCase):
    def test_obo_preserves_repeated_tags_and_obsolete_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tiny.obo'
            path.write_text('format-version: 1.2\ndata-version: test\n\n[Term]\nid: HP:0000001\nname: All\nsynonym: "Whole" EXACT []\nsynonym: "Everything" RELATED []\nis_a: HP:0000000 ! root\nis_obsolete: true\nreplaced_by: HP:0000002\n')
            rows = list(obo_stanzas(path))
        self.assertEqual(rows[0]['stanza_type'], 'header')
        self.assertEqual(rows[0]['tags']['data-version'], ['test'])
        term = rows[1]['tags']
        self.assertEqual(len(term['synonym']), 2)
        self.assertIn('is_a', term)
        self.assertEqual(term['is_obsolete'], ['true'])
        self.assertEqual(term['replaced_by'], ['HP:0000002'])

    def test_tsv_preserves_empty_values_and_full_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tiny.tsv'
            path.write_text('#version: x\nid\tqualifier\tfrequency\nX\tNOT\t\n')
            rows = list(tsv_rows(path))
        self.assertEqual(rows, [{'id': 'X', 'qualifier': 'NOT', 'frequency': ''}])

    def test_clinvar_commented_header_is_a_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clinvar.tsv'
            path.write_text('#AlleleID\tType\tClinicalSignificance\n1\tSNV\tConflicting classifications\n')
            rows = list(tsv_rows(path))
        self.assertEqual(rows, [{'AlleleID': '1', 'Type': 'SNV', 'ClinicalSignificance': 'Conflicting classifications'}])

    def test_xml_keeps_attributes_repeated_children_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tiny.xml'
            path.write_text('<Root><Disorder id="1"><Name lang="en">A</Name><Name lang="fr">B</Name></Disorder></Root>')
            rows = list(xml_records(path, 'Disorder'))
        self.assertEqual(rows[0]['attributes'], {'id': '1'})
        self.assertEqual([child['text'] for child in rows[0]['children']], ['A', 'B'])
        self.assertEqual(rows[0]['children'][1]['attributes'], {'lang': 'fr'})


if __name__ == '__main__':
    unittest.main()

import unittest
from pathlib import Path
from harvest.enrichment import gaf_records, delimited

class EnrichmentParserTests(unittest.TestCase):
    def test_gaf_preserves_negative_qualifier_and_evidence(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p=Path(d)/'x.gaf'
            p.write_text('!gaf-version: 2.2\nUniProtKB\tP12345\tGENE\tNOT|enables\tGO:0000001\tPMID:1\tIDA\t\tF\tName\t\tprotein\ttaxon:9606\t20260101\tUniProt\t\t\n')
            row=list(gaf_records(p))[0]
            self.assertEqual(row['qualifier'],'NOT|enables')
            self.assertEqual(row['evidence_code'],'IDA')
            self.assertEqual(row['go_id'],'GO:0000001')

    def test_delimited_preserves_multiple_native_columns(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as d:
            p=Path(d)/'x.tsv';p.write_text('id\taliases\n1\tA|B\n')
            self.assertEqual(list(delimited(p)),[{'id':'1','aliases':'A|B'}])

if __name__=='__main__': unittest.main()

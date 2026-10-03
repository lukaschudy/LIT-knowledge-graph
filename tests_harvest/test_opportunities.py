import unittest
from harvest.opportunities import TERMS, grants_search_body, _ot_query_batch, grin_disease_mondo_ids

class OpportunityHarvestTests(unittest.TestCase):
    def test_grants_search_pagination_and_statuses(self):
        body=grants_search_body('rare disease',200,100)
        self.assertEqual(body['startRecordNum'],200)
        self.assertEqual(body['rows'],100)
        self.assertEqual(body['oppStatuses'],'forecasted|posted')
        self.assertTrue({'rare disease','orphan disease','orphan drug'}.issubset(TERMS))

    def test_open_targets_query_keeps_identifiers_and_association_fields(self):
        query=_ot_query_batch(['MONDO_0000001','MONDO_0000002'])
        self.assertIn('d0: disease(efoId:"MONDO_0000001")',query)
        self.assertIn('d1: disease(efoId:"MONDO_0000002")',query)
        self.assertIn('datasourceScores',query)
        self.assertIn('drugAndClinicalCandidates',query)

    def test_grin_curated_disease_ids_include_clingen_complex_ndd(self):
        ids=grin_disease_mondo_ids()
        self.assertIn('MONDO_0100038',ids)
        self.assertTrue(any(x['gene']=='GRIN2A' for x in ids['MONDO_0100038']))
        self.assertTrue(any(x['gene']=='GRIN2B' for x in ids['MONDO_0100038']))

if __name__=='__main__': unittest.main()

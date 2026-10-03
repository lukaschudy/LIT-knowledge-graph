import unittest
from harvest.literature import vocabulary,batches,query_for_group

class VocabularyTests(unittest.TestCase):
    def test_ambiguous_aliases_excluded_but_short_preferred_kept(self):
        result=vocabulary([{'Rare Disease Name':'ABC','Disease Aliases':'ABC//other name syndrome//AMBIGUOUS','Disease Annotations':'d:1'}, {'Rare Disease Name':'other name syndrome','Disease Annotations':'d:2'}])
        terms={x['term']:x['disease_source_ids'] for x in result}
        self.assertEqual(terms,{'abc':['d:1'],'other name syndrome':['d:1','d:2']})
    def test_generic_alias_excluded_without_reflowing_other_batches(self):
        group=[{'term':'tetralogy of fallot'},{'term':'the syndrome'},{'term':'thiamine metabolism dysfunction syndrome 1'}]
        self.assertEqual(query_for_group(group),'(TITLE_ABS:"tetralogy of fallot" OR TITLE_ABS:"thiamine metabolism dysfunction syndrome 1")')
        self.assertEqual(len(group),3)
    def test_batching_never_drops_vocabulary_terms(self):
        terms=[{'term':'example syndrome '+str(i)} for i in range(123)]
        groups=list(batches(terms,max_chars=100))
        self.assertEqual([x for group in groups for x in group],terms)

class RecheckTests(unittest.TestCase):
    def test_legacy_recovery_stays_with_original_query(self):
        from harvest.literature_repair import comparisons_and_recoveries
        old={'query_id':'old','added_ids':['MED:1']}
        new={'query_id':'new','added_ids':['MED:2']}
        comparisons,recoveries=comparisons_and_recoveries({'comparison':new,'comparisons':{'old':old,'new':new},'recovery':{'identifiers':['MED:1']}})
        self.assertEqual(set(recoveries),{'old'})
        self.assertEqual(set(comparisons),{'old','new'})
    def test_export_timestamps_cannot_hide_missing_recovered_article(self):
        from unittest.mock import patch
        from harvest.literature_repair import finalize
        q={'query_id':'q','added_ids':['MED:1']}
        recheck={'comparison':q,'recovery':{'identifiers':['MED:1'],'merged_to_main_database_at':'2026-10-03T00:00:00+00:00'}}
        main={'status':'complete_with_query_gaps','datasets':{name:{'created_at':'2026-10-04T00:00:00+00:00'} for name in ['articles','query_membership']}}
        with patch('harvest.literature_repair.manifest',side_effect=[main,recheck]), patch('harvest.literature_repair.read_records',return_value=iter([])):
            with self.assertRaisesRegex(ValueError,'recovered article IDs missing'):
                finalize()
    def test_changed_provider_counts_cannot_clear_gap(self):
        from harvest.literature_repair import reconciled
        report={'reported_counts':[10,11],'recheck_unique_ids':10,'absent_ids':[]}
        self.assertFalse(reconciled(report,10))
        report['reported_counts']=[10]
        self.assertTrue(reconciled(report,10))
        report['absent_ids']=['MED:1']
        self.assertFalse(reconciled(report,10))

if __name__=='__main__':unittest.main()

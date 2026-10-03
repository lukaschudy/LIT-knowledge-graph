import unittest
from harvest.literature import vocabulary,batches

class VocabularyTests(unittest.TestCase):
    def test_ambiguous_aliases_excluded_but_short_preferred_kept(self):
        result=vocabulary([{'Rare Disease Name':'ABC','Disease Aliases':'ABC//other name syndrome//AMBIGUOUS','Disease Annotations':'d:1'}, {'Rare Disease Name':'other name syndrome','Disease Annotations':'d:2'}])
        terms={x['term']:x['disease_source_ids'] for x in result}
        self.assertEqual(terms,{'abc':['d:1'],'other name syndrome':['d:1','d:2']})
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
    def test_changed_provider_counts_cannot_clear_gap(self):
        from harvest.literature_repair import reconciled
        report={'reported_counts':[10,11],'recheck_unique_ids':10,'absent_ids':[]}
        self.assertFalse(reconciled(report,10))
        report['reported_counts']=[10]
        self.assertTrue(reconciled(report,10))
        report['absent_ids']=['MED:1']
        self.assertFalse(reconciled(report,10))

if __name__=='__main__':unittest.main()

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

if __name__=='__main__':unittest.main()

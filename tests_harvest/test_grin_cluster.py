import unittest
from harvest.grin_cluster import central_value,normalized_feature
class GrinFeatures(unittest.TestCase):
 def test_ratio_direction_and_missingness(self):
  p={'name':'glutamate EC50','variant':'6,418 ± 278','wt_control':'3.4 ± 0.11 µM; n=51'}
  self.assertAlmostEqual(normalized_feature(p)['ratio'],3.4/6418)
  p['name']='peak current density';p['variant']='1.2 ± 0.5';p['wt_control']='19 ± 3.6; n=16'
  self.assertAlmostEqual(normalized_feature(p)['ratio'],1.2/19)
  for value in (None,'ND','>100','<0.01'):
   p['variant']=value;self.assertIsNone(normalized_feature(p))
 def test_sample_size_is_not_a_value(self):
  self.assertEqual(central_value('0.30 [0.24, 0.38] (11)'),0.30)
  self.assertIsNone(central_value('n=12'))
if __name__=='__main__':unittest.main()

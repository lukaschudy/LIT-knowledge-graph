import copy,json,unittest
from harvest.grin_bundle import EVIDENCE,build,core_eligible
from atlas.model import validate_bundle
from atlas.reasoning import AtlasReasoner

class GrinCohortTests(unittest.TestCase):
 def setUp(self):
  self.e=json.loads(EVIDENCE.read_text());self.sources={s['source_id']:s for s in self.e['sources']}
 def test_core_requires_primary_assay_and_comparator(self):
  v=copy.deepcopy(self.e['variants'][0]);self.assertTrue(core_eligible(v,self.sources))
  v['functional_evidence']=[];self.assertFalse(core_eligible(v,self.sources))
  v['clinical_significance']='Pathogenic';self.assertFalse(core_eligible(v,self.sources))
 def test_possible_opposite_unknown_not_core(self):
  self.assertEqual(sum(core_eligible(v,self.sources) for v in self.e['variants']),6)
  for label in ['Possible LoF','Possible GoF','No detectable effect']:
   v=copy.deepcopy(self.e['variants'][0]);v['integrated_function']['source_classification']=label
   self.assertFalse(core_eligible(v,self.sources))
 def test_exact_source_controls_and_discrepant_identity(self):
  v=next(v for v in self.e['variants'] if v['reported_protein']=='p.Ser541Gly')
  self.assertEqual(v['identity_status'],'publication_cdna_protein_discrepancy')
  tau=next(m for m in v['functional_evidence'][0]['measured_parameters'] if 'deactivation' in m['name'])
  self.assertEqual(tau['wt_control'],'1061 ± 91 ms; n=16')
  self.assertNotIn('c.1621A>C',v['variant_id'])
 def test_real_bundle_paths_keep_controls_separate(self):
  b=build();self.assertEqual(validate_bundle(b),[]);self.assertFalse(b['dataset']['synthetic'])
  r=AtlasReasoner(b).explore('cohort:grin2b:core_likely_reduced')
  by={c['disease']['properties']['cohort_tier']:c['status'] for c in r['candidates']}
  self.assertEqual(by['core_likely_reduced'],'supported_lead')
  self.assertEqual(by['provisional_possible_reduced'],'needs_review')
  self.assertEqual(by['opposing_control'],'rejected')
  self.assertEqual(by['unresolved_control'],'needs_review')
  self.assertTrue(any(o['asset']['id']=='asset:grin-registry' and o['status']=='supported_route' for o in r['opportunities']))
  self.assertFalse(any(e['review_status']=='human_reviewed' for e in b['evidence']))
if __name__=='__main__':unittest.main()

import unittest
from unittest.mock import patch
from harvest import core
from harvest.opportunities import TERMS, grants_search_body, _ot_query_batch, _association_page_query, _association_full_query, _association_prefix_query, _initial_association_records, _association_audit_complete, _association_prefix_children, _prefix_partition_complete, grin_disease_mondo_ids

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

    def test_open_targets_association_continuation_query_uses_requested_page_and_scores(self):
        query=_association_page_query(['MONDO_0000001','MONDO_0000002'],3,100)
        self.assertIn('page:{index:3,size:100}',query)
        self.assertIn('d1: disease(efoId:"MONDO_0000002")',query)
        self.assertIn('datasourceScores { id score }',query)
        self.assertIn('datatypeScores { id score }',query)

    def test_open_targets_tie_stable_repair_query_uses_one_page_or_prefix_partition(self):
        full=_association_full_query([('MONDO_0000107',864)])
        self.assertIn('index:0,size:864',full)
        self.assertIn('orderByScore:"score desc"',full)
        prefix=_association_prefix_query([('MONDO_0001056','ENSG000001')])
        self.assertIn('BFilter:"ENSG000001"',prefix)
        self.assertIn('index:0,size:3000',prefix)

    def test_open_targets_rebuild_uses_immutable_page_zero_and_requires_uniqueness_audit(self):
        diseases=[{'id':'MONDO_1','name':'example','rare_source_identifiers':[{'id':'x'}],'associatedTargets':{'count':1,'rows':[{'target':{'id':'ENSG1'},'score':0.1}]}}]
        rows=list(_initial_association_records(diseases))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['target_association']['target']['id'],'ENSG1')
        self.assertEqual(rows[0]['rare_source_identifiers'],[{'id':'x'}])
        self.assertFalse(_association_audit_complete(1,1,None))
        self.assertFalse(_association_audit_complete(1,1,{'distinct_target_count_mismatches':0,'duplicate_rows':1}))
        self.assertTrue(_association_audit_complete(1,1,{'distinct_target_count_mismatches':0,'duplicate_rows':0}))

    def test_open_targets_association_rebuild_does_not_reuse_flattened_continuations(self):
        diseases=[{'id':'MONDO_1','name':'example','associatedTargets':{'count':2,'rows':[{'target':{'id':'ENSG1'},'score':0.1}]}}]
        first=list(_initial_association_records(diseases))
        flattened=first+[{'disease_id':'MONDO_1','target_association':{'target':{'id':'ENSG2'},'score':0.2},'page_index':1}]
        rerun_first=list(_initial_association_records(diseases))
        self.assertEqual(len(flattened),2)
        self.assertEqual(len(rerun_first),1)
        self.assertEqual(rerun_first[0]['target_association']['target']['id'],'ENSG1')

    def test_open_targets_prefix_partition_expands_and_checks_children(self):
        pending=[('ENSG000001',3500)]
        observed=[]
        while pending:
            prefix,count=pending.pop(0)
            observed.append(prefix)
            children=_association_prefix_children(prefix,count,3000)
            if children:
                child_counts=[2500,1000]+[0]*8 if prefix=='ENSG000001' else [count]
                self.assertEqual(len(children),10)
                self.assertTrue(_prefix_partition_complete(count,child_counts))
                pending.extend(zip(children,child_counts))
        self.assertEqual(len(observed),11)
        self.assertIn('ENSG0000010',observed)

    def test_grin_curated_disease_ids_include_clingen_complex_ndd(self):
        # These are curated source shapes, not a dependency on an ignored local
        # multi-million-record harvest. Include an unrelated gene as a negative.
        fixtures={
            'mondo/obo_stanzas.jsonl.gz': [{'tags': {'id':['MONDO:0100038'], 'xref':['OMIM:613970']}}],
            'clingen/gene_disease_validity.jsonl.gz': [
                {'GENE ID (HGNC)':'HGNC:4585','DISEASE ID (MONDO)':'MONDO:0100038'},
                {'GENE ID (HGNC)':'HGNC:4586','DISEASE ID (MONDO)':'MONDO:0100038'},
                {'GENE ID (HGNC)':'HGNC:9999','DISEASE ID (MONDO)':'MONDO:9999999'},
            ],
            'gencc/assertions.jsonl.gz': [{'gene_curie':'HGNC:4585','disease_curie':'OMIM:613970'}],
        }
        def read_fixture(path):
            return iter(fixtures.get(str(path.relative_to(core.PROCESSED)),[]))
        with patch.object(core,'read_records',side_effect=read_fixture):
            ids=grin_disease_mondo_ids()
        self.assertNotIn('MONDO_9999999',ids)
        self.assertTrue(any(x['provider']=='gencc' and x['native_disease_id']=='OMIM:613970' for x in ids['MONDO_0100038']))
        self.assertIn('MONDO_0100038',ids)
        self.assertTrue(any(x['gene']=='GRIN2A' for x in ids['MONDO_0100038']))
        self.assertTrue(any(x['gene']=='GRIN2B' for x in ids['MONDO_0100038']))

if __name__=='__main__': unittest.main()

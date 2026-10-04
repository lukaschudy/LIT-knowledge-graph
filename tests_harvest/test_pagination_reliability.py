"""Provider pagination fixtures: cycles, duplicates, and drifting result totals."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from harvest import core, literature, literature_recheck, opportunities


class PaginationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for module in (core,literature,literature_recheck):
            for name,value in {'ROOT':self.root,'RAW':self.root/'raw','PROCESSED':self.root/'processed'}.items():
                self.stack.enter_context(patch.object(module,name,value))
        self.stack.enter_context(patch.object(core,'MANIFESTS',self.root/'manifests'))
        self.stack.enter_context(patch.object(core.time,'sleep'))
        self.stack.enter_context(patch('builtins.print'))
        self.stack.enter_context(patch.object(core.SESSION,'request',side_effect=AssertionError('No network')))

    def opportunity_pages(self,pages):
        pending=iter(pages)
        def next_page(path):
            try:return deepcopy(next(pending))
            except StopIteration:raise AssertionError('Pagination requested another page after failing to advance')
        self.stack.enter_context(patch.object(opportunities,'TERMS',('rare disease',)))
        self.stack.enter_context(patch.object(opportunities,'_json',side_effect=next_page))
        download=self.stack.enter_context(patch.object(core,'download',return_value=self.root/'raw/page.json'))
        self.stack.enter_context(patch.object(core,'emit_records',return_value=self.root/'output.jsonl.gz'))
        publish=self.stack.enter_context(patch.object(core,'update_manifest'))
        return download,publish

    def test_grants_nonadvancing_offset_terminates_before_repeating_forever(self):
        page={'data':{'hitCount':3,'startRecord':0,'oppHits':[{'id':'1'}]}}
        download,publish=self.opportunity_pages([page,page])
        with self.assertRaisesRegex(RuntimeError,'did not advance'):
            opportunities.harvest_grants_gov(page_size=1)
        self.assertEqual(download.call_count,2)
        publish.assert_not_called()

    def test_grants_duplicate_hits_cannot_satisfy_completeness_count(self):
        download,publish=self.opportunity_pages([
            {'data':{'hitCount':2,'startRecord':0,'oppHits':[{'id':'1'}]}},
            {'data':{'hitCount':2,'startRecord':1,'oppHits':[{'id':'1'}]}},
            {'data':{'id':'1'}},{'data':{'id':'1'}}])
        opportunities.harvest_grants_gov(page_size=1)
        receipt=publish.call_args.kwargs
        self.assertEqual(receipt['status'],'partial')
        result=receipt['coverage']['searches'][0]
        self.assertEqual(result['records_received'],2)
        self.assertEqual(result['unique_records_received'],1)
        self.assertFalse(result['complete'])

    def test_grants_changed_total_cannot_be_reported_as_complete(self):
        _,publish=self.opportunity_pages([
            {'data':{'hitCount':2,'startRecord':0,'oppHits':[{'id':'1'}]}},
            {'data':{'hitCount':3,'startRecord':1,'oppHits':[{'id':'2'}]}},
            {'data':{'id':'1'}},{'data':{'id':'1'}},{'data':{'id':'2'}}])
        opportunities.harvest_grants_gov(page_size=1)
        result=publish.call_args.kwargs['coverage']['searches'][0]
        self.assertEqual(result['reported_counts'],[2,3])
        self.assertFalse(result['complete'])

    def evidence_pages(self,pages):
        download,publish=self.opportunity_pages(pages)
        self.stack.enter_context(patch.object(opportunities,'grin_disease_mondo_ids',return_value={'MONDO_1':[{'gene':'GRIN2A'}]}))
        self.stack.enter_context(patch.object(opportunities,'_evidence_selection',return_value='id'))
        return download,publish

    @staticmethod
    def evidence(cursor,ident='same',count=2):
        return {'data':{'target':{'evidences':{'count':count,'cursor':cursor,'rows':[{'id':ident}]}}}}

    def test_evidence_repeated_cursor_stops_without_publishing_completeness(self):
        download,publish=self.evidence_pages([self.evidence('next'),self.evidence('next')])
        with self.assertRaisesRegex(RuntimeError,'cursor repeated'):
            opportunities.harvest_grin_evidence(page_size=1)
        self.assertEqual(download.call_count,2)
        publish.assert_not_called()

    def test_evidence_duplicate_rows_do_not_satisfy_reported_total(self):
        _,publish=self.evidence_pages([self.evidence('next'),self.evidence(None),
            {'data':{'target':{'evidences':{'count':0,'cursor':None,'rows':[]}}}}])
        coverage=opportunities.harvest_grin_evidence(page_size=1)
        self.assertEqual(coverage['GRIN2A']['records_acquired'],2)
        self.assertEqual(coverage['GRIN2A']['unique_records_acquired'],1)
        self.assertFalse(coverage['GRIN2A']['complete'])
        self.assertFalse(publish.call_args.kwargs['evidence_dataset']['complete_for_selected_diseases'])

    def literature_pages(self,pages,*,recheck=False):
        pending=iter(pages)
        def download(source,url,filename,**kwargs):
            try:page=deepcopy(next(pending))
            except StopIteration:raise AssertionError('Pagination requested another page after a cycle')
            path=core.RAW/source/filename;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(page))
            return path
        module=literature_recheck if recheck else literature
        return self.stack.enter_context(patch.object(module,'download',side_effect=download))

    @staticmethod
    def article(cursor,ident='1',count=10):
        return {'hitCount':count,'nextCursorMark':cursor,'resultList':{'result':[{'source':'MED','id':ident}]}}

    def test_independent_literature_recheck_detects_two_cursor_cycle(self):
        original=core.RAW/'europe_pmc_diseases/query-00000.json';original.parent.mkdir(parents=True)
        original.write_text(json.dumps({'request':{'queryString':'rare disease'},'resultList':{'result':[]}}))
        download=self.literature_pages([self.article('A'),self.article('B'),self.article('A')],recheck=True)
        with self.assertRaisesRegex(ValueError,'cursor cycle'):
            literature_recheck.run('query')
        self.assertEqual(download.call_count,3)
        self.assertFalse((core.PROCESSED/'europe_pmc_recheck').exists())

    def prepare_main_literature(self):
        vocabulary=core.PROCESSED/'raresource/diseases.jsonl.gz'
        core.emit_records('raresource','diseases',[{'Rare Disease Name':'Rare disease fixture','Disease Annotations':'D1'}])
        self.assertTrue(vocabulary.exists())

    def test_main_literature_cycle_remains_an_explicit_query_gap(self):
        self.prepare_main_literature()
        download=self.literature_pages([self.article('A'),self.article('B'),self.article('A')])
        literature.run(workers=1)
        result=core.manifest(literature.SOURCE)
        self.assertEqual(download.call_count,3)
        self.assertEqual(result['status'],'complete_with_query_gaps')
        self.assertEqual(len(result['query_errors']),1)
        self.assertFalse(result['queries'])

    def test_literature_changing_provider_count_cannot_claim_verification(self):
        self.prepare_main_literature()
        self.literature_pages([self.article('A','1',2),self.article(None,'2',3)])
        literature.run(workers=1)
        result=core.manifest(literature.SOURCE)
        self.assertEqual(result['status'],'complete_with_query_gaps')
        query=next(iter(result['queries'].values()))
        self.assertEqual(query['reported_counts'],[2,3])
        self.assertEqual(query['status'],'count_discrepancy')
        self.assertEqual(len(result['count_discrepancies']),1)


if __name__=='__main__':unittest.main()

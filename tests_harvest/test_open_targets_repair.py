"""Exercise the real recursive repair, including cached rerun behavior."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harvest import core, opportunities


class OpenTargetsRepairIntegrationTests(unittest.TestCase):
    def test_large_partition_is_fully_traversed_and_rerun_stays_unique(self):
        targets=['ENSG00000100001','ENSG00000100002','ENSG00000100003',
                 'ENSG00000110001','ENSG00000110002']
        requested=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.multiple(core,ROOT=root,RAW=root/'raw',PROCESSED=root/'processed',MANIFESTS=root/'manifests'):
                core.emit_records('open_targets','rare_diseases',[{'id':'MONDO_1','name':'Example','associatedTargets':{'count':5}}])
                core.emit_records('open_targets','target_associations',[
                    {'disease_id':'MONDO_1','target_association':{'target':{'id':key}}}
                    for key in targets[:2]+targets[:2]+targets[:1]])
                def download(source,url,filename,**kwargs):
                    query=kwargs['json_body']['query'];data={}
                    entries=re.findall(r'd(\d+): disease\(efoId:"([^"]+)"\).*?BFilter:"([^"]+)"',query)
                    self.assertTrue(entries,'Expected a prefix query for the oversized disease')
                    for alias,ident,prefix in entries:
                        requested.append(prefix)
                        matches=[key for key in targets if key.startswith(prefix)]
                        data['d'+alias]={'id':ident,'associatedTargets':{'count':len(matches),'rows':[
                            {'target':{'id':key},'score':0.1} for key in matches[:3]]}}
                    path=core.RAW/source/filename;path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_text(json.dumps({'data':data}));return path
                with patch.object(core,'download',side_effect=download):
                    result=opportunities.harvest_open_targets_uniqueness_repair(batch_size=2,page_size=3,delay=0)
                self.assertEqual((result['rows'],result['distinct_pairs'],result['duplicates'],result['mismatches']),(5,5,0,0))
                self.assertEqual(result['failures'],[])
                self.assertTrue(set('ENSG000001'+str(i) for i in range(10)).issubset(requested))
                self.assertTrue(core.manifest('open_targets')['association_dataset']['complete_for_returned_diseases'])
                with patch.object(core,'download',side_effect=AssertionError('Rerun should not download')):
                    rerun=opportunities.harvest_open_targets_uniqueness_repair(page_size=3,delay=0)
                self.assertEqual((rerun['rows'],rerun['distinct_pairs'],rerun['calls']),(5,5,0))

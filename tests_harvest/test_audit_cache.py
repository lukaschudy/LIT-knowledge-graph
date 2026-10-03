import gzip, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from harvest import audit
from harvest.core import digest

class AuditCacheTests(unittest.TestCase):
    def test_reused_structure_still_rehashes_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifests=root/'manifests';manifests.mkdir();(root/'data').mkdir()
            data=root/'rows.jsonl.gz'
            with gzip.open(data,'wt') as handle:
                handle.write(json.dumps({'_source':'example','_dataset':'rows','_record':1,'value':'A'})+'\n')
            m={'source':'example','status':'complete','artifacts':{},'datasets':{'rows':{'path':'rows.jsonl.gz','records':1,'bytes':data.stat().st_size,'sha256':digest(data)}}}
            (manifests/'example.json').write_text(json.dumps(m))
            with patch.object(audit,'ROOT',root),patch.object(audit,'MANIFESTS',manifests):
                first=audit.run();self.assertEqual(first['totals']['errors'],0)
                reused=audit.run(reuse_verified=True)
                self.assertEqual(reused['sources'][0]['datasets'][0]['verified_records'],1)
                self.assertIn('structural_validation_reused_from',reused['sources'][0])
                content=bytearray(data.read_bytes());content[-1]^=1;data.write_bytes(content)
                corrupt=audit.run(reuse_verified=True)
                self.assertGreater(corrupt['totals']['errors'],0)
                self.assertNotIn('structural_validation_reused_from',corrupt['sources'][0])

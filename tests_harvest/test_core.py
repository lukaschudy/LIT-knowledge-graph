import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harvest import core


class CoreTests(unittest.TestCase):
    def test_record_stream_preserves_negative_context_and_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(core,'ROOT',root), patch.object(core,'PROCESSED',root/'out'), patch.object(core,'MANIFESTS',root/'manifests'):
                p=core.emit_records('hpo','annotations',iter([{'subject':'OMIM:1','qualifier':'NOT','hpo_id':'HP:0000001'}]),description='fixture')
                with gzip.open(p,'rt') as f:row=json.loads(f.readline())
                self.assertEqual(row['qualifier'],'NOT')
                self.assertEqual(row['_source'],'hpo')
                m=core.manifest('hpo')['datasets']['annotations']
                self.assertEqual(m['records'],1)
                self.assertEqual(m['sha256'],core.digest(p))

    def test_failed_stream_does_not_replace_existing_dataset(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(core,'ROOT',root), patch.object(core,'PROCESSED',root/'out'), patch.object(core,'MANIFESTS',root/'manifests'):
                p=core.emit_records('test','rows',[{'id':'keep'}])
                before=p.read_bytes()
                def bad():
                    yield {'id':'partial'}
                    raise ValueError('malformed row')
                with self.assertRaises(ValueError):core.emit_records('test','rows',bad())
                self.assertEqual(p.read_bytes(),before)
                self.assertEqual(core.manifest('test')['datasets']['rows']['records'],1)

    def test_secret_query_parameters_are_redacted(self):
        url=core.safe_url('https://example.org/data?api_key=secret&query=disease')
        self.assertNotIn('secret',url)
        self.assertIn('query=disease',url)


if __name__=='__main__':unittest.main()

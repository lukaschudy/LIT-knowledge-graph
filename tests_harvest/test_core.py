import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from harvest import core


class CoreTests(unittest.TestCase):
    def test_cache_requires_matching_request_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            response=MagicMock();response.status_code=200
            response.headers={'Content-Length':'3'};response.url='https://example.org/data?query=new'
            response.iter_content.return_value=iter([b'new'])
            context=MagicMock();context.__enter__.return_value=response
            with patch.object(core,'ROOT',root), patch.object(core,'RAW',root/'raw'), patch.object(core,'MANIFESTS',root/'manifests'), patch.object(core,'DISK_FLOOR',0), patch.object(core.SESSION,'request',return_value=context) as request:
                p=root/'raw/test/data.json';p.parent.mkdir(parents=True);p.write_bytes(b'old')
                core.update_manifest('test',artifacts={'data.json':{'url':'https://example.org/data?query=old','method':'GET','request_body':None,'sha256':core.digest(p)}})
                core.download('test','https://example.org/data?query=old','data.json',license_name='fixture')
                request.assert_not_called()
                core.download('test','https://example.org/data?query=new','data.json',license_name='fixture')
                request.assert_called_once();self.assertEqual(p.read_bytes(),b'new')

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

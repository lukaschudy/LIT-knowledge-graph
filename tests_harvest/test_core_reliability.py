"""Offline acquisition failures must not produce successful partial receipts."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import requests
from requests.structures import CaseInsensitiveDict
from harvest import core


class Response:
    def __init__(self, body=b'', *, status=200, headers=None, chunks=None):
        self.status_code=status
        self.headers=CaseInsensitiveDict(headers or {})
        self.url='https://example.org/data'
        self.chunks=chunks if chunks is not None else [body]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):
        if self.status_code>=400:raise requests.HTTPError('provider error',response=self)
    def iter_content(self, size):
        for value in self.chunks:
            if isinstance(value,BaseException):raise value
            yield value


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for name,value in {'ROOT':self.root,'RAW':self.root/'raw','PROCESSED':self.root/'processed',
                           'MANIFESTS':self.root/'manifests','DISK_FLOOR':0}.items():
            change=patch.object(core,name,value);change.start();self.addCleanup(change.stop)
        sleep=patch.object(core.time,'sleep');sleep.start();self.addCleanup(sleep.stop)
        quiet=patch('builtins.print');quiet.start();self.addCleanup(quiet.stop)
        self.dest=core.RAW/'fixture'/'data.bin'
    def download(self, **kwargs):
        return core.download('fixture',kwargs.pop('url','https://example.org/data'),'data.bin',license_name='fixture',**kwargs)

    def test_partial_range_segments_are_not_published_until_total_is_reached(self):
        responses=[Response(headers={'ETag':'"a"','Content-Length':'9'},chunks=[b'abc',requests.ConnectionError('interrupted')]),
                   Response(b'def',status=206,headers={'ETag':'"a"','Content-Range':'bytes 3-5/9','Content-Length':'3'}),
                   Response(b'ghi',status=206,headers={'ETag':'"a"','Content-Range':'bytes 6-8/9','Content-Length':'3'})]
        with patch.object(core.SESSION,'request',side_effect=responses) as request:
            self.assertEqual(self.download().read_bytes(),b'abcdefghi')
        self.assertEqual([call.kwargs['headers'].get('Range') for call in request.call_args_list],[None,'bytes=3-','bytes=6-'])
        receipt=core.manifest('fixture')['artifacts']['data.bin']
        self.assertEqual(receipt['bytes'],9)
        self.assertEqual(receipt['sha256'],hashlib.sha256(b'abcdefghi').hexdigest())

    def test_incomplete_range_exhaustion_leaves_only_resumable_work(self):
        responses=[Response(bytes([97+i]),status=206,headers={'ETag':'"a"','Content-Range':f'bytes {i}-{i}/8','Content-Length':'1'}) for i in range(4)]
        with patch.object(core.SESSION,'request',side_effect=responses),self.assertRaises(RuntimeError):
            self.download()
        self.assertFalse(self.dest.exists())
        self.assertEqual(self.dest.with_suffix('.bin.part').read_bytes(),b'abcd')
        self.assertNotIn('data.bin',core.manifest('fixture')['artifacts'])
        self.assertEqual(core.manifest('fixture')['status'],'in_progress')

    def test_unsolicited_nonzero_range_is_never_a_complete_acquisition(self):
        response=Response(b'def',status=206,headers={'ETag':'"a"','Content-Range':'bytes 3-5/6','Content-Length':'3'})
        with patch.object(core.SESSION,'request',return_value=response),self.assertRaises(RuntimeError):
            self.download()
        self.assertFalse(self.dest.exists())
        self.assertFalse(core.manifest('fixture')['artifacts'])

    def test_decoded_compressed_response_restarts_without_range(self):
        responses=[Response(headers={'ETag':'"a"','Content-Encoding':'gzip','Content-Length':'14'},
                            chunks=[b'decoded-prefix-is-longer',requests.ConnectionError('cut')]),
                   Response(b'whole',headers={'ETag':'"a"','Content-Length':'5'})]
        with patch.object(core.SESSION,'request',side_effect=responses) as request:
            self.assertEqual(self.download().read_bytes(),b'whole')
        self.assertNotIn('Range',request.call_args_list[1].kwargs['headers'])

    def test_changed_resume_validator_discards_the_old_representation(self):
        responses=[Response(headers={'ETag':'"old"','Content-Length':'6'},chunks=[b'old',requests.ConnectionError('cut')]),
                   Response(b'new',status=206,headers={'ETag':'"new"','Content-Range':'bytes 3-5/6','Content-Length':'3'}),
                   Response(b'newnew',headers={'ETag':'"new"','Content-Length':'6'})]
        with patch.object(core.SESSION,'request',side_effect=responses) as request:
            self.assertEqual(self.download().read_bytes(),b'newnew')
        self.assertNotIn('Range',request.call_args_list[2].kwargs['headers'])

    def test_redacted_url_collision_does_not_reuse_another_authenticated_request(self):
        with patch.object(core.SESSION,'request',side_effect=[Response(b'one'),Response(b'two')]) as request:
            self.download(url='https://example.org/data?token=first-secret')
            self.download(url='https://example.org/data?token=second-secret')
        self.assertEqual(request.call_count,2)
        self.assertEqual(self.dest.read_bytes(),b'two')
        text=(core.MANIFESTS/'fixture.json').read_text()
        self.assertNotIn('first-secret',text);self.assertNotIn('second-secret',text)

    def test_request_exception_cannot_echo_url_credentials_or_body(self):
        error=requests.RequestException('Failed https://user:password@example.org/data?token=super-secret body=private-value')
        with patch.object(core.SESSION,'request',side_effect=error),self.assertRaises(RuntimeError) as raised:
            self.download(url='https://user:password@example.org/data?token=super-secret')
        message=str(raised.exception)
        for secret in ('password','super-secret','private-value','user:'):
            self.assertNotIn(secret,message)
        self.assertIn('RequestException',message)

    def test_failed_refresh_preserves_old_artifact_and_marks_source_in_progress(self):
        with patch.object(core.SESSION,'request',return_value=Response(b'old')):
            self.download()
        old_receipt=core.manifest('fixture')['artifacts']['data.bin']
        core.update_manifest('fixture',status='complete')
        with patch.object(core.SESSION,'request',side_effect=requests.ConnectionError('cut')),self.assertRaises(RuntimeError):
            self.download(refresh=True)
        self.assertEqual(self.dest.read_bytes(),b'old')
        manifest=core.manifest('fixture')
        self.assertEqual(manifest['artifacts']['data.bin'],old_receipt)
        self.assertEqual(manifest['status'],'in_progress')

    def test_refresh_crash_cannot_pair_new_validator_with_old_partial_bytes(self):
        original=core.atomic_json
        calls=[]
        def stop_before_new_receipt(path,obj):
            if str(path).endswith('.part.json'):
                calls.append(obj)
                if len(calls)==2:raise KeyboardInterrupt('process interruption')
            return original(path,obj)
        responses=[Response(headers={'ETag':'"old"','Content-Length':'6'},chunks=[b'old',requests.ConnectionError('cut')]),
                   Response(b'newnew',headers={'ETag':'"new"','Content-Length':'6'})]
        with patch.object(core.SESSION,'request',side_effect=responses),patch.object(core,'atomic_json',side_effect=stop_before_new_receipt):
            with self.assertRaises(KeyboardInterrupt):self.download()
        self.assertEqual(self.dest.with_suffix('.bin.part').read_bytes(),b'')
        self.assertFalse(self.dest.exists())

    def test_generator_failure_keeps_previous_dataset_and_receipt(self):
        dest=core.emit_records('fixture','records',[{'old':True}])
        before=dest.read_bytes();receipt=core.manifest('fixture')['datasets']['records']
        core.update_manifest('fixture',status='complete')
        def failed():
            yield {'new':True}
            raise RuntimeError('parser interrupted')
        with self.assertRaisesRegex(RuntimeError,'parser interrupted'):
            core.emit_records('fixture','records',failed())
        self.assertEqual(dest.read_bytes(),before)
        manifest=core.manifest('fixture')
        self.assertEqual(manifest['datasets']['records'],receipt)
        self.assertEqual(manifest['status'],'in_progress')
        self.assertFalse(list(dest.parent.glob('*.tmp')))

    def test_atomic_json_concurrent_publish_never_loses_the_destination(self):
        path=self.root/'receipt.json'
        gate=threading.Barrier(2)
        original=Path.replace
        def synchronized_replace(source,target):
            if target==path:gate.wait(timeout=3)
            return original(source,target)
        with patch.object(Path,'replace',synchronized_replace),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(core.atomic_json,path,{'value':value}) for value in (1,2)]
            for future in futures:future.result(timeout=3)
        self.assertIn(json.loads(path.read_text())['value'],(1,2))
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_failed_export_copy_preserves_previous_acquisition(self):
        incoming=self.root/'export.csv';incoming.write_bytes(b'original-export')
        dest=core.import_export('fixture',incoming,'export.csv',url='https://example.org',license_name='fixture')
        receipt=core.manifest('fixture')['artifacts']['export.csv']
        def partial(source,target):
            target.write(b'broken');raise OSError('copy interrupted')
        with patch.object(core.shutil,'copyfileobj',side_effect=partial),self.assertRaises(OSError):
            core.import_export('fixture',incoming,'export.csv',url='https://example.org',license_name='fixture')
        self.assertEqual(dest.read_bytes(),b'original-export')
        self.assertEqual(core.manifest('fixture')['artifacts']['export.csv'],receipt)
        self.assertFalse(list(dest.parent.glob('*.tmp')))

    def test_overlong_range_body_is_discarded_before_retry(self):
        responses=[Response(headers={'ETag':'"a"','Content-Length':'6'},chunks=[b'abc',requests.ConnectionError('cut')]),
                   Response(b'defEXTRA',status=206,headers={'ETag':'"a"','Content-Range':'bytes 3-5/6'}),
                   Response(b'abcdef',headers={'ETag':'"a"','Content-Length':'6'})]
        with patch.object(core.SESSION,'request',side_effect=responses) as request:
            self.assertEqual(self.download().read_bytes(),b'abcdef')
        self.assertNotIn('Range',request.call_args_list[2].kwargs['headers'])

    def test_invalid_partial_receipt_restarts_instead_of_permanently_failing(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.with_suffix('.bin.part').write_bytes(b'unverified partial')
        self.dest.with_suffix('.bin.part.json').write_text('{unfinished')
        with patch.object(core.SESSION,'request',return_value=Response(b'whole')) as request:
            self.assertEqual(self.download().read_bytes(),b'whole')
        self.assertNotIn('Range',request.call_args.kwargs['headers'])

    def test_paths_and_manifest_source_identity_are_checked_before_writes(self):
        with patch.object(core.SESSION,'request') as request:
            for source,name in [('../outside','data'),('fixture','../../outside'),('fixture','/outside')]:
                with self.subTest(source=source,name=name),self.assertRaises(ValueError):
                    core.download(source,'https://example.org',name,license_name='fixture')
            request.assert_not_called()
        core.update_manifest('fixture',status='complete')
        path=core.MANIFESTS/'fixture.json'
        obj=json.loads(path.read_text());obj['source']='another';path.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,'source identity'):
            core.manifest('fixture')


if __name__=='__main__':unittest.main()

"""Deployment packaging must be reproducible and fail without damaging a good build."""
import gzip
import hashlib
import fcntl
import threading
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

builder=module('build_cloudflare')
verifier=module('verify_cloudflare_build')
uploader=module('upload_cloudflare')

class CloudBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for source in ['atlas','data/curated','data/benchmarks/grin-v1','deploy/cloudflare','scripts']:
            shutil.copytree(ROOT/source,self.root/source,ignore=shutil.ignore_patterns('build','.venv','.venv-workers','python_modules','.wrangler','node_modules','__pycache__'),dirs_exist_ok=True)
        self.target=self.root/'deploy/cloudflare/build'

    def build(self):
        with patch('builtins.print'):return builder.build(self.root)

    def test_clean_checkout_build_is_reproducible_without_private_sources(self):
        self.assertFalse((self.root/'data/processed').exists())
        self.build();first=(self.target/'build-manifest.json').read_bytes()
        self.assertGreater(verifier.verify(self.root)['files'],30)
        self.build();self.assertEqual(first,(self.target/'build-manifest.json').read_bytes())

    def test_stale_non_allowlisted_assets_and_modules_are_removed(self):
        self.build()
        (self.target/'public'/'old-private.json').write_text('stale content')
        (self.target/'old_module.py').write_text('pass')
        with self.assertRaisesRegex(ValueError,'inventory'):verifier.verify(self.root)
        self.build()
        self.assertFalse((self.target/'public'/'old-private.json').exists())
        self.assertFalse((self.target/'old_module.py').exists())
        verifier.verify(self.root)

    def test_invalid_input_preserves_previous_build_byte_for_byte(self):
        self.build();first={str(p.relative_to(self.target)):p.read_bytes() for p in self.target.rglob('*') if p.is_file()}
        path=self.root/'data/curated/grin_public_excerpts_v2.json';path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'receipt'):self.build()
        self.assertEqual(first,{str(p.relative_to(self.target)):p.read_bytes() for p in self.target.rglob('*') if p.is_file()})
        self.assertFalse(list(self.target.parent.glob('.atlas-build-*')))

    def test_changed_dense_snapshot_cannot_be_published(self):
        p=self.root/'data/curated/hgnc_dense_snapshot.json.gz'
        data=json.loads(gzip.decompress(p.read_bytes()));data['nodes'][0]['label']='tampered'
        p.write_bytes(gzip.compress(json.dumps(data).encode()))
        with self.assertRaisesRegex(ValueError,'receipt'):self.build()
        self.assertFalse(self.target.exists())

    def test_verifier_detects_changed_source_and_changed_generated_asset(self):
        self.build();p=self.root/'atlas/web/graph.js';p.write_text(p.read_text()+'\n// change\n')
        with self.assertRaisesRegex(ValueError,'inputs changed'):verifier.verify(self.root)
        self.build();(self.target/'public/graph.js').write_text('changed output')
        with self.assertRaisesRegex(ValueError,'files changed'):verifier.verify(self.root)

    def test_publish_rename_failure_restores_previous_build(self):
        self.build();old=(self.target/'build-manifest.json').read_bytes();original=Path.rename
        def fail_staging(path,to):
            if path.parent.name.startswith('.atlas-build-') and path.name=='build':raise OSError('disk rename failed')
            return original(path,to)
        with patch.object(Path,'rename',fail_staging),self.assertRaisesRegex(OSError,'disk rename'):self.build()
        self.assertEqual(old,(self.target/'build-manifest.json').read_bytes())
        verifier.verify(self.root)

    def test_python_toolchain_inputs_cannot_change_after_verification(self):
        self.build()
        for filename in ('pyproject.toml', 'pylock.toml', 'uv.lock'):
            with self.subTest(filename=filename):
                path = self.root / 'deploy/cloudflare' / filename
                original = path.read_bytes()
                try:
                    path.write_bytes(original + b'\n# changed after packaging\n')
                    with self.assertRaisesRegex(ValueError, 'inputs changed'):
                        verifier.verify(self.root)
                finally:
                    path.write_bytes(original)
        verifier.verify(self.root)

    def test_concurrent_source_edit_does_not_replace_valid_build(self):
        self.build();old=(self.target/'build-manifest.json').read_bytes()
        original=builder._build_into
        def edit_after_copy(*args, **kwargs):
            original(*args, **kwargs)
            source=self.root/'atlas/web/graph.js'
            source.write_text(source.read_text()+'\n// concurrent edit\n')
        with patch.object(builder,'_build_into',edit_after_copy),self.assertRaisesRegex(ValueError,'during packaging'):
            self.build()
        self.assertEqual(old,(self.target/'build-manifest.json').read_bytes())
        self.assertFalse(list(self.target.parent.glob('.atlas-build-*')))

    def test_manifest_cannot_authorize_private_output_or_omit_dependency(self):
        self.build()
        manifest_path=self.target/'build-manifest.json'
        manifest=json.loads(manifest_path.read_text())
        private=self.target/'private-dump.json';private.write_text('private')
        manifest['files']['private-dump.json']=hashlib.sha256(private.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'allowlist'):verifier.verify(self.root)
        self.build()
        manifest=json.loads(manifest_path.read_text())
        del manifest['inputs']['atlas/cloud_bundle.py']
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'input inventory'):verifier.verify(self.root)

    def test_optional_frozen_source_presence_is_part_of_input_inventory(self):
        self.build()
        source=self.root/builder.OPTIONAL_SOURCES;source.parent.mkdir(parents=True)
        source.write_text('{}')
        with self.assertRaisesRegex(ValueError,'input inventory'):verifier.verify(self.root)
        self.assertIn(str(builder.OPTIONAL_SOURCES),builder.input_hashes(self.root))

    def test_alternate_root_cannot_seal_generator_code_it_did_not_execute(self):
        (self.root/'atlas/cloud_bundle.py').write_text('raise RuntimeError("different revision")')
        with self.assertRaisesRegex(ValueError,'different generator code'):self.build()
        self.assertFalse(self.target.exists())

    def test_builds_serialize_and_leave_one_valid_output(self):
        original=builder._build_into
        entered=threading.Event();release=threading.Event();second=threading.Event()
        calls=[]
        def hold_first(*args,**kwargs):
            calls.append(1)
            if len(calls)==1:
                entered.set()
                if not release.wait(3):raise RuntimeError('Test release timeout')
            else:second.set()
            return original(*args,**kwargs)
        with patch.object(builder,'_build_into',hold_first),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self.build)
            self.assertTrue(entered.wait(3))
            other=pool.submit(self.build)
            try:self.assertFalse(second.wait(.05))
            finally:release.set()
            first.result(timeout=3);other.result(timeout=3)
        self.assertTrue(second.is_set())
        verifier.verify(self.root)

    def test_upload_verifies_and_holds_lock_without_shell_interpolation(self):
        self.build()
        message='Literal release text; $() and `backticks`'
        commands=[]
        def upload_command(command,**kwargs):
            commands.append(command)
            self.assertEqual(kwargs['cwd'],self.root/'deploy/cloudflare')
            with (self.root/'deploy/cloudflare/.atlas-release.lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        with patch.object(uploader,'verify_packager',return_value='1.17.6'), \
             patch.object(uploader,'verify_vendor',return_value={'files':29,'sha256':'fixture'}) as vendor, \
             patch.object(uploader,'verify_sync_state') as synced, \
             patch.object(uploader.subprocess,'run',side_effect=upload_command):
            uploader.upload(message,root=self.root)
            vendor.assert_called_once_with(self.root,wheel_path=None)
            synced.assert_called_once_with(self.root,packager_version='1.17.6')
        self.assertEqual(commands,[['pywrangler','sync'],['pywrangler','versions','upload','--message',message]])
        (self.target/'worker.py').write_text('changed')
        with patch.object(uploader.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'files changed'):
            uploader.upload(message,root=self.root)
        run.assert_not_called()

    def test_upload_refuses_unverified_vendor_and_sync_changed_inputs(self):
        self.build()
        with patch.object(uploader,'verify_packager',return_value='1.17.6'), \
             patch.object(uploader,'verify_vendor',side_effect=ValueError('Vendor inventory mismatch')), \
             patch.object(uploader.subprocess,'run') as run, self.assertRaisesRegex(ValueError,'Vendor inventory'):
            uploader.upload('test',root=self.root)
        self.assertEqual([c.args[0] for c in run.call_args_list],[['pywrangler','sync']])
        def mutate_lock(*args,**kwargs):
            p=self.root/'deploy/cloudflare/pylock.toml';p.write_text(p.read_text()+'\n# changed by sync\n')
        with patch.object(uploader,'verify_packager',return_value='1.17.6'), \
             patch.object(uploader,'verify_vendor') as vendor, \
             patch.object(uploader.subprocess,'run',side_effect=mutate_lock) as run, \
             self.assertRaisesRegex(ValueError,'inputs changed'):
            uploader.upload('test',root=self.root)
        self.assertEqual([c.args[0] for c in run.call_args_list],[['pywrangler','sync']])
        vendor.assert_not_called()

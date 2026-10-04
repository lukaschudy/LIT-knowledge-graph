"""No uploads/network: authenticate miniature wheel fixtures with real SHA pins."""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import verify_cloudflare_vendor as guard


class CloudVendorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.deploy = self.root / 'deploy/cloudflare'
        self.vendor = self.deploy / 'python_modules'
        self.vendor.mkdir(parents=True)
        self.wheel = self.root / 'sdk.whl'
        self.info = guard.DIST_INFO
        self.files = {
            'workers/__init__.py': b'from .fetch import fetch\n',
            'workers/fetch.py': b'def fetch(url): pass\n',
            f'{self.info}/METADATA': b'Name: workers-runtime-sdk\nVersion: 1.9.2\n',
            f'{self.info}/WHEEL': b'Wheel-Version: 1.0\nTag: py3-none-any\n',
            f'{self.info}/RECORD': b'wheel-provided-record\n',
        }
        self.make_wheel(self.files)
        self.install_files(self.files)
        (self.deploy / 'uv.lock').write_text('[[package]]\nname="workers-py"\nversion="1.17.6"\n')
        (self.deploy / 'pyproject.toml').write_text('[project]\nname="test"\n')
        host = self.deploy / '.venv-workers'
        host.mkdir()
        (host / '.synced').write_text('1.17.6')
        self.fresh_tokens()

    def make_wheel(self, files):
        with zipfile.ZipFile(self.wheel, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        data = self.wheel.read_bytes()
        url = 'https://files.pythonhosted.org/packages/test/workers_runtime_sdk-1.9.2-py3-none-any.whl'
        (self.deploy / 'pylock.toml').write_text(
            f'lock-version="1.0"\n[[packages]]\nname="workers-runtime-sdk"\nversion="1.9.2"\n'
            f'wheels=[{{url={json.dumps(url)},size={len(data)},hashes={{sha256="{hashlib.sha256(data).hexdigest()}"}}}}]\n')

    def install_files(self, files):
        installed = dict(files)
        installed[f'{self.info}/INSTALLER'] = b'uv'
        installed[f'{self.info}/REQUESTED'] = b''
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')
        for name, data in sorted(installed.items()):
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
            writer.writerow([name, '', ''] if name.endswith('/RECORD') else [name, f'sha256={digest}', len(data)])
        installed[f'{self.info}/RECORD'] = output.getvalue().encode()
        installed['.synced'] = b'1.17.6'
        installed['pyvenv.cfg'] = b''
        for name, data in installed.items():
            path = self.vendor / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def fresh_tokens(self):
        timestamp = max((self.deploy / name).stat().st_mtime_ns for name in ('pyproject.toml', 'pylock.toml')) + 1_000_000
        for name in ('python_modules/.synced', '.venv-workers/.synced'):
            os.utime(self.deploy / name, ns=(timestamp, timestamp))

    def verify(self):
        return guard.verify_vendor(self.root, wheel_path=self.wheel)

    def test_exact_vendor_inventory_and_sync_contract_pass_offline(self):
        with patch.object(guard, 'urlopen', side_effect=AssertionError('network')):
            receipt = self.verify()
        self.assertEqual(receipt['files'], 9)
        self.assertEqual(receipt['wheel_sha256'], hashlib.sha256(self.wheel.read_bytes()).hexdigest())
        guard.verify_sync_state(self.root)

    def test_extra_private_files_and_empty_directories_fail(self):
        for name in ('private-corpus.json', '.env', 'workers/local-data.csv', 'workers/cache.pyc'):
            with self.subTest(name=name):
                extra = self.vendor / name
                extra.write_text('private')
                with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                    self.verify()
                extra.unlink()
        (self.vendor / 'private').mkdir()
        with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
            self.verify()

    def test_modified_library_even_with_rewritten_record_fails(self):
        changed = dict(self.files)
        changed['workers/fetch.py'] = b'def fetch(url): evil\n'
        self.install_files(changed)
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            self.verify()

    def test_record_tampering_alone_fails(self):
        record = self.vendor / self.info / 'RECORD'
        record.write_bytes(record.read_bytes() + b'private.json,,\n')
        with self.assertRaises(ValueError):
            self.verify()

    def test_every_generated_file_has_exact_content(self):
        for name in ('pyvenv.cfg', '.synced', f'{self.info}/INSTALLER', f'{self.info}/REQUESTED'):
            with self.subTest(name=name):
                path = self.vendor / name
                original = path.read_bytes()
                path.write_bytes(original + b'private')
                with self.assertRaises(ValueError):
                    self.verify()
                path.write_bytes(original)

    def test_missing_file_fails(self):
        (self.vendor / 'workers/fetch.py').unlink()
        with self.assertRaisesRegex(ValueError, 'missing='):
            self.verify()

    def test_wheel_pin_does_not_trust_changed_archive_or_record(self):
        self.wheel.write_bytes(self.wheel.read_bytes().replace(b'workers', b'evilxxx', 1))
        with self.assertRaisesRegex(ValueError, 'SHA256 pin'):
            self.verify()

    def test_symlinked_file_directory_and_root_fail(self):
        target = self.vendor / 'workers/fetch.py'
        target.unlink()
        target.symlink_to(self.wheel)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.verify()
        target.unlink()
        self.install_files(self.files)
        directory = self.vendor / 'workers'
        directory.rename(self.root / 'external-workers')
        directory.symlink_to(self.root / 'external-workers', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.verify()
        self.vendor.rename(self.deploy / 'actual-vendor')
        self.vendor.symlink_to(self.deploy / 'actual-vendor', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.verify()

    def test_special_files_fail_without_blocking(self):
        os.mkfifo(self.vendor / 'private-pipe')
        with self.assertRaisesRegex(ValueError, 'special file'):
            self.verify()

    def test_inventory_and_expansion_are_bounded(self):
        with patch.object(guard, 'MAX_ENTRIES', 5):
            with self.assertRaisesRegex(ValueError, 'entry bound'):
                self.verify()
        with patch.object(guard, 'MAX_EXPANDED_BYTES', 5):
            with self.assertRaisesRegex(ValueError, 'bounded vendor'):
                self.verify()

    def test_path_traversal_wheel_is_rejected_before_extracting(self):
        self.make_wheel(dict(self.files, **{'../private.txt': b'bad'}))
        with self.assertRaisesRegex(ValueError, 'Unsafe SDK wheel'):
            self.verify()
        self.assertFalse((self.root / 'private.txt').exists())

    def test_mutation_during_verification_is_rejected(self):
        original = guard._read
        def changed(path, limit):
            value = original(path, limit)
            if str(path).endswith('workers/fetch.py'):
                (self.vendor / 'private.json').write_text('private')
            return value
        with patch.object(guard, '_read', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during verification'):
                self.verify()

    def test_both_sync_tokens_version_and_freshness_are_required(self):
        for name in ('python_modules/.synced', '.venv-workers/.synced'):
            with self.subTest(name=name):
                token = self.deploy / name
                token.write_text('1.17.5')
                with self.assertRaisesRegex(ValueError, 'resync'):
                    guard.verify_sync_state(self.root)
                token.write_text('1.17.6')
                os.utime(token, ns=(1, 1))
                with self.assertRaisesRegex(ValueError, 'resync'):
                    guard.verify_sync_state(self.root)
                self.fresh_tokens()
        with self.assertRaisesRegex(ValueError, 'executable'):
            guard.verify_sync_state(self.root, packager_version='1.18.0')

    def test_unreviewed_packager_lock_is_rejected(self):
        (self.deploy / 'uv.lock').write_text('[[package]]\nname="workers-py"\nversion="1.18.0"\n')
        with self.assertRaisesRegex(ValueError, 'audited workers-py'):
            self.verify()

    def test_packager_version_uses_non_proxy_cli_flag(self):
        result = subprocess.CompletedProcess([], 0, 'pywrangler, version 1.17.6\n', '')
        with patch.object(guard.subprocess, 'run', return_value=result) as run:
            self.assertEqual(guard.verify_packager('/tool/pywrangler', root=self.root), '1.17.6')
            self.assertEqual(run.call_args.args[0], ['/tool/pywrangler', '--version'])
        result.stdout = 'wrangler 4.0.0\n'
        with patch.object(guard.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(ValueError, 'executable'):
                guard.verify_packager('/tool/pywrangler', root=self.root)


if __name__ == '__main__':
    unittest.main()

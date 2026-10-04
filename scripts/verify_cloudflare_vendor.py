"""Authenticate the exact Python vendor tree against the pinned SDK wheel.

Run after pywrangler sync and before upload, under the caller's release lock.
No vendor files are changed. An optional --wheel avoids network access; its
bytes still have to match pylock.toml. Extracted uv caches and installed RECORD
files are deliberately not trusted as the source of dependency hashes.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tomllib
from urllib.parse import urlsplit
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_WHEEL_BYTES = 1_000_000
MAX_EXPANDED_BYTES = 8_000_000
MAX_ENTRIES = 256
SDK_VERSION = '1.9.2'
PACKAGER_VERSION = '1.17.6'
DIST_INFO = f'workers_runtime_sdk-{SDK_VERSION}.dist-info'


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path, limit):
    """Bounded regular-file read, rejecting symlinks and concurrent replacement."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise ValueError(f'Not a bounded regular file: {path}')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        if _signature(os.fstat(handle.fileno())) != _signature(before):
            raise ValueError(f'File changed during verification: {path}')
        data = handle.read(limit + 1)
        after = os.fstat(handle.fileno())
    if (len(data) > limit or _signature(before) != _signature(after)
            or _signature(before) != _signature(path.lstat())):
        raise ValueError(f'File changed during verification: {path}')
    return data


def _locks(deploy):
    lock = tomllib.loads(_read(deploy / 'pylock.toml', MAX_WHEEL_BYTES).decode('utf-8'))
    packages = lock.get('packages')
    if (lock.get('lock-version') != '1.0' or not isinstance(packages, list)
            or len(packages) != 1 or not isinstance(packages[0], dict)
            or packages[0].get('name') != 'workers-runtime-sdk'
            or packages[0].get('version') != SDK_VERSION):
        raise ValueError('Vendor verification requires the audited workers-runtime-sdk 1.9.2 lock.')
    package = packages[0]
    wheels = package.get('wheels', [])
    if (not isinstance(wheels, list) or len(wheels) != 1 or not isinstance(wheels[0], dict)
            or any(key in package for key in ('sdist', 'directory', 'vcs', 'archive'))):
        raise ValueError('Vendor lock must contain exactly one pinned SDK wheel.')
    wheel = wheels[0]
    hashes = wheel.get('hashes', {})
    digest = hashes.get('sha256', '') if isinstance(hashes, dict) else ''
    size = wheel.get('size')
    if not isinstance(wheel.get('url'), str):
        raise ValueError('SDK wheel URL is invalid.')
    url = urlsplit(wheel.get('url', ''))
    if (type(size) is not int or not 0 < size <= MAX_WHEEL_BYTES
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in '0123456789abcdef' for c in digest)
            or url.scheme != 'https' or url.hostname != 'files.pythonhosted.org'
            or url.username or url.password or url.port not in (None, 443)
            or not url.path.endswith(f'/workers_runtime_sdk-{SDK_VERSION}-py3-none-any.whl')
            or url.query or url.fragment):
        raise ValueError('SDK wheel URL, size, or SHA256 pin is invalid.')
    uv_lock = tomllib.loads(_read(deploy / 'uv.lock', MAX_WHEEL_BYTES).decode('utf-8'))
    uv_packages = uv_lock.get('package', [])
    if not isinstance(uv_packages, list) or any(not isinstance(p, dict) for p in uv_packages):
        raise ValueError('Invalid workers-py package lock.')
    packagers = [p for p in uv_packages if p.get('name') == 'workers-py']
    if len(packagers) != 1 or packagers[0].get('version') != PACKAGER_VERSION:
        raise ValueError('Vendor generation contract requires audited workers-py 1.17.6.')
    return wheel


def _wheel_bytes(wheel, wheel_path):
    if wheel_path is not None:
        data = _read(Path(wheel_path), MAX_WHEEL_BYTES)
    else:
        # The SHA pin authenticates bytes even if the transport/cache is compromised.
        with urlopen(wheel['url'], timeout=20) as response:
            data = response.read(wheel['size'] + 1)
    if len(data) != wheel['size'] or hashlib.sha256(data).hexdigest() != wheel['hashes']['sha256']:
        raise ValueError('SDK wheel does not match the pylock.toml size and SHA256 pin.')
    return data


def _expected_files(data):
    expected = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > MAX_ENTRIES or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
            raise ValueError('SDK wheel exceeds the bounded vendor inventory.')
        for item in members:
            name = item.filename
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
                    or str(path) != name.rstrip('/')
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError(f'Unsafe SDK wheel member: {name!r}')
            if item.is_dir():
                continue
            if name in expected or any(part.endswith('.data') for part in path.parts):
                raise ValueError(f'Unsupported SDK wheel member: {name!r}')
            expected[name] = archive.read(item)
    record = f'{DIST_INFO}/RECORD'
    if record not in expected or f'{DIST_INFO}/METADATA' not in expected:
        raise ValueError('SDK wheel lacks its expected distribution metadata.')
    # uv rewrites RECORD, adding these two deterministic installer files. Do not
    # let the installed RECORD supply hashes: that would bless coordinated edits.
    for name, data in ((f'{DIST_INFO}/INSTALLER', b'uv'), (f'{DIST_INFO}/REQUESTED', b'')):
        if name in expected:
            raise ValueError(f'Unexpected generated file in SDK wheel: {name}')
        expected[name] = data
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    for name, data in sorted(expected.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
        writer.writerow((name, '', '') if name == record else (name, f'sha256={digest}', str(len(data))))
    expected[record] = output.getvalue().encode('utf-8')
    expected['pyvenv.cfg'] = b''
    expected['.synced'] = PACKAGER_VERSION.encode('ascii')
    return expected


def _inventory(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError('python_modules must be a real directory, not a symlink.')
    result = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if len(result) >= MAX_ENTRIES:
                    raise ValueError('Vendor inventory exceeds its entry bound.')
                if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    raise ValueError(f'Vendor contains a symlink or special file: {relative}')
                result[relative] = (stat.S_ISDIR(info.st_mode), _signature(info))
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
    return result


def verify_sync_state(root=ROOT, *, packager_version=PACKAGER_VERSION):
    """Reject conditions that would let the following upload implicitly resync.

    The caller must obtain packager_version from the executable it will invoke.
    This does not replace holding the release lock across sync, verification and
    upload, or prevent unrelated processes from changing files after this check.
    """
    if packager_version != PACKAGER_VERSION:
        raise ValueError('Upload executable differs from the audited workers-py version.')
    deploy = Path(root) / 'deploy/cloudflare'
    latest = max((deploy / name).stat().st_mtime_ns for name in ('pyproject.toml', 'pylock.toml'))
    for name in ('python_modules/.synced', '.venv-workers/.synced'):
        token = deploy / name
        if _read(token, 64) != PACKAGER_VERSION.encode('ascii') or token.stat().st_mtime_ns < latest:
            raise ValueError(f'pywrangler would resync during upload; sync before verification: {name}')


def verify_packager(executable='pywrangler', *, root=ROOT):
    """Check the exact CLI to be used, without triggering dependency sync."""
    result = subprocess.run([str(executable), '--version'],
                            cwd=Path(root) / 'deploy/cloudflare',
                            capture_output=True, text=True, check=True, timeout=20)
    if result.stdout.strip() != f'pywrangler, version {PACKAGER_VERSION}':
        raise ValueError('Upload executable differs from the audited workers-py version.')
    return PACKAGER_VERSION


def verify_vendor(root=ROOT, *, wheel_path=None):
    """Return an authenticated inventory receipt; raise on any extra/changed file."""
    deploy = Path(root) / 'deploy/cloudflare'
    wheel = _locks(deploy)
    expected = _expected_files(_wheel_bytes(wheel, wheel_path))
    vendor = deploy / 'python_modules'
    before = _inventory(vendor)
    directories = {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != '.'}
    actual_files = {name for name, (is_dir, _) in before.items() if not is_dir}
    actual_dirs = {name for name, (is_dir, _) in before.items() if is_dir}
    if actual_files != set(expected) or actual_dirs != directories:
        extras = sorted((actual_files - set(expected)) | (actual_dirs - directories))
        missing = sorted(set(expected) - actual_files)
        raise ValueError(f'Vendor inventory mismatch; extra={extras!r}, missing={missing!r}')
    for name, content in expected.items():
        if _read(vendor / name, len(content)) != content:
            raise ValueError(f'Vendor bytes differ from the pinned wheel/generated contract: {name}')
    if _inventory(vendor) != before:
        raise ValueError('Vendor inventory changed during verification.')
    receipt = hashlib.sha256()
    for name, content in sorted(expected.items()):
        receipt.update(name.encode('utf-8') + b'\0' + hashlib.sha256(content).digest())
    return {'files': len(expected), 'sha256': receipt.hexdigest(), 'wheel_sha256': wheel['hashes']['sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--wheel', type=Path, help='Local pinned wheel for offline verification')
    parser.add_argument('--check-sync-state', action='store_true')
    args = parser.parse_args()
    try:
        result = verify_vendor(args.root, wheel_path=args.wheel)
        if args.check_sync_state:
            verify_sync_state(args.root)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Vendor verification failed: {error}\n')
    print(f"Verified {result['files']} vendor files: {result['sha256']}")

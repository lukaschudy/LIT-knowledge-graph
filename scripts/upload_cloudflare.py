"""Verify and upload one sealed Worker build while holding the release lock.

This uploads a version; it does not promote traffic or change domain routes.
"""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_cloudflare import release_lock
from scripts.verify_cloudflare_build import verify_locked
from scripts.verify_cloudflare_vendor import verify_packager, verify_sync_state, verify_vendor


def upload(message, *, root=ROOT, pywrangler='pywrangler', wheel_path=None):
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Provide a release description.')
    root = Path(root).resolve()
    with release_lock(root):
        verify_locked(root)
        packager_version = verify_packager(pywrangler, root=root)
        subprocess.run([pywrangler, 'sync'], cwd=root / 'deploy/cloudflare', check=True)
        # Sync may regenerate lock files. Never seal its changes implicitly.
        verify_locked(root)
        vendor = verify_vendor(root, wheel_path=wheel_path)
        verify_sync_state(root, packager_version=packager_version)
        print(f"Verified {vendor['files']} vendor files: {vendor['sha256']}", flush=True)
        subprocess.run([pywrangler, 'versions', 'upload', '--message', message],
                       cwd=root / 'deploy/cloudflare', check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message', required=True)
    parser.add_argument('--pywrangler', default='pywrangler', help='Installed pywrangler executable')
    parser.add_argument('--wheel', type=Path, help='Pinned SDK wheel for offline vendor verification')
    args = parser.parse_args()
    upload(args.message, pywrangler=args.pywrangler, wheel_path=args.wheel)

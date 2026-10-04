"""Reject altered, stale, or non-allowlisted release output before Wrangler upload."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_cloudflare import input_hashes, output_paths, release_lock


def verify(root=ROOT):
    with release_lock(root, shared=True):
        return verify_locked(root)


def verify_locked(root=ROOT):
    root=Path(root).resolve();target=root/'deploy/cloudflare/build'
    if target.is_symlink():
        raise ValueError('Build output must not be a symlink.')
    manifest=json.loads((target/'build-manifest.json').read_text())
    if manifest.get('schema_version')!='atlas-build-v1' or manifest.get('asset_source') not in ('HEAD','working-tree'):
        raise ValueError('Unsupported or missing build manifest.')
    if set(manifest.get('files', {})) != output_paths():
        raise ValueError('Build file inventory differs from the independent asset/module allowlist.')
    current_inputs = input_hashes(root, committed_assets=manifest['asset_source'] == 'HEAD')
    if set(manifest.get('inputs', {})) != set(current_inputs):
        raise ValueError('Build input inventory changed. Rebuild before deployment.')
    observed={str(p.relative_to(target)) for p in target.rglob('*') if p.is_file() or p.is_symlink()}
    expected=set(manifest['files'])|{'build-manifest.json'}
    if observed!=expected:
        raise ValueError(f'Build file inventory changed: {sorted(observed ^ expected)}')
    for collection,base in [('files',target),('inputs',root)]:
        for relative,wanted in manifest[collection].items():
            path=Path(relative)
            if path.is_absolute() or '..' in path.parts or (base/path).is_symlink() or not (base/path).resolve().is_relative_to(base.resolve()):
                raise ValueError(f'Unsafe {collection} path: {relative}')
            if collection=='inputs' and manifest['asset_source']=='HEAD' and relative.startswith('atlas/web/'):
                value=subprocess.check_output(['git','show','HEAD:'+relative],cwd=root)
            else:value=(base/path).read_bytes()
            if hashlib.sha256(value).hexdigest()!=wanted:
                raise ValueError(f'{collection} changed after build: {relative}. Rebuild before deployment.')
    return {'files':len(manifest['files']),'inputs':len(manifest['inputs']),'asset_source':manifest['asset_source']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(verify(),sort_keys=True))

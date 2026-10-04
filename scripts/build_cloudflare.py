"""Build an allowlisted Cloudflare deployment of the reviewed GRIN cluster."""
import json
import gzip
from pathlib import Path
import shutil
import sys
import re
import subprocess
import hashlib
import tempfile
import argparse
import fcntl
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atlas.cloud_bundle import reviewed_graph
from atlas.benchmark.contracts import digest
from atlas.model import validate_bundle
from atlas.server import _ASSETS
from atlas.store import GraphStore

PACKAGE_FILES = ['cloud_voice.py', '__init__.py', 'http_api.py', 'reasoning.py', 'questions.py', 'cluster_questions.py', 'demo_scope.py', 'public_graph.py', 'proposals.py']
OPTIONAL_SOURCES = Path('data/processed/benchmarks/grin-development-v1/sources.json')


def _build_into(target, *, root, committed_assets=False):
    target.mkdir(parents=True, exist_ok=True)
    public = target / 'public'
    public.mkdir(exist_ok=True)
    for filename, _ in _ASSETS.values():
        source = root / 'atlas/web' / filename
        destination = public / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        if committed_assets:
            destination.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:atlas/web/' + filename], cwd=root))
        else:
            shutil.copy2(source, destination)
    (public / '_headers').write_text("""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'
""")
    package = target / 'atlas'
    package.mkdir(exist_ok=True)
    for name in PACKAGE_FILES:
        shutil.copy2(root / 'atlas' / name, package / name)
    shutil.copy2(root / 'deploy/cloudflare/worker.py', target / 'worker.py')
    cluster = json.loads((root / 'data/curated/grin_cluster_demo_v2.json').read_text())
    receipt = json.loads((root / 'data/benchmarks/grin-v1/cluster-annotation-receipt-v2.json').read_text())
    if cluster['reference_sha256'] != receipt['reference']['sha256'] or not receipt['validation']['bundle_rebuild_equal']:
        raise ValueError('Reviewed cluster and verification receipt do not match.')
    cluster_path = root / 'data/curated/grin_cluster_demo_v2.json'
    if hashlib.sha256(cluster_path.read_bytes()).hexdigest() != receipt['files']['data/curated/grin_cluster_demo_v2.json']['sha256']:
        raise ValueError('Reviewed cluster changed since verification.')
    bundle = reviewed_graph(json.loads((root / 'data/curated/grin_atlas_bundle.json').read_text()), cluster)
    errors = validate_bundle(bundle)
    if errors:
        raise ValueError(errors)
    if bundle['dataset']['synthetic']:
        raise ValueError('Production deployment cannot use synthetic fixtures.')
    store = GraphStore()
    try:
        store.load_bundle(bundle)
        stats = store.stats()
    finally:
        store.close()
    (target / 'snapshot.py').write_text('import json\nBUNDLE = json.loads(' + repr(json.dumps(bundle, separators=(',', ':'))) + ')\nSTATS = ' + repr(stats) + '\n')
    public_receipt = json.loads((root / 'data/curated/cloudflare_public_data_receipt.json').read_text())
    for key, relative in [('excerpts', 'data/curated/grin_public_excerpts_v2.json'), ('hgnc', 'data/curated/hgnc_dense_snapshot.json.gz')]:
        if public_receipt[key]['path'] != relative or hashlib.sha256((root / relative).read_bytes()).hexdigest() != public_receipt[key]['sha256']:
            raise ValueError(f'Public {key} snapshot does not match its receipt.')
    dense = json.loads(gzip.decompress((root / 'data/curated/hgnc_dense_snapshot.json.gz').read_bytes()))
    dense_receipt = public_receipt['hgnc']
    if dense['dataset']['synthetic'] is not False or len(dense['nodes']) != dense_receipt['nodes'] or len(dense['claims']) != dense_receipt['claims']:
        raise ValueError('Public HGNC counts or synthetic flag do not match the receipt.')
    node_ids = {n['id'] for n in dense['nodes']}
    if len(node_ids) != len(dense['nodes']) or len({c['id'] for c in dense['claims']}) != len(dense['claims']):
        raise ValueError('Duplicate public graph identities.')
    if any(c['subject'] not in node_ids or c['object'] not in node_ids for c in dense['claims']):
        raise ValueError('Public graph contains a dangling relationship.')
    if sorted(d['key'] for d in dense['public_datasets']) != sorted(dense_receipt['dataset_keys']) or any(n['type'] not in ('Gene','Protein') for n in dense['nodes']):
        raise ValueError('Public graph exceeds the allowlisted HGNC projection.')
    (target / 'dense_snapshot.py').write_text('import json\nBUNDLE = json.loads(' + repr(json.dumps(dense, separators=(',', ':'))) + ')\n')
    public_excerpts = json.loads((root / 'data/curated/grin_public_excerpts_v2.json').read_text())
    if public_excerpts['source_snapshot_digest'] != cluster['sources_sha256'] or public_excerpts['reference_sha256'] != cluster['reference_sha256']:
        raise ValueError('Public excerpts belong to a different source/reference snapshot.')
    spans = public_excerpts['excerpts']
    if len(spans) != public_receipt['excerpts']['count']:
        raise ValueError('Public excerpt count does not match its receipt.')
    valid_keys = {f"{s['unit_id']}:{s['start']}:{s['end']}":s for record in cluster['observations']+cluster['claims'] for s in record['evidence']+record.get('comparator',{}).get('evidence',[])}
    if any(key not in valid_keys or not isinstance(text,str) or len(text) != valid_keys[key]['end']-valid_keys[key]['start'] for key,text in spans.items()):
        raise ValueError('Public excerpts do not match cited span boundaries.')
    # A clean checkout uses the sealed, already-published excerpts. If originals
    # are present, verify them too; never silently accept a changed source cache.
    source_path = root / OPTIONAL_SOURCES
    if source_path.exists():
        sources = json.loads(source_path.read_text())
        if digest(sources) != cluster['sources_sha256']:
            raise ValueError('Frozen source snapshot does not match the reviewed cluster.')
        if extract_public_excerpts(cluster, sources) != spans:
            raise ValueError('Published excerpts differ from the frozen source spans.')
    (target / 'cluster_snapshot.py').write_text('import json\nCLUSTER = json.loads(' + repr(json.dumps(cluster, separators=(',', ':'))) + ')\nEXCERPTS = json.loads(' + repr(json.dumps(spans, separators=(',', ':'))) + ')\n')
    page = (root / 'atlas/cluster_web.html').read_text()
    style = re.search(r'<style>(.*?)</style>', page, re.S).group(1)
    script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
    (public / 'cluster.css').write_text(style)
    (public / 'cluster.js').write_text(script)
    page = re.sub(r'<style>.*?</style>', '<link rel="stylesheet" href="/cluster.css">', page, flags=re.S)
    page = re.sub(r'<script>.*?</script>', '<script src="/cluster.js" defer></script>', page, flags=re.S)
    page = page.replace('href="http://127.0.0.1:18767/"', 'href="/explore"').replace('Literature search ↗', 'Graph and chat ↗')
    (public / 'cluster.html').write_text(page)
    print(f'Reviewed cluster: {cluster["counts"]["observations"]} observations; {cluster["counts"]["claims"]} claims; {len(spans)} bounded source spans.')
    print(f'Built {target}: {len(dense["nodes"])} public HGNC nodes plus {len(bundle["nodes"])} reviewed GRIN nodes.')


def extract_public_excerpts(cluster, sources):
    units = {u['unit_id']:u for u in sources['units']}
    spans = {}
    for record in cluster['observations']+cluster['claims']:
        for span in record['evidence']+record.get('comparator',{}).get('evidence',[]):
            unit=units[span['unit_id']]
            start,end=span['start'],span['end']
            if not 0 <= start < end <= len(unit['text']):
                raise ValueError('Cited excerpt exceeds its source unit.')
            quote=unit['text'][start:end]
            if unit['kind']=='table_cell' or ('supplement:' in unit['locator'] and len(quote)<=300):
                spans[f"{span['unit_id']}:{start}:{end}"]=quote
    return spans


def input_hashes(root, *, committed_assets=False):
    # Include generator dependencies as well as uploaded modules; changing the
    # source-to-public projection must invalidate a previously generated build.
    paths = {path.relative_to(root) for path in (root / 'atlas').rglob('*.py')}
    paths.update(Path('atlas/web') / filename for filename, _ in _ASSETS.values())
    paths.update(map(Path, [
        'atlas/cluster_web.html', 'deploy/cloudflare/worker.py',
        'deploy/cloudflare/wrangler.jsonc', 'deploy/cloudflare/pyproject.toml',
        'deploy/cloudflare/uv.lock', 'deploy/cloudflare/pylock.toml', 'scripts/build_cloudflare.py',
        'scripts/verify_cloudflare_build.py', 'scripts/upload_cloudflare.py', 'scripts/verify_cloudflare_vendor.py',
        'data/curated/grin_cluster_demo_v2.json', 'data/curated/grin_atlas_bundle.json',
        'data/benchmarks/grin-v1/cluster-annotation-receipt-v2.json',
        'data/curated/cloudflare_public_data_receipt.json',
        'data/curated/grin_public_excerpts_v2.json',
        'data/curated/hgnc_dense_snapshot.json.gz',
    ]))
    if (root / OPTIONAL_SOURCES).exists():
        paths.add(OPTIONAL_SOURCES)
    return {str(path): hashlib.sha256(
        subprocess.check_output(['git', 'show', 'HEAD:' + str(path)], cwd=root)
        if committed_assets and str(path).startswith('atlas/web/')
        else (root / path).read_bytes()
    ).hexdigest() for path in sorted(paths)}


def output_paths():
    return ({'public/' + filename for filename, _ in _ASSETS.values()}
            | {'atlas/' + name for name in PACKAGE_FILES}
            | {'public/_headers', 'public/cluster.html', 'public/cluster.css', 'public/cluster.js',
               'worker.py', 'snapshot.py', 'dense_snapshot.py', 'cluster_snapshot.py'})


@contextmanager
def release_lock(root=ROOT, *, shared=False):
    """Serialize local build, verification and upload; never lock live worker data."""
    directory = Path(root) / 'deploy/cloudflare'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.atlas-release.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def build(root=ROOT, *, committed_assets=False):
    root = Path(root).resolve()
    # Alternate roots are used by isolated data/failure tests. Imported generator
    # code must match that root; use its own CLI process to build another revision.
    if root != ROOT:
        generators = [p.relative_to(ROOT) for p in (ROOT / 'atlas').rglob('*.py')]
        generators.append(Path('scripts/build_cloudflare.py'))
        if any(not (root / p).is_file() or (root / p).read_bytes() != (ROOT / p).read_bytes() for p in generators):
            raise ValueError('Alternate build root has different generator code; run its own build_cloudflare.py CLI.')
    with release_lock(root):
        return _build_locked(root, committed_assets=committed_assets)


def _build_locked(root, *, committed_assets=False):
    """Stage a complete allowlisted tree before replacing a known-good build."""
    root=Path(root).resolve()
    target=root/'deploy/cloudflare/build'
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink():
        raise ValueError('Build output must be a directory, not a symlink.')
    with tempfile.TemporaryDirectory(prefix='.atlas-build-',dir=target.parent) as temporary:
        inputs = input_hashes(root, committed_assets=committed_assets)
        staging=Path(temporary)/'build'
        _build_into(staging,root=root,committed_assets=committed_assets)
        # The manifest seals every generated file, including modules that Wrangler
        # will upload, so stale/private files cannot survive a rebuild unnoticed.
        outputs={str(p.relative_to(staging)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(staging.rglob('*')) if p.is_file()}
        if inputs != input_hashes(root, committed_assets=committed_assets):
            raise ValueError('Build inputs changed during packaging. Retry after edits finish.')
        manifest={'schema_version':'atlas-build-v1','asset_source':'HEAD' if committed_assets else 'working-tree','inputs':inputs,'files':outputs}
        (staging/'build-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        previous=Path(temporary)/'previous'
        if target.exists(): target.rename(previous)
        try: staging.rename(target)
        except BaseException:
            if previous.exists(): previous.rename(target)
            raise
    return target


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--committed-assets',action='store_true')
    args=parser.parse_args()
    build(committed_assets=args.committed_assets)

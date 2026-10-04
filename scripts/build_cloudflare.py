"""Build an allowlisted Cloudflare deployment of the reviewed GRIN cluster."""
import json
from pathlib import Path
import shutil
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atlas.cloud_bundle import reviewed_graph
from atlas.benchmark.contracts import digest
from atlas.model import validate_bundle
from atlas.server import _ASSETS
from atlas.store import GraphStore


def build():
    target = ROOT / 'deploy/cloudflare/build'
    target.mkdir(parents=True, exist_ok=True)
    public = target / 'public'
    public.mkdir(exist_ok=True)
    for filename, _ in _ASSETS.values():
        source = ROOT / 'atlas/web' / filename
        destination = public / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    (public / '_headers').write_text("""/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Content-Security-Policy: default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'
""")
    package = target / 'atlas'
    package.mkdir(exist_ok=True)
    for name in ['__init__.py', 'http_api.py', 'reasoning.py', 'questions.py', 'cluster_questions.py']:
        shutil.copy2(ROOT / 'atlas' / name, package / name)
    shutil.copy2(ROOT / 'deploy/cloudflare/worker.py', target / 'worker.py')
    cluster = json.loads((ROOT / 'data/curated/grin_cluster_demo_v2.json').read_text())
    receipt = json.loads((ROOT / 'data/benchmarks/grin-v1/cluster-annotation-receipt-v2.json').read_text())
    if cluster['reference_sha256'] != receipt['reference']['sha256'] or not receipt['validation']['bundle_rebuild_equal']:
        raise ValueError('Reviewed cluster and verification receipt do not match.')
    import hashlib
    cluster_path = ROOT / 'data/curated/grin_cluster_demo_v2.json'
    if hashlib.sha256(cluster_path.read_bytes()).hexdigest() != receipt['files']['data/curated/grin_cluster_demo_v2.json']['sha256']:
        raise ValueError('Reviewed cluster changed since verification.')
    bundle = reviewed_graph(json.loads((ROOT / 'data/curated/grin_atlas_bundle.json').read_text()), cluster)
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
    # Include cited table cells and short selected supplement rows, not entire papers.
    sources = json.loads((ROOT / 'data/processed/benchmarks/grin-development-v1/sources.json').read_text())
    if digest(sources) != cluster['sources_sha256']:
        raise ValueError('Frozen source snapshot does not match the reviewed cluster.')
    units = {u['unit_id']: u for u in sources['units']}
    spans = {}
    for record in cluster['observations'] + cluster['claims']:
        for span in record['evidence'] + record.get('comparator', {}).get('evidence', []):
            unit = units[span['unit_id']]
            quote = unit['text'][span['start']:span['end']]
            if unit['kind'] == 'table_cell' or ('supplement:' in unit['locator'] and len(quote) <= 300):
                spans[f"{span['unit_id']}:{span['start']}:{span['end']}"] = quote
    (target / 'cluster_snapshot.py').write_text('import json\nCLUSTER = json.loads(' + repr(json.dumps(cluster, separators=(',', ':'))) + ')\nEXCERPTS = json.loads(' + repr(json.dumps(spans, separators=(',', ':'))) + ')\n')
    page = (ROOT / 'atlas/cluster_web.html').read_text()
    style = re.search(r'<style>(.*?)</style>', page, re.S).group(1)
    script = re.search(r'<script>(.*?)</script>', page, re.S).group(1)
    (public / 'cluster.css').write_text(style)
    (public / 'cluster.js').write_text(script)
    page = re.sub(r'<style>.*?</style>', '<link rel="stylesheet" href="/cluster.css">', page, flags=re.S)
    page = re.sub(r'<script>.*?</script>', '<script src="/cluster.js" defer></script>', page, flags=re.S)
    page = page.replace('href="http://127.0.0.1:18767/"', 'href="/explore"').replace('Literature search ↗', 'Graph and chat ↗')
    (public / 'cluster.html').write_text(page)
    print(f'Reviewed cluster: {cluster["counts"]["observations"]} observations; {cluster["counts"]["claims"]} claims; {len(spans)} bounded source spans.')
    print(f'Built {target}: {len(bundle["nodes"])} nodes; {len(bundle["claims"])} claims.')


if __name__ == '__main__':
    build()

"""Small reproducible command line for the research atlas."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from atlas.store import GraphStore
from atlas.model import ValidationError, validate_bundle
from atlas.reasoning import AtlasReasoner
from atlas.recommendations import RecommendationEngine, ResearchRequest, SearchBudget
from atlas.export import to_jsonld, to_cytoscape

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / 'data' / 'atlas.sqlite'
FIXTURE = ROOT / 'data' / 'fixtures' / 'atlas-demo.json'


def dump(value, path=None):
    body = json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    if path:
        Path(path).write_text(body, encoding='utf-8')
    else:
        print(body, end='')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Rare-disease research atlas: evidence, context, and shared research.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('validate', help='Validate a normalized bundle without changing a database')
    p.add_argument('bundle')
    p = sub.add_parser('app', aliases=['research'], help='Run the connected Atlas graph, literature search, models and evidence workflow')
    p.add_argument('--bundle', help='Optional graph bundle; defaults to the combined real neuro and GRIN graph')
    p.add_argument('--documents', default=str(ROOT / 'data/curated/neuro_documents.json'))
    p.add_argument('--request', default=str(ROOT / 'data/curated/neuro_request.json'))
    p.add_argument('--workspace', default=str(ROOT / 'data/workspaces/atlas.json'))
    p.add_argument('--env-file', type=Path, default=ROOT / '.env' if (ROOT / '.env').exists() else None)
    p.add_argument('--search', choices=('auto', 'local', 'topk'), default='auto', help='Literature catalog provider; auto uses configured TopK credentials')
    p.add_argument('--provider', choices=('auto', 'openai', 'codex'), default='auto')
    p.add_argument('--model')
    p.add_argument('--model-timeout', type=int, default=120)
    p.add_argument('--retrieval', choices=('local', 'topk'), default='local')
    p.add_argument('--host', choices=('127.0.0.1', 'localhost'), default='127.0.0.1')
    p.add_argument('--port', type=int, default=8767)
    p.add_argument('--graph-db', type=Path, default=ROOT / 'data/graph/harvest.sqlite')
    p.add_argument('--resolved-graph', type=Path, default=ROOT / 'data/graph/neuro-resolved.json')
    p = sub.add_parser('resolve-neuro', help='Resolve neuro identities and extract unreviewed source-backed relationships')
    p.add_argument('--graph-db', type=Path, default=ROOT / 'data/graph/harvest.sqlite')
    p.add_argument('--output', type=Path, default=ROOT / 'data/graph/neuro-resolved.json')
    p.add_argument('--provider', choices=('auto','codex','openai'), default='codex')
    p.add_argument('--model')
    p.add_argument('--model-timeout', type=int, default=180)
    p.add_argument('--no-extract', action='store_true', help='Build registry/metadata identities without a model call')
    p = sub.add_parser('build-graph', help='Stream every registered harvested source into a resumable disk-backed graph')
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT / 'data/graph/harvest.sqlite')
    p.add_argument('--batch-size', type=int, default=5000)
    p = sub.add_parser('index-research', help='Explicitly upload the loaded source slice to the configured TopK semantic collection')
    p.add_argument('--documents', default=str(ROOT / 'data/curated/neuro_documents.json'))
    p = sub.add_parser('index-neuro', help='Index and verify the neuro source excerpts in their separate TopK collection')
    p.add_argument('--env-file', type=Path, default=ROOT / '.env' if (ROOT / '.env').exists() else None)
    for name in ('demo','ingest','stats','search','explore','recommend','reassess','export','serve'):
        p = sub.add_parser(name)
        p.add_argument('--db', default=str(DEFAULT_DB))
        if name in ('demo','ingest'):
            p.add_argument('--replace', action='store_true', help='Explicitly replace the existing dataset')
        if name == 'ingest': p.add_argument('bundle')
        if name == 'search': p.add_argument('query')
        if name == 'explore': p.add_argument('disease')
        if name in ('recommend', 'reassess'):
            p.add_argument('input', help='Research request JSON, or a previous result for reassess')
            p.add_argument('--output')
        if name == 'recommend':
            p.add_argument('--max-candidates', type=int, default=40)
            p.add_argument('--max-followup-queries', type=int, default=3)
            p.add_argument('--followup-proposals', help='Offline retriever response JSON; new evidence remains unreviewed')
        if name == 'export':
            p.add_argument('--format', choices=('json','jsonld','cytoscape'), default='json')
            p.add_argument('--output')
        if name == 'serve':
            p.add_argument('--host', default='127.0.0.1')
            p.add_argument('--port', type=int, default=8765)
    p = sub.add_parser('convert-hpoa', help='Convert a local HPO annotation TSV into an evidence bundle; does not download')
    p.add_argument('input')
    p.add_argument('--source-url', required=True)
    p.add_argument('--retrieved-at', required=True)
    p.add_argument('--source-version', required=True)
    p.add_argument('--license', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'resolve-neuro':
            from atlas.neuro_ingestion import build_neuro
            from atlas.ai import ModelClient, ModelError
            client = None if args.no_extract else ModelClient(args.provider,args.model,args.model_timeout)
            try:
                result = build_neuro(ROOT,args.graph_db,args.output,client=client,extract=not args.no_extract,
                                     progress=lambda row: print(json.dumps(row),flush=True))
            except ModelError as exc:
                print(f'Atlas extraction error ({exc.code}): {exc}',file=sys.stderr)
                return 1
            dump(result['resolution']['stats'])
            return 0
        if args.command == 'build-graph':
            from atlas.harvest_graph.build import build
            import time
            last = [0, None]
            def progress(stats):
                now = time.monotonic()
                if now - last[0] >= 10 or stats.get('current_dataset') != last[1] or stats['status'] != 'building':
                    print(json.dumps(stats), flush=True)
                    last[:] = [now, stats.get('current_dataset')]
            dump(build(args.source_root, args.output, progress=progress, batch_size=args.batch_size))
            return 0
        if args.command == 'index-neuro':
            from atlas.catalog import index_neuro
            try:
                dump(index_neuro(ROOT, env_file=args.env_file))
            except Exception:
                print('Atlas error: neuro indexing or verification failed; no verified receipt was issued for this run.', file=sys.stderr)
                return 1
            return 0
        if args.command == 'index-research':
            from atlas.retrieval import TopKRetriever, TopKError
            documents = json.loads(Path(args.documents).read_text(encoding='utf-8'))
            try:
                dump(TopKRetriever(documents).index_documents())
            except TopKError as exc:
                print(f'Atlas error: {exc}', file=sys.stderr)
                return 1
            return 0
        if args.command in ('app', 'research'):
            from atlas.ai import ModelClient
            from atlas.assistant import AtlasAssistant
            from atlas.catalog import EvidenceCatalog, combined_bundle
            from atlas.workflow import ResearchWorkspace
            from atlas.server import serve
            bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8')) if args.bundle else combined_bundle(ROOT)
            documents = json.loads(Path(args.documents).read_text(encoding='utf-8'))
            request = json.loads(Path(args.request).read_text(encoding='utf-8'))
            # A secret file is parsed as literal assignments, never executed.
            # API secrets remain in this server process, not the browser state.
            if args.env_file:
                import os
                for line in args.env_file.read_text().splitlines():
                    name, separator, value = line.partition('=')
                    name = name.strip().removeprefix('export ')
                    if separator and name in ('OPENAI_API_KEY',) and not os.environ.get(name):
                        os.environ[name] = value.strip().strip('\"\'')
            client = ModelClient(args.provider, args.model, args.model_timeout)
            catalog = EvidenceCatalog(ROOT, env_file=args.env_file, mode=args.search)
            workspace = ResearchWorkspace(bundle, documents, request, path=args.workspace, client=client,
                retrieval=args.retrieval, catalog=catalog, assistant=AtlasAssistant(client, catalog))
            harvest = None
            if args.graph_db.is_file():
                from atlas.harvest_graph.store import HarvestGraph
                import sqlite3
                with sqlite3.connect(args.graph_db) as conn:
                    source_root = conn.execute("SELECT value FROM metadata WHERE key='source_root'").fetchone()[0]
                harvest = HarvestGraph(args.graph_db, source_root)
            resolved = None
            if args.resolved_graph.is_file():
                from atlas.resolved_graph import ResolvedGraph
                resolved = ResolvedGraph(args.resolved_graph, harvest=harvest)
            with GraphStore() as store:
                store.load_bundle(workspace._active_bundle())
                print(f'Atlas: http://{args.host}:{args.port}/explore', flush=True)
                serve(store, args.host, args.port, workspace=workspace, harvest=harvest, resolved=resolved)
            return 0
        if args.command == 'validate':
            bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8'))
            errors = validate_bundle(bundle)
            dump({'valid':not errors,'errors':errors})
            return 1 if errors else 0
        if args.command == 'convert-hpoa':
            from atlas.ingest import hpoa_to_bundle
            bundle = hpoa_to_bundle(Path(args.input).read_text(encoding='utf-8'), source_url=args.source_url,
                retrieved_at=args.retrieved_at, source_version=args.source_version, license=args.license)
            errors = validate_bundle(bundle)
            if errors:
                dump({'valid':False,'errors':errors})
                return 1
            dump(bundle,args.output)
            return 0
        path = Path(args.db)
        if args.command not in ('demo','ingest') and not path.is_file():
            parser.error('Database does not exist. Run `python -m atlas demo` or ingest a validated bundle first.')
        if args.command in ('demo','ingest'):
            bundle = json.loads((FIXTURE if args.command == 'demo' else Path(args.bundle)).read_text(encoding='utf-8'))
            if args.command == 'demo':
                from atlas.demo import expand_demo
                bundle = expand_demo(bundle)
            errors = validate_bundle(bundle)
            if errors:
                dump({'valid':False,'errors':errors})
                return 1
            if path.exists() and not args.replace:
                parser.error('Database exists. Use --replace to explicitly replace its dataset, or select a new --db path.')
            path.parent.mkdir(parents=True,exist_ok=True)
        store = GraphStore(str(path))
        try:
            if args.command in ('demo','ingest'): dump(store.load_bundle(bundle))
            elif args.command == 'stats': dump(store.stats())
            elif args.command == 'search': dump(store.search(args.query))
            elif args.command == 'explore': dump(AtlasReasoner(store.bundle()).explore(args.disease))
            elif args.command in ('recommend', 'reassess'):
                engine = RecommendationEngine(store.bundle())
                data = json.loads(Path(args.input).read_text(encoding='utf-8'))
                if args.command == 'reassess':
                    result = engine.reassess(data)
                else:
                    retriever = None
                    if args.followup_proposals:
                        proposals = json.loads(Path(args.followup_proposals).read_text(encoding='utf-8'))
                        class FileRetriever:
                            def retrieve(self, questions, *, max_claims):
                                return proposals
                        retriever = FileRetriever()
                    result = engine.run(ResearchRequest.from_dict(data), retriever=retriever,
                        budget=SearchBudget(max_candidates=args.max_candidates,
                                            max_followup_queries=args.max_followup_queries))
                dump(result, args.output)
            elif args.command == 'export':
                bundle = store.bundle()
                dump({'json':lambda b:b,'jsonld':to_jsonld,'cytoscape':to_cytoscape}[args.format](bundle),args.output)
            elif args.command == 'serve':
                from atlas.server import serve
                print(f'Atlas: http://{args.host}:{args.port} (read-only local explorer)',flush=True)
                serve(store,args.host,args.port)
        finally:
            store.close()
    except (ValidationError, ValueError, OSError, KeyError) as exc:
        print(f'Atlas error: {exc}',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

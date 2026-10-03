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
    p = sub.add_parser('research', help='Run the complete local neuro research workspace')
    p.add_argument('--bundle', default=str(ROOT / 'data/curated/neuro_bundle.json'))
    p.add_argument('--documents', default=str(ROOT / 'data/curated/neuro_documents.json'))
    p.add_argument('--request', default=str(ROOT / 'data/curated/neuro_request.json'))
    p.add_argument('--workspace', default=str(ROOT / 'data/research/session.json'))
    p.add_argument('--provider', choices=('auto', 'openai', 'codex'), default='auto')
    p.add_argument('--model')
    p.add_argument('--model-timeout', type=int, default=120)
    p.add_argument('--retrieval', choices=('local', 'topk'), default='local')
    p.add_argument('--host', choices=('127.0.0.1', 'localhost'), default='127.0.0.1')
    p.add_argument('--port', type=int, default=8767)
    p = sub.add_parser('index-research', help='Explicitly upload the loaded source slice to the configured TopK semantic collection')
    p.add_argument('--documents', default=str(ROOT / 'data/curated/neuro_documents.json'))
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
        if args.command == 'index-research':
            from atlas.retrieval import TopKRetriever, TopKError
            documents = json.loads(Path(args.documents).read_text(encoding='utf-8'))
            try:
                dump(TopKRetriever(documents).index_documents())
            except TopKError as exc:
                print(f'Atlas error: {exc}', file=sys.stderr)
                return 1
            return 0
        if args.command == 'research':
            from atlas.ai import ModelClient
            from atlas.workflow import ResearchWorkspace
            from atlas.server import serve
            bundle = json.loads(Path(args.bundle).read_text(encoding='utf-8'))
            documents = json.loads(Path(args.documents).read_text(encoding='utf-8'))
            request = json.loads(Path(args.request).read_text(encoding='utf-8'))
            workspace = ResearchWorkspace(bundle, documents, request, path=args.workspace,
                client=ModelClient(args.provider, args.model, args.model_timeout), retrieval=args.retrieval)
            with GraphStore() as store:
                store.load_bundle(workspace._active_bundle())
                print(f'Research workspace: http://{args.host}:{args.port}/research', flush=True)
                serve(store, args.host, args.port, workspace=workspace)
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

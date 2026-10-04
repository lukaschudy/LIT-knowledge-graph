"""Run with python -m atlas.search; credentials never enter output artifacts."""
import argparse
import json
from pathlib import Path
import sys

from .passages import export
from .topk import DEFAULT_REGION, checked_bundle, client_from_settings, graph_connections, ingest, search, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--root", type=Path, default=Path.cwd())
    prepare.add_argument("--output", type=Path, default=Path("data/processed/search/grin-passages.jsonl.gz"))
    prepare.add_argument("--curated-only", action="store_true")
    sub.add_parser("status")
    upload = sub.add_parser("ingest")
    upload.add_argument("--export", type=Path, required=True)
    upload.add_argument("--checkpoint", type=Path, required=True)
    upload.add_argument("--create", action="store_true")
    upload.add_argument("--workers", type=int, default=1, help="One to four upload workers; default one for account quotas")
    query = sub.add_parser("query")
    query.add_argument("text")
    query.add_argument("--snapshot", required=True)
    query.add_argument("--mode", choices=["hybrid", "semantic", "keyword"], default="hybrid")
    query.add_argument("--gene")
    query.add_argument("--variant")
    query.add_argument("--kind")
    query.add_argument("--k", type=int, default=10)
    query.add_argument("--bundle", type=Path, default=Path("data/curated/grin_atlas_bundle.json"))
    query.add_argument("--checkpoint", type=Path, help="Enables graph linking after validating the indexed bundle revision")
    args = parser.parse_args()
    if args.command == "prepare":
        result = export(args.root, args.output, fulltext=not args.curated_only)
    else:
        config = settings(args.env_file)
        client = client_from_settings(config)
        collection = config.get("TOPK_COLLECTION") or "lit-grin-evidence-v1"
        if args.command == "status":
            result = {"connected": True, "region": config.get("TOPK_REGION") or DEFAULT_REGION,
                      "collections": repr(client.collections().list())}
        elif args.command == "ingest":
            result = ingest(client, collection, args.export, args.checkpoint,
                            config.get("TOPK_REGION") or DEFAULT_REGION, create=args.create, workers=args.workers,
                            progress=lambda row: print(json.dumps(row), file=sys.stderr, flush=True))
        else:
            result = search(client, collection, args.text, args.snapshot, k=args.k,
                            mode=args.mode, gene=args.gene, protein=args.variant, kind=args.kind)
            result["connections"] = []
            if args.checkpoint:
                state = json.loads(args.checkpoint.read_text())
                if (state["snapshot_id"] != args.snapshot or state["collection"] != collection
                        or state["region"] != (config.get("TOPK_REGION") or DEFAULT_REGION)):
                    raise ValueError("Checkpoint does not match search target")
                result["connections"] = graph_connections(result["hits"], checked_bundle(args.bundle, state))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # SDK exceptions may contain transport details; never dump credential-bearing clients.
        print(f"Search operation failed ({type(exc).__name__}). Check configuration and local inputs.", file=sys.stderr)
        sys.exit(1)

"""Offline benchmark entry point. Never calls a model or reads API secrets."""
import argparse
import json
from pathlib import Path

from .contracts import validate_manifest
from .scoring import score


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate-manifest")
    check.add_argument("manifest", type=Path)
    run = sub.add_parser("score")
    for name in ("manifest", "sources", "reference", "predictions", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--bootstrap-iterations", type=int, default=2000)
    run.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    try:
        manifest = read(args.manifest)
        if args.command == "validate-manifest":
            docs = validate_manifest(manifest)
            print(json.dumps({"valid": True, "state": manifest["state"], "synthetic": manifest["synthetic"],
                              "documents": len(docs), "held_out_documents": sum(d["split"] == "held_out" for d in docs.values()),
                              "ready_for_scoring": False if any(d["source_sha256"] is None for d in docs.values()) else "requires_reference_validation"}))
        else:
            report = score(manifest, read(args.sources), read(args.reference), read(args.predictions),
                           iterations=args.bootstrap_iterations, seed=args.seed)
            # Reports contain reference answers: keep them in the evaluator's workspace.
            with args.output.open("x", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.write("\n")
            print(json.dumps({"output": str(args.output), "observations": report["observations"],
                              "assessment": report["assessment"]}))
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"Benchmark error: {exc}\n")


if __name__ == "__main__":
    main()

"""Prepare metadata-only candidates; never infer unseen status or reference answers."""
import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path

from .contracts import VERSION, digest, validate_manifest


def file_sha(path):
    h = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare(root):
    root = Path(root)
    curated_path = root / "data/curated/grin_functional_evidence.json"
    known = {s["pmcid"]: s for s in json.loads(curated_path.read_text())["sources"]}
    candidates, inputs = {}, {str(curated_path.relative_to(root)): file_sha(curated_path)}
    for filename in ("grin_licensed_full_text.jsonl.gz", "grin_html_full_text.jsonl.gz"):
        path = root / "data/processed/harvest/pmc_grin_oa" / filename
        relative = str(path.relative_to(root))
        inputs[relative] = file_sha(path)
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                candidate = candidates.setdefault(row["pmcid"], {"document_id": row["pmcid"], "title": row["title"],
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{row['pmcid']}/", "available_sources": []})
                candidate["available_sources"].append({"path": relative, "record_pmcid": row["pmcid"],
                    "format": "jats_xml" if "jats_xml" in row else "html_body_text",
                    "record_sha256": digest(row), "license": row["license"]})
    for pmcid, source in known.items():
        candidate = candidates.setdefault(pmcid, {"document_id": pmcid, "title": source["title"],
                                                  "url": source["url"], "available_sources": []})
        html = root / "data/raw/harvest/grin_primary_pages" / (pmcid + ".html")
        if html.exists():
            relative = str(html.relative_to(root))
            inputs[relative] = file_sha(html)
            candidate["available_sources"].append({"path": relative, "format": "article_html",
                "sha256": inputs[relative], "license": "Individual article terms; no assumed redistribution permission"})
    for pmcid, candidate in candidates.items():
        candidate.update(exposure="known_development" if pmcid in known else "unknown_requires_audit",
                         screening="pending", study_grouping="pending", split="unassigned")
    manifest = {"schema_version": VERSION, "benchmark_id": "grin-development-seed-v1", "state": "draft",
                "synthetic": False, "scope": "Seven previously curated papers. Development only; study grouping, source units and independent annotations pending.",
                "documents": [{"document_id": pmcid, "study_id": "UNREVIEWED-" + pmcid,
                               "split": "development", "known_development": True, "grouping_reviewed": False,
                               "source_sha256": None, "strata": ["previously_curated", "screening_pending"]}
                              for pmcid in sorted(known)]}
    validate_manifest(manifest)
    inventory = {"schema_version": "grin-benchmark-candidates-v1", "input_sha256": inputs,
                 "documents": sorted(candidates.values(), key=lambda r: r["document_id"]),
                 "counts": {"candidates": len(candidates), "known_development": len(known), "assigned_held_out": 0},
                 "limitations": ["Candidate inventory is not the benchmark sample; relevance screening is pending.",
                                 "Unknown exposure is not evidence that a paper is unseen.",
                                 "No study families, reference labels, source units or reviewer identities are inferred.",
                                 "Full texts and restricted article content are not copied into these metadata files."]}
    return manifest, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing directories are refused")
    args = parser.parse_args()
    manifest, inventory = prepare(args.root)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("development-manifest.json", manifest), ("candidate-inventory.json", inventory)):
        (args.output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(inventory["counts"]))


if __name__ == "__main__":
    main()

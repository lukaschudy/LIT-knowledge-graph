# Live harvesting

The acquisition pipeline is separate from the concurrently developed Atlas application. It stores complete downloaded artifacts and normalized source records; clustering and inferred biological links are a later step.

## Storage and evidence

- `data/raw/harvest/<source>/`: downloaded source snapshots and API responses, outside Git.
- `data/processed/harvest/<source>/`: streamed gzip JSONL records, outside Git.
- `data/harvest-manifests/<source>.json`: version, URL, acquisition time, licensing reference, SHA-256, counts and coverage, committed to Git.
- `harvest/`: connector code. Requires Python 3.11+ and `requests`.

Cached acquisitions are reused only after SHA-256 verification. Incomplete GET downloads resume when the source supplies an entity validator; normalized outputs replace earlier files only after parsing succeeds. The downloader maintains an 8 GiB free-disk reserve. Large raw datasets are not pushed into GitHub commits.

## Scope

The target is the full accessible rare-disease source collection: complete ontology and structured reference releases; all matches for recorded research queries; community/asset metadata where authorized; clearly recorded access gaps for licensed or restricted sources. An exhaustive query result is not proof that the query captures all rare-disease research. Manifests must distinguish whole-file completeness from query recall, source subsets, missing fields, and denied access.

Preserve native IDs, conflict/review status, phenotype negation/frequency, version history, upstream references and species. Source-normalized records are not clinical conclusions. A submitted grant abstract or preprint claim is not scientific validation.

## Commands

```bash
python3 -m unittest discover -s tests_harvest -v
python3 -m harvest.biology
python3 -m harvest.enrichment
python3 -m harvest.research
```

Connector commands and the final coverage report will identify partial/failing sources; retries must resume recorded work rather than silently overwriting or reporting empty results as complete.

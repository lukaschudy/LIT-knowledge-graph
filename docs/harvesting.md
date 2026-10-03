# Live harvesting

The acquisition pipeline is separate from the concurrently developed Atlas application. It stores complete downloaded artifacts and normalized source records; clustering and inferred biological links are a later step.

## Storage and evidence

- `data/raw/harvest/<source>/`: downloaded source snapshots and API responses, outside Git.
- `data/processed/harvest/<source>/`: streamed gzip JSONL records, outside Git; new exports default to compression level 6.
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
python3 -m harvest.literature --workers 8
python3 -m harvest.opportunities all
python3 -m harvest.audit --reuse-verified
python3 -m harvest.status
python3 -m harvest.report
```

Connector commands and the final coverage report will identify partial/failing sources; retries must resume recorded work rather than silently overwriting or reporting empty results as complete.

The literature collector limits new requests to two per second and can use up to eight concurrent workers. It keeps a disk-backed identifier index and explicit per-query checkpoints. `--reuse-verified` still hashes every stored artifact and dataset; it only reuses the structural record scan when the manifest and all file bytes match the earlier successful audit.

Read [the coverage report](harvest-coverage.md) for current source counts and access limitations, and [the GRIN demonstration](grin-demo.md) for the selected functional cohort and reproducible graph. Full acquisition datasets and the small curated demonstration are separate layers.

## Literature count reconciliation

If the literature manifest records count discrepancies, run `python3 -m harvest.literature_recheck --all` to independently traverse those queries in publication-date order and retrieve any missing core records. Then rerun `python3 -m harvest.literature --workers 8` to re-emit normalized outputs from the corrected index. Completed query downloads are reused. The finalizer checks both exported article IDs and per-query membership counts before resolving a discrepancy; original response snapshots remain preserved.

The alias “the syndrome,” supplied for Trichohepatoenteric syndrome, is excluded as a non-discriminating query phrase. Its preferred name and specific aliases remain searchable. The source vocabulary, excluded-alias reason, superseded query and retained raw responses are recorded in the manifest. Other search hits remain retrieval candidates requiring relevance review.

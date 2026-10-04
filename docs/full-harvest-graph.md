# Full harvested-data graph

The main `/explore` graph can browse the complete locally harvested corpus: **105 registered datasets and 21,746,825 normalized source records**. The current snapshot indexes **8,914,689 entities and 53,429,267 explicit source relationships**. Every source row, including administrative metadata and rows without a supported semantic mapping, remains addressable in the dataset browser.

The [verification receipt](research/full-harvest-graph-2026-10-04.json) records dataset counts, source-row checks and index integrity.

## Build and run

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[topk,graph]'
.venv/bin/python -m atlas build-graph --source-root /absolute/path/to/harvest-repository
.venv/bin/python -m atlas app --env-file .env --search topk --provider codex
```

The source repository must contain `data/harvest-manifests/*.json` and the normalized gzip files registered in those manifests. `--output PATH` changes the default index at `data/graph/harvest.sqlite`; pass the same path as `atlas app --graph-db PATH`. Keep the adjacent `.sqlite.sources` directory and original harvested files. The build stores the absolute source root; it does not copy the corpus.

The builder checks compressed-file SHA-256 hashes, byte counts and final row counts. It commits checkpoints every 5,000 records and resumes when rerun against the same snapshot. It pauses if disk space falls below its reserve. Source snapshots must remain unchanged; use a new output index for a changed harvest. Index files and local workspaces are ignored by Git.

The app defaults to **All harvested data** and its dense 10,000-node view. The [resolved neuro neighborhood](neuro-entity-resolution.md) is available as an optional scope when its artifact is present.

## Explore a dense graph

- Choose the number of nodes to display, up to **10,000 per page**. Loading further pages or neighborhoods adds to the visible graph; reset the view to clear accumulated pages. The full store is larger than the current canvas.
- Search the full entity index by exact identifier or label prefix, including entities outside the current view. Select a result to load its neighborhood.
- Expand a selected node to inspect source relationships. Open a relationship or node to read its original JSON record, dataset, row number and source receipt.
- Browse **all datasets** and their paginated source records. A record does not need a materialized biological edge to remain accessible.

The graph distinguishes entity counts, relationship counts, original record counts and the current view. Duplicate source assertions can remain separate edges because each has its own provenance; graph edge counts are not counts of independent scientific findings.

## Why this representation

Loading millions of objects into a browser would make interaction impractical. SQLite holds the complete entity/relationship index while the browser renders bounded, dense projections. Binary row offsets and gzip seek indexes retrieve original records without duplicating their large payloads. Stable source identifiers connect registries, papers, genes, diseases, variants, pathways, proteins, trials and organizations. Names alone do not merge researchers.

Source adapters retain explicit distinctions: negative GO/HPO annotations, mouse and other species, ClinGen/GenCC assertion classifications, ontology hierarchy, query membership and identifiers. Associations and clinical classifications are not converted into functional effects or causal treatment claims. Complex fields without an adapter remain in the exact original record.

## Relationship to Astra, TopK and recommendations

The broad graph and the focused evidence workflow share `/explore`. Harvested relationships remain **unreviewed source relationships**. They do not automatically acquire expert approval or become qualified evidence in the recommendation engine.

TopK still searches the verified GRIN and neuro passage collections. Bulk graph ingestion does not embed 21.7 million records or send them to a model. Selecting a harvested entity can provide a text hint to Ask Atlas; an answer still uses the focused catalog and its validated citations. The review/planning workspace retains its own versioned claims and gates. Broad-corpus semantic retrieval and systematic scientific extraction are separate follow-on work.

## Read API

All endpoints are on the local Atlas server:

- `GET /api/harvest/status`
- `GET /api/harvest/graph?limit=3000&offset=0` (optional `focus=ENTITY_ID`)
- `GET /api/harvest/search?q=EPG5&limit=40`
- `GET /api/harvest/node?id=ENTITY_ID`
- `GET /api/harvest/claim?id=harvest:edge:EDGE_ID`
- `GET /api/harvest/datasets`
- `GET /api/harvest/records?dataset=DATASET_ID&page=0&limit=50`
- `GET /api/harvest/record?id=record:DATASET_ID:ROW_NUMBER`

Record row numbers are one-based; pages are zero-based. Graph offsets are cursors returned by `next_offset`, not page numbers. Node and relationship details resolve exact raw records. This local source browser is not a hosted multi-user database.

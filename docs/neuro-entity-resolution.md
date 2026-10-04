# Neuro entity ingestion and resolution

The default `/explore` view opens a bounded neuro neighborhood around EPG5/Vici, WDR45/BPAN and AP4B1/SPG47. It combines registry entities, source-scoped researchers and assets, publication metadata, and exact-quote model extractions. Expand a node or search by identifier, alias or label to navigate the larger resolved layer. Switch to **All harvested data** to browse the complete 105-dataset source graph.

## Run it

```bash
python3 -m atlas resolve-neuro --provider codex
python3 -m atlas app --env-file .env --search topk --provider codex
```

The existing harvest index and its original source files must be available. `resolve-neuro` writes `data/graph/neuro-resolved.json`; use `--output` and the app's `--resolved-graph` for a different location. `--no-extract` builds registry identities and structured metadata without model calls. Run the full command again to add extraction. Restart the app after rebuilding its startup snapshot.

The build reads bounded neighborhoods from the full SQLite graph. Publication metadata is joined by PMCID against the harvested Europe PMC dataset; the first scan is cached. Four supplied neuro text snapshots are extracted with the configured model. Validated extraction results are cached by source, supplied vocabulary, extractor code, provider and model, so a repeated build does not pay for unchanged requests. Quotes and source hashes are checked again before publishing cached results. The artifact is replaced atomically only after the build succeeds; a failed model response leaves the prior artifact intact. Generated artifacts, caches and original large datasets are excluded from Git.

The [live verification receipt](research/neuro-resolution-2026-10-04.json) records **1,056 entities, 34 identity merges and 44 new Astra-extracted claims** from this run. All 134 evidence quotations and source hashes passed the final artifact check.

## How identities are decided

- **Genes:** checked HGNC records anchor Ensembl, NCBI Gene and explicit OMIM cross-references.
- **Diseases:** checked MONDO anchors use `skos:exactMatch`. A general cross-reference is insufficient to merge disease concepts.
- **Phenotypes:** HPO identifiers retain phenotype semantics even when a broad association feed buckets them as diseases. The resolved layer records the original adapter type and the namespace correction.
- **Variants:** source variation identifiers stay distinct; this pass does not equate variants by similar labels or inferred genome coordinates.
- **Papers:** explicit PMID/PMCID/DOI fields establish equivalence. Three of the four supplied papers currently lack a matching harvested metadata row; those retain only the known PMCID from their source URL.
- **Researchers:** publication metadata supplies authors. ORCID identifies an author across records; without it, the author remains scoped to that paper. Equal names do not establish equal people.
- **Assets and other extracted mentions:** retain source-scoped identities unless the passage can refer to an existing supplied entity. Models cannot propose identity merges.

Every merge retains member identifiers, source pointers and its resolution rule. Conflicting authoritative IDs and incompatible types are rejected. The project-to-registry anchors live in `data/curated/neuro-identities.json`; edits fail if the checked registry label/type no longer matches.

## What an edge means

Registry edges preserve the source adapter's meaning and original-record pointer. Model edges preserve negation, species, context, a source hash, an exact unique quote and an uncalibrated extraction confidence. Invalid endpoints, invented identifiers, ambiguous quotations and malformed responses fail validation. Structured authorship edges come from exact publication metadata; they do not establish asset ownership, availability or willingness to collaborate.

`DISCUSSES` links a paper to entities in its grounded claims. It is a document-content connection, not an additional causal assertion. Existing curated neuro claims and their evidence survive identity remapping. Repeated scientific assertions retain separate provenance; relationship counts are not counts of independent discoveries.

This resolved artifact is a read-only exploration DTO. It includes broad source predicates and entity types and is **not** a replacement for the stricter recommendation bundle. Newly extracted evidence stays **unreviewed**. Identity resolution and exact-quote validation do not qualify a biological claim for a recommendation. The existing source-version-bound review/planning workspace remains separate; broad extracted claims are not automatically admitted to it.

## Interface and API

The overview starts with 120 entities, with 300 and 1,000 options. It balances entity types within graph-distance layers so large disease/ontology sets do not hide papers, researchers, variants and assays. Selecting and expanding a node retrieves its immediate neighborhood. Further pages extend the current view; the full resolved node count remains visible.

- `GET /api/resolved/status`
- `GET /api/resolved/graph?limit=120&offset=0` (optional `focus=HGNC:29331`)
- `GET /api/resolved/search?q=EPG5`
- `GET /api/resolved/node?id=HGNC:29331`
- `GET /api/resolved/claim?id=CLAIM_ID`

Use returned `next_offset` values for pagination. Node details expose identity members, decisions, conflicts and provenance. Model/metadata claim details expose supporting or contradictory quotations. Harvest claim IDs continue to open original JSON via `/api/harvest/claim`.

## Current boundary

This is a validated neuro ingestion pass over a bounded subset of the harvest, not corpus-wide entity resolution or scientific extraction. The entire raw corpus remains searchable in the harvest scope. TopK continues to search its verified passage collections; this build neither embeds the whole corpus nor claims a measured improvement in scientific discovery. Source missingness, author disambiguation and scientific review remain visible rather than being filled in by inference.

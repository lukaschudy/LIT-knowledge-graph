# From source extraction to an evidence-backed graph

This is a proposed implementation design, not a claim that connectors or a production graph exist. It combines the source-specific findings in [the extraction guide](source-extraction-guide.md) and [additional sources](additional-sources.md). Research date: 2026-10-03.

## Start with one complete journey

Use a small, reviewable disease cluster, selected for documented biology, an identifiable community and an existing asset. STXBP1-related disorders are a **candidate seed**, because the [Foundation biorepository](https://www.stxbp1disorders.org/biorepository) and [STARR natural-history study page](https://www.stxbp1disorders.org/starr) expose concrete research infrastructure. The selection is a practical proposal; related disease membership and shared mechanisms still need evidence. Do not prepopulate neighboring diseases merely because they share epilepsy or a synaptic gene label.

Target a reviewed seed set of 3–5 diseases, 5–15 genes, relevant curated variant assertions, 30–100 relevant publications, current study records, and 5–10 public organization/asset records. These are planning bounds, not promises about source coverage or a harvest already completed. Before scaling, demonstrate disease → supported biological connection → asset → organization/investigator → next research question, plus a counterexample that is not merged.

## Acquisition stages

1. **Identity and vocabulary.** Pin MONDO, HPO, HGNC and open Orphadata releases. Parse source-native identifiers, hierarchy and explicit mapping semantics. Register deprecated IDs and mapping confidence. Do not transform every xref into equivalence.
2. **Curated assertions.** Load focused ClinVar XML/TSV or Entrez records, ClinGen/GenCC, and licensed OMIM material only if access is granted. Preserve submission, inheritance, condition and review context. Add Reactome/UniProt/GO where needed to represent mechanisms and processes.
3. **Research and funding.** Discover papers with disease/gene synonyms; fetch PubMed metadata and eligible PMC text, then ClinicalTrials.gov and RePORTER records. Save search queries, count limits, pagination state and excluded records. Dates and publication status matter as much as titles.
4. **Communities and assets.** Curate the official directories and group pages for the chosen cluster. Add registry, natural-history study, biobank, assay/model and protocol nodes with access conditions and current-status evidence. Ingest public metadata, not private participant data.
5. **Extraction and reconciliation.** Apply deterministic parsing to structured sources. Use a schema-constrained language model on permitted text only where relations are genuinely in prose. Resolve candidate identities with source xrefs and a review queue. Never let the extractor invent a missing source identifier or citation.
6. **Evidence review and export.** Review the pilot's scientific links and all proposed cross-disease mechanism matches. Produce a graph export and a coverage report, with source versions and omitted/unavailable sources visible. Export only fields permitted by the underlying rights.

## Keep three layers

| Layer | Store | Why |
|---|---|---|
| Source records | Immutable source snapshots or permitted minimal metadata, URL, checksum, retrieval time, release, license | Reproduce the basis of a result without silently replacing history |
| Assertions | Subject, predicate, object, polarity, source record, evidence locator, context, review state | Preserve who claims what, disagreements and version-specific evidence |
| Resolved graph | Canonical entities and reviewed mappings; computed clusters/paths with their supporting assertions | Query efficiently without erasing uncertainty or provenance |

Start with versioned JSONL/Parquet entity/assertion tables plus a source manifest; choose the serving graph database after the query patterns are clear. A property graph or RDF can both work. Keep canonical exports independent of the chosen graph database so the dataset can be reproduced without a proprietary server.

## Minimum record contract

Every connector should emit:

```text
source_id, source_record_id, source_record_version, source_url
retrieved_at_utc, source_updated_at, dataset_release, payload_sha256
license_uri_or_terms_reference, reuse_status, acquisition_method
native_identifiers, raw_labels, language, parser_version
```

Every assertion additionally needs:

```text
assertion_id, subject_id, predicate, object_id_or_literal
source_record_key, evidence_locator, evidence_excerpt_if_permitted
asserted_by, assertion_date, polarity, evidence_type
species, tissue_or_model, variant_or_genotype, inheritance_context
extraction_method, extractor_version, extraction_confidence
mapping_status, scientific_review_status, supersedes, contradicted_by
```

Fields may be null only with a recorded reason; source version is not the retrieval date. For XML/JSON evidence use a stable element/field path; for papers use section and paragraph/table plus character offsets on a checksummed normalized text; for PDFs retain page and bounding box or text locator. A generic homepage is not adequate evidence for an individual edge.

`extraction_confidence` measures whether the parser/model recovered the passage correctly. It is **not** scientific evidence strength. Retain ClinVar review status, ClinGen classification, publication type and manual-review decisions as separate dimensions. A language model's self-reported probability should not substitute for calibration against a reviewed sample.

## Entity and relationship decisions

| Entity | Preferred identity | Required cautions |
|---|---|---|
| Disease | MONDO; preserve ORPHA/OMIM source identities | Disorder/group/subtype and narrow/broad mappings differ |
| Human gene | HGNC with NCBI Gene/Ensembl xrefs | Symbols change and aliases collide |
| Variant | ClinVar accession/Variation ID plus allele representation | Preserve assembly, transcript version, coordinates, haplotype/genotype; normalize explicitly |
| Phenotype | HP identifier | NOT, frequency, onset and disease context matter |
| Protein/pathway | UniProt accession/isoform; Reactome stable ID | Species, isoform, direction of effect and inference status matter |
| Publication | DOI/PMID/PMCID crosswalk; version nodes | Preprint and final publication are linked versions/works, not duplicate support |
| Study | NCT or registry's native accession | Planned outcomes differ from reported results; enrollment status can age |
| Grant/project | Application/project ID and fiscal-year record | Core project number is not an individual annual award |
| Person/institution | Verified ORCID / ROR where available | Name matching alone cannot establish identity or current employment |
| Patient organization | Persistent local UUID with verified official domain/source aliases | Umbrella organizations, alliances, chapters and campaigns differ |
| Research asset | Native catalogue/registry accession or local UUID | Record owner, intended use, validation, access procedure and availability date |

Use explicit predicates such as `HAS_PHENOTYPE`, `ASSERTS_PATHOGENICITY_FOR`, `ASSOCIATED_WITH`, `PARTICIPATES_IN`, `STUDIES`, `OPERATES`, `MEMBER_OF` and `ANNOUNCED`. Preserve source predicate meaning. A paper mentioning a disease is not equivalent to evidence for a mechanism. A funded proposal is not evidence the proposed experiment succeeded. A registry listing is not a guarantee of dataset access.

## Completeness and incremental extraction

“All sources” in this task means a plan for every source named in the PDF. “All records” is a separate implementation property and must be measured per connector. A broad rare-disease query cannot prove exhaustive global coverage.

- For bulk files, record publisher manifest, release, size/checksum where supplied, downloaded file count, parsed/rejected rows and schema version. Do not silently skip parse failures.
- For APIs, record query and filters, total count when provided, all visited offsets/tokens, item count and deduplicated IDs. Respect search caps; partition or switch to bulk. Retry transient errors with bounded exponential backoff/jitter and honor `Retry-After`; save resumable state.
- For directories, record visited index/filter pages, profile links, reachable profiles, excluded/gated pages and access failures. A directory's membership coverage is not the world's patient-group coverage.
- Commit update watermarks only after every page in the run is stored/validated. Use overlapping time windows and deduplication where updates are not stable; periodically recheck known records because additions filters miss revisions.
- Distinguish provider deletion/withdrawal from temporary HTTP failure, changed query membership, expired access or malformed response. Maintain tombstones and superseded assertions; do not erase a clinical conflict by retaining only the newest row.
- Track upstream lineage: one paper mirrored by PubMed, PMC, Europe PMC and an aggregator is one scientific study with several metadata observations, not four confirmations.

## Proposed connector acceptance checks

These are implementation criteria, not tests claimed to have passed in this planning repository:

1. One seed record can be re-fetched or reconstructed from its licensed snapshot; its checksum/version is recorded.
2. Pagination/bulk manifests close without an unexplained count mismatch; schema changes fail visibly rather than yielding an empty graph.
3. Every exported assertion points to a resolvable source record and a field/text locator; inferred edges are labeled and retain their derivation inputs.
4. A fixture with an HPO `NOT`, conflicting ClinVar submissions, an obsolete disease ID, and a retracted paper retains all relevant distinctions after an update.
5. A fixture with the same gene but different variant effects does not automatically cluster together; different genes enter a mechanism cluster only with cited evidence.
6. Duplicate upstream evidence across aggregators is counted once for scientific support while provenance remains visible.
7. Rights/access restrictions propagate into export eligibility. Private/participant data and credentials never enter the public graph or repository.
8. A family-facing route exposes what is known, what is inferred, asset access conditions and the exact question requiring expert review. An unsupported route returns an honest coverage gap.

## Implementation order and dependencies

| Stage | Deliverable | External dependency |
|---|---|---|
| 1 | Versioned ontology/gene spine and mapping report | Open release access; attribution |
| 2 | Curated biology assertions with contradiction handling | OMIM access optional/conditional; open alternatives do not claim full OMIM coverage |
| 3 | Literature/trial/grant connectors and evidence locators | Provider rate policies; article-level reuse rights |
| 4 | Reviewed organization/asset seed set | NORD/export or source-specific permission where needed; registry contents remain separate |
| 5 | Reviewed clusters and one end-to-end action view | Domain review of scientific links and asset suitability |
| 6 | Wider disease/geographic expansion | Measured connector coverage and maintenance capacity |

Do not delay the whole pilot while waiting for a restricted source. Keep it listed as `access_pending` and show the resulting coverage limitation. For a meaningful milestone, compare the manual time needed to discover a reusable registry/model and qualified collaborator against the graph-assisted route; the PDF's 10× ambition is a hypothesis to evaluate, not an impact claim this research has established.

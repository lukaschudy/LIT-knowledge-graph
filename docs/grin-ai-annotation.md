# GRIN source snapshots and independent AI annotation

This development exercise prepares real source snapshots and separate-context AI annotations. It does not create human-reviewed gold labels or measure a held-out extraction model's accuracy. The two annotators receive identical source-only packets; a third AI adjudicator checks their drafts against the paper, including facts on which they agree. Model agreement can still contain correlated errors.

## Source snapshots

The local package is `data/processed/benchmarks/grin-development-v1/`. It contains seven original article HTML files, the already acquired Myers supplement PDF and extracted layout text, normalized source units, a table/coverage ledger, a draft manifest and a blank annotation template. The original artifacts are checked against their harvest hashes before use. Rebuilding into an existing directory is refused.

The snapshot contains **5,885 source units and 4,479 table cells**, including equation tables. Empty cells remain in the table ledger even though they cannot form nonempty quote units. Row/column spans, headers, captions, footnotes, methods and image references are preserved. A comparison with the existing harvest table parser found identical cell order and text in all seven articles. No article-tree repair was needed for these files.

There are **107 image-bearing cells** across the seven papers. Images are recorded, not transcribed or interpreted. Supplemental layout text is available for one paper only; nine supplement pages are included as explicit layout-text units. Whole-paper coverage therefore remains partial pending visual and supplement review. Source quotations use offsets into the saved unit text, not raw HTML or PDF bytes.

The committed `data/benchmarks/grin-v1/source-snapshot-receipt.json` and `source-snapshot-manifest.json` bind these local files to their hashes. Full source text and annotation quotations remain in the ignored local data directory. The original seven-document `development-manifest.json` is retained as the seed; the generated snapshot manifest adds actual source-unit hashes while keeping study grouping unreviewed.

```bash
.venv/bin/python -m atlas.benchmark.snapshots \
  --output /tmp/grin-development-snapshots
```

## First annotation scope

The first calibration batch covers **all 25 variant rows and all four functional endpoints in Swanger 2016 main Table 2**, a total of 100 cells. Both GRIN2A and GRIN2B are included without selecting variants by functional direction. The two WT rows are comparators, not separate observations. Other article sections provide experimental context; Table 3 is not part of this extraction batch.

The article's published Table 2 is HTML table number 8 because preceding equations use HTML table markup. `ai-pilot-scope.json` fixes the exact 100 source-cell IDs, row/column locations and scope description. This distinction avoids silently annotating the wrong table.

This one-table pilot calibrates annotation rules before expanding to the remaining papers. It is not a complete annotation of the seven-paper collection or a held-out test. The parent paper was already used in development, and every pilot manifest says so.

## Isolation and provenance

Two agents were created with `fork_turns: none` and no model override. Each received only the scoped manifest, source snapshot, source ledger, blank reference template, standalone contract and identical annotation instructions. Their directions explicitly excluded the curated graph, earlier conclusions, model predictions, other reviewer files, chat context and the network. The packets are byte-identical and reproducible with the packet builder.

This is context isolation and an explicit access instruction, not an operating-system security sandbox. The exact underlying model deployment identifier and provider token/cost receipts were not exposed by the collaboration tool. They must not be invented. Shared model priors remain a source of correlated errors.

Annotator A and B files are retained separately and unchanged. Both record AI identities, `expert_reviewed: false`, no adjudicator and no functional decisions. A third fresh-context agent receives the source and the completed drafts for adjudication. It is explicitly an AI adjudicator, not a third independent blind annotation or a human expert.

The annotation vocabulary fixes assay/property names, units and protein notation. It does not supply expected measurements, functional categories or reference answers. An entirely unreported measurement goes into the coverage ledger; it is not an invented zero or a quantitative observation with a silently missing value. The required coverage matrix includes every in-scope cell exactly once.

## Initial agreement and problems found

Both independent drafts contain **88 quantitative observations and 12 explicitly unreported cells**, with no unsupported quantitative cells in this bounded scope. They agree on all paired genes, protein variants, assay/property labels, numerical values, units, WT comparators, uncertainty magnitudes and sample counts. Reported uncertainty type and what n counts remain unknown where not explicitly defined for the table.

Exact whole-observation agreement is **0 of 88** because both drafts use different protocol prose. Receptor and expression-system assignments agree; the protocol descriptions differ in wording, detail and whether figure-specific agonist conditions can be generalized to the table. This is a development-schema finding, not evidence that all 88 measurements were transcribed incorrectly. It motivates canonical structured conditions and source-specific applicability rules rather than an LLM judge that overlooks differences.

The third agent's source audit also identified a shared sequence-context omission: the methods name construct reference accessions, while both annotators treated sequence context as requiring a flanking sequence. Assigning an unversioned construct accession must remain distinct from confirming a genomic allele or validating the residue against a versioned sequence. The original omissions remain visible in both drafts and the agreement report.

The comparison is **annotator agreement, not precision, recall or model accuracy**. The pilot produces a provisional development reference after adjudication; it must not be used to claim the same agents have passed an independent held-out benchmark.

## Completed AI adjudication

The third agent reconstructed all 100 cells from the source before comparing the drafts. The final provisional reference contains:

| Endpoint | Quantitative observations |
|---|---:|
| Glutamate EC50 | 22 |
| Glycine EC50 | 22 |
| Weighted deactivation time constant | 19 |
| Peak current density | 25 |
| Total | 88 |

There are 64 GRIN2A observations and 24 GRIN2B observations. The other 12 cells are explicitly unreported endpoints, not failed extractions or zero measurements. The source audit found no differences in reported numbers, units, gene/protein labels, WT values, uncertainty magnitudes or n relative to the drafts.

The reference corrects all 88 sequence-context omissions to the source-reported human construct accessions, preserves their unversioned status and records canonical protocols using 13 ordered keys. Figure-only conditions are retained separately without being assigned to every table row. The original drafts are unchanged. The change log includes both original values, the adjudicated value, reasons and source references.

Final artifacts in the local `adjudicator/` directory are `adjudicated-reference.json`, `adjudication.json`, `structured-protocols.json`, `adjudicator-notes.md` and a reproducible builder. The coordinator independently checked the reference contract, the complete cell-to-observation mapping, original-input hashes and **all 7,087 exact source spans** across the reference and audit artifacts. The committed `ai-annotation-pilot-receipt.json` records counts, provenance and file hashes.

Unresolved items remain explicit: table-wide uncertainty type, what n counts, some agonist concentrations, accession versions/residue compatibility, the anchor of the HEK recording delay and a conflicting nucleotide label. `expert_reviewed` remains false, no functional classification decisions were generated, and no held-out model accuracy was measured. The proposed structured-condition sidecar has not silently changed the existing benchmark contract.

## Reproduce packets and comparisons

Each output directory/file must be new. A packet contains no prefilled observations, scientific answers or reviewer identity.

```bash
.venv/bin/python -m atlas.benchmark.review packet \
  --snapshot data/processed/benchmarks/grin-development-v1 \
  --scope data/benchmarks/grin-v1/ai-pilot-scope.json \
  --output /tmp/grin-reviewer-source-only
```

The completed pilot lives at `data/processed/benchmarks/grin-ai-annotation-pilot-v1/`, with `reviewer-a/`, `reviewer-b/` and `adjudicator/` directories. To reproduce the comparison into a new file:

```bash
.venv/bin/python -m atlas.benchmark.review compare \
  --manifest data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-a/manifest.json \
  --sources data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-a/sources.json \
  --scope data/benchmarks/grin-v1/ai-pilot-scope.json \
  --a data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-a/annotations.json \
  --b data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-b/annotations.json \
  --coverage-a data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-a/coverage.json \
  --coverage-b data/processed/benchmarks/grin-ai-annotation-pilot-v1/reviewer-b/coverage.json \
  --output /tmp/grin-ai-agreement.json
```

The comparison validates source quotes, reviewer identities, all 100 coverage cells and one-to-one measurement-to-observation links. It rejects omitted cells, hidden extra observations, forged source spans, duplicate reviewer identities and claims of expert review in an unadjudicated AI draft. It reports every field and coverage disagreement for source-based adjudication without promoting any record automatically.

## Expansion criteria

Before expanding the annotation run, freeze an unambiguous definition of sequence context, canonical experimental-condition fields and the distinction between table-wide and figure-specific protocols. Preserve comparator uncertainty/sample size and significance markers in the coverage sidecar until the observation contract can represent them directly. Do not claim the current scorer measures those sidecar fields.

The next batches can extend to the same paper's calculated endpoints and the other six source snapshots. Censored values, interval-valued measurements, image-dependent classifications and supplementary evidence need explicit contract/coverage handling before a batch can be called complete. Keep all these papers in development until study grouping and exposure audits justify a genuinely separate test set.

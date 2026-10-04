# GRIN extraction benchmark

This repository now contains an offline benchmark foundation for source-grounded observations and functional decisions. It validates study splits, source snapshots, reference annotations and run metadata, then scores predictions without an LLM judge. It does not yet contain an independently reviewed GRIN answer set or a model runner. The synthetic example demonstrates software behavior only.

## What is ready

- `atlas/benchmark/contracts.py`: executable, strict annotation and prediction contracts. Unknown fields, duplicate IDs, ungrounded reference spans and inconsistent snapshots are rejected.
- `atlas/benchmark/scoring.py`: complete observation precision and recall, one-to-one matching, field diagnostics, decision confusion matrices, abstention coverage and study-cluster bootstrap intervals.
- `atlas/benchmark/prepare.py`: a reproducible metadata inventory of available papers and a development-only manifest for previously curated papers. It does not read scientific conclusions to assign test labels.
- `data/benchmarks/synthetic-v1/`: a complete invented example of every input format. No biomedical assertions or human reviewer identities are fabricated.
- `data/benchmarks/grin-v1/`: 360 candidate documents, including seven known development papers. The inventory combines 355 licensed full-text records with five additional individually acquired article pages. Candidates have not been screened for benchmark eligibility. No held-out studies have been assigned.

The existing `atlas/search/evaluate.py` remains a separate regression test over known curated evidence cards. Its hit rate is not extraction recall or independent scientific validation.

## The operational loop

1. **Define scope before annotation.** Decide which experimental endpoints, variants, conditions and source sections must be exhaustively annotated. Include negative and unresolved cases. Account for missing supplements and image-only cells. Do not silently exclude hard observations that the current format cannot represent.
2. **Screen candidates and group studies.** Audit development exposure, duplicate experiments, overlapping cohorts, supplements and secondary reports. A paper ID is not necessarily an independent study ID. The initial ten-development and twenty-test paper target is a recruitment target, not a frozen sample. Twenty test papers may contain fewer than twenty independent studies.
3. **Create source units.** Preserve stable paragraph, methods, caption, footnote and table-cell locators. Keep headers and footnotes as separate units and record table row/column locations, including spans, in locators. Retain a reconstruction/coverage ledger beside the original files. The current TopK flattened table text is insufficient to certify table completeness.
4. **Annotate independently.** Two reviewers read the same source snapshot without seeing predictions. Annotate all in-scope observations. Record disagreements and an adjudicated reference; preserve unresolved scientific interpretations. Functional assessments require qualified review. Do not copy the current machine-curated graph into an independent reference set.
5. **Freeze inputs and policy.** Freeze the source units, manifest, scope, annotation guide, matching rules, model budgets and acceptance policy. Store source hashes and record who reviewed study grouping. Keep held-out labels and detailed reports in a separate evaluator workspace inaccessible to the extraction runner.
6. **Run extraction and evidence checking.** Sol proposes observations; deterministic checks verify structure and exact source excerpts. Astra checks original evidence and may request bounded additional retrieval. Proposed initial limits are three retrieval rounds per case with explicit call/token caps. Missing context or continuing conflict leads to review or abstention. This model runner and its budget enforcement are not implemented here yet.
7. **Score offline.** Export predictions, including missing and failed executions, into this contract. The scorer consumes reference answers only after prediction generation. Record costs and token usage from provider receipts; use null when unknown. A successful CLI exit means a report was produced, never scientific approval.
8. **Diagnose development errors.** Inspect unmatched records and split failures into parsing, retrieval, identity, transcription, context and interpretation. Change one component at a time. Re-run regression tests and compare identical input hashes before comparing scores.
9. **Evaluate a selected release.** Use held-out results only after choosing the candidate on development data. If failures inform another change, record that exposure and treat those cases as regression data thereafter. Keep a dated exposure ledger; checksums cannot enforce reviewer independence or prevent someone reading a test answer.
10. **Audit accepted outputs.** Review all flagged cases plus a random sample of accepted cases. Measure correction time and sample selection. New confirmed failures enter development; reserve fresh studies for subsequent independent evaluations.

## Annotation contract

The four JSON files in `data/benchmarks/synthetic-v1/` are runnable examples. The authoritative validator is `contracts.py`; there is no permissive fallback or model-generated repair during scoring.

### Manifest and source units

A document declares `document_id`, `study_id`, `split`, `known_development`, `grouping_reviewed`, `source_sha256` and descriptive `strata`. Draft manifests permit missing source hashes. Frozen manifests require hashes and reviewed grouping. A study family cannot cross splits. A known development document cannot be assigned to `held_out`.

Each source unit contains `unit_id`, `document_id`, `kind`, `locator` and `text`. Unit IDs are globally unique. Character offsets are zero-based Python Unicode code-point offsets into this exact text, with an exclusive end. They are not PDF byte offsets or JavaScript UTF-16 indices. The document source hash is SHA-256 of canonical JSON for its units sorted by unit ID, using the included `digest` function. A changed source snapshot invalidates the previous reference/run binding.

The source-unit hash includes locators and document IDs. Identical hashes across splits are blocked, but changed locators or IDs can produce different hashes for duplicate content. Human study grouping and duplicate-content review remain necessary. Source formatting, original file hashes, figure/image omissions, licensing and transformation version belong in the preparation ledger. The candidate inventory already records original artifact/record hashes and access paths.

### Observations

An observation contains:

| Field | Annotation rule |
|---|---|
| `gene`, `variant`, `sequence_context` | Use the agreed canonical notation. Preserve unknown accession/transcript context as null; a protein mention alone does not establish an allele identity. |
| `assay`, `property`, `measurement_type` | Separate measured results from author-calculated results. Use a controlled annotation vocabulary frozen before testing. |
| `value`, `unit` | Store decimal values as strings, preserving source precision. Null means not represented/reported, never zero. |
| `comparator` | Store label, numeric value and units separately. Do not assume the nearest WT row belongs to the same experiment. |
| `conditions` | Retain receptor composition, expression system and experimental protocol. Protocol includes the concentrations, voltage, timing and other conditions necessary to identify this endpoint. |
| `uncertainty` | Preserve the reported uncertainty type and numeric value. Do not relabel SD as SEM. |
| `sample_size` | Preserve both the count and what was counted. Do not infer biological replication from an unqualified n. |
| `evidence_sets` in references | One or more acceptable sets of exact source spans. Each set must contain every needed row/header/method/footnote span. Alternative sets allow equivalent source locations without relaxing facts. |
| `evidence` in predictions | Exact source spans with unit ID, start, end and quote. Missing/forged spans cannot earn a grounded true positive. |

The v1 value structure represents scalar quantitative endpoints and a scalar uncertainty. Censored measurements, confidence intervals with two bounds, qualitative results and other unsupported structures must be recorded in the scope/coverage ledger and cause `coverage: partial` when in scope. Extend and test the versioned contract before freezing a benchmark containing those cases; do not convert unsupported values to null and call coverage complete.

Annotations declare `coverage` as `partial` or `complete`, distinct annotator IDs, an adjudicator ID and an expert-review flag. These are attestations, not proof that review occurred. Preserve original independent annotations and disagreement/adjudication records separately. The scorer requires every document in the selected split to appear in the reference, even when it has no observations.

### Decisions

Reference decisions contain a neutral `question`, `case_id`, one of `supports`, `contradicts` or `unresolved`, supporting observation IDs and a separate nullable `author_interpretation`. Define the proposition and experimental context explicitly. A source-qualified assay effect is not automatically an overall variant classification, and neither determines treatment suitability.

Predictions answer the declared cases with the same three labels or `abstain`. Missing decisions count as abstentions. A correct label receives grounded credit only when its referenced prediction observations match exactly the reference observation set through the observation scorer. Abstention is distinct from a justified unresolved finding. These are declared-case decisions, not a benchmark of open-ended claim discovery.

### Run metadata

Every prediction file binds to a manifest hash and split. It records a run ID, stage (`extraction` or `end_to_end`), code commit, prompt hash, full configuration and its hash, input/output tokens, dollar cost and elapsed time. The configuration object must record requested/resolved model identifiers, reasoning settings, parser version, retrieval snapshot/filters and budgets when applicable. The validator checks its hash but cannot verify provider execution or that every relevant option was recorded. Keep provider receipts and retrieval traces alongside it, outside Git if they contain source text or secrets.

The synthetic run uses an all-zero code hash and no models as explicit placeholders. Replace those with actual provenance for real runs. Unknown accounting fields are null, not zero.

## Scoring rules

Complete observation matches require agreement on every observation field and coverage of at least one full reference evidence set. Only whitespace, the two micro-symbol forms, and mathematically equal decimal-string formatting are normalized. There is no approximate number tolerance, unit conversion, fuzzy variant matching or semantic LLM judge. An extra field or invalid data type invalidates the run rather than silently dropping a record.

Maximum one-to-one matching prevents duplicate predictions earning multiple true positives. Extra predictions are false positives; unreturned reference observations are false negatives. Predictions from missing/failed documents do not disappear from the report. Verified partial output from a failed execution can still score, but the execution failure remains explicit.

Precision is `TP / (TP + FP)`; recall is `TP / (TP + FN)`. Undefined denominators are null. A paper with no reference observations can still incur false positives. Both micro totals and per-document macro summaries are reported, including how many documents have defined metrics.

Field diagnostics compare only uniquely aligned gene/variant/sequence/assay/property/measurement-type/condition anchors. They do not rescue a wrong identity and are not end-to-end accuracy. Numeric diagnostics count non-null reference numbers among those aligned pairs. Their denominator excludes missed/ambiguous records and is shown explicitly.

Exact source-text verification checks provenance, not biological entailment. The human reference evidence sets define which excerpts are adequate. An overly broad reference span weakens this check; prefer minimal sufficient evidence bundles.

Study-cluster bootstrap resamples whole study families and reports descriptive 95% percentile intervals, valid/undefined draw counts and the random seed. Fewer than two independent groups produces no interval. A perfect tiny sample can yield a degenerate interval; it does not establish absence of rare errors. Precision/recall targets of 95%/90% and numeric accuracy of 99% remain proposals, not a validated release policy. The numeric target must not be interpreted without observation recall and its restricted denominator.

The report never says scientifically validated. It is inconclusive for synthetic/development/draft data, incomplete annotation/review, failed execution or fewer than the proposed twenty independent test study families. Otherwise it requires release review. Freezing the final sample-size justification, scientific decision thresholds and acceptable uncertainty requires the actual annotation distribution and review policy.

## Run the example

From the repository root:

```bash
.venv/bin/python -m unittest discover -s tests_benchmark -v
.venv/bin/python -m atlas.benchmark validate-manifest data/benchmarks/grin-v1/development-manifest.json
.venv/bin/python -m atlas.benchmark score \
  --manifest data/benchmarks/synthetic-v1/manifest.json \
  --sources data/benchmarks/synthetic-v1/sources.json \
  --reference data/benchmarks/synthetic-v1/reference.json \
  --predictions data/benchmarks/synthetic-v1/predictions.json \
  --output /tmp/grin-synthetic-report.json
```

The output path must not exist; reports are never overwritten. The synthetic prediction matches its invented reference exactly, while the assessment remains inconclusive. The committed `synthetic-report.json` records this machinery check, not model performance.

To reproduce the candidate metadata in a new directory:

```bash
.venv/bin/python -m atlas.benchmark.prepare --root . --output /tmp/grin-benchmark-candidates
```

The seven-paper development manifest intentionally cannot be scored yet: normalized source units, reviewed study grouping and independent annotations are missing. No held-out answers are stored in this repository. Keep real reference sets and reports in a separate evaluator directory and out of any TopK collection/model context used by the runner.

## What comes next

Choose and annotate the development sample, including a source coverage audit and unsupported-value cases. Freeze the annotation vocabulary and expand the scalar contract where needed. Add a model runner that exports this format and compare Sol, Astra and Sol with Astra review under the same input scope and declared budgets. Independently prepare the held-out set after study grouping and exposure review.

Separate component benchmarks for retrieval Recall@k, entity mention recall, identity merges, annotator agreement, human correction time and clustering remain to be implemented. The existing scorer must not be presented as measuring those capabilities. A deployment decision needs those checks in addition to this observation benchmark.

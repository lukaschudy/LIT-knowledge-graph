# Seven-paper GRIN evidence cluster

This development demo connects the selected ten GRIN2A/GRIN2B protein variants to source-reported functional classifications and experimental observations across seven papers. The categories are source-guided groups, not an unsupervised clustering result, a patient cohort or a treatment recommendation.

## Annotation and review

Two fresh-context AI annotators received identical frozen source packets and the [v2 annotation contract](grin-cluster-annotation-contract.md), without the existing graph, prior annotations or expected classifications. Each annotated all 152 in-scope main-table endpoint cells and separately inspected supporting prose and the available Myers supplement. Their initial drafts contain 304 and 333 observations respectively. The difference is largely supplemental/prose coverage, which cannot be assessed by matching main-table coordinates alone.

They agree on 145 of 152 complete measurement objects and 133 of 152 comparator objects. These counts include formatting and metadata differences. They are annotation agreement, not model accuracy. The third fresh-context AI adjudicator audits agreed and disputed fields against the source, reconciles additional records and preserves unresolved conflicts. The process uses context isolation and explicit file-access instructions, not an operating-system sandbox. Shared model priors can still produce correlated errors; human expert review remains pending.

The v2 contract retains raw source text, central estimates, inequality bounds, confidence intervals, uncertainty type, sample counts, comparator measurements and named experimental conditions. It is separate from the earlier scalar benchmark contract; the old scorer has not silently gained interval-aware scoring. These seven exposed development papers are not a held-out test set.

## What the viewer does

The left panel groups variants by source-reported functional category. A core member requires an explicit primary-source `Likely LoF` classification and a quantitative intrinsic-function observation with an eligible WT comparison. Possible LoF remains provisional. Opposing and unresolved variants remain visible as controls. Conflicting primary functional categories remain unresolved.

The main panel separates measured receptor function, calculated functional summaries, pharmacology and secondary summaries. Every source record retains its original experimental context. Counts represent annotated records, not independent experiments: a later paper may reuse an earlier measurement while contributing its own classification analysis.

Descriptive ratios use WT EC50 / variant EC50 for glutamate and glycine potency, and variant / matched WT for other eligible intrinsic endpoints. They are neither aggregate functional scores nor tests of statistical significance. Censored values, missing comparators, incompatible units and nonpositive denominators do not yield point ratios. Confidence intervals remain attached to their measurements; ratio uncertainty is not propagated.

Each source button opens the exact saved evidence spans, experimental conditions and paper link. Source hashes must match at server startup. Table coordinates, raw cell text and full-cell citations are checked against the source ledger before building the cluster. Supplemental/prose records have exact text offsets but do not invent main-table coordinates.

## Rebuild and run

The quotation-heavy annotations, reviewer drafts, source snapshots, visual audits and reproducible annotation builders remain in the ignored local directory `data/processed/benchmarks/grin-cluster-annotation-v2/`. The committed cluster bundle stores measurement metadata and source coordinates without reproducing full source quotations. A fresh checkout needs the matching local source snapshot to display evidence quotes.

```bash
.venv/bin/python -m atlas.cluster_demo build \
  --reference data/processed/benchmarks/grin-cluster-annotation-v2/adjudicator/adjudicated-reference.json \
  --sources data/processed/benchmarks/grin-development-v1/sources.json \
  --curated data/curated/grin_functional_evidence.json \
  --ledger data/processed/benchmarks/grin-development-v1/source-ledger.json \
  --output data/curated/grin_cluster_demo_v2.json

.venv/bin/python -m atlas.cluster_demo serve --port 18769
```

Open <http://127.0.0.1:18769/>. The existing TopK literature-search pilot remains available through the viewer's search link. This new source-audited bundle is separate from the earlier TopK-indexed curated bundle; it has not been silently uploaded or substituted into the search collection.

## Coverage limits

The scope is the existing ten selected protein variants across seven papers, including functionally opposing and unresolved controls. It is not every GRIN variant in those papers or the entire harvested literature corpus. Main tables, available text and the Myers supplement are covered within that scope. Other unavailable supplements, unquantified figures, transcript/allele identity conflicts and ambiguous protocols remain in the coverage and issue records. Protein/construct identity is not equivalent to a fully normalized genomic allele.

Source disagreements remain visible, including conflicting Myers supplemental charge-transfer values. No source value is corrected merely because it appears biologically implausible. A source-reported label also remains distinguishable from an independently verified biological conclusion.

# GRIN cluster annotation contract

This development format preserves measurements, intervals, censoring and receptor context for the ten-variant demonstration. It is separate from the scalar benchmark v1 and must not be silently scored as that format.

Annotate all main-table quantitative endpoints for the selected variants across the seven supplied papers, including calculated charge transfer and pharmacology. Review source prose and available supplemental pages for author-reported functional classifications, identity conflicts and experimental context. Include qualitative/missing endpoints in the coverage ledger. Do not infer an integrated functional class from a single measurement. Do not count a secondary summary as a new experiment.

Selected identities, with no assigned functional labels: GRIN2A p.Gly483Arg, p.Ala716Thr, p.Asp731Asn; GRIN2B p.Glu413Gly, p.Ser541Arg, p.Pro553Thr, p.Cys461Phe, p.Ser541Gly, p.Ala639Val, p.Arg540His. Normalize short and long protein notation but never guess a gene from a residue alone.

## File format

`annotations.json` is an object with exactly these keys:

- `schema_version`: `grin-cluster-annotations-v2`
- `reviewer`: AI reviewer identifier
- `review_type`: `independent_ai_draft` or `source_audited_ai_reference`
- `expert_reviewed`: false
- `sources_sha256`: canonical digest of the entire supplied sources.json
- `observations`: list of observation objects below
- `claims`: list of source-reported claims below
- `coverage`: one entry per source document with document_id, status, scope, omissions, and reviewed_tables (table IDs). A narrower scope or missing supplemental/visual content must be explicit.
- `issues`: a list of unresolved source/annotation issues, each with document_id, gene (nullable), protein (nullable), description and evidence.

All exact evidence spans use `{unit_id,start,end,quote}` with Python Unicode offsets into the saved source unit. An image-only cell may lack a source text unit: log its table ID, row, column and asset URL as an omission; never invent a quote or value. Do not use existing graph labels or other reviewers' files.

## Observation object

Required keys: `id`, `document_id`, `gene`, `protein`, `table_id`, `row`, `column`, `endpoint`, `assay`, `measurement_type`, `sequence_context`, `conditions`, `measurement`, `comparator`, `evidence`.

- `id` is unique within the file. `protein` uses p. and three-letter amino acids.
- `table_id` uses the supplied ledger; row/column are the ledger's one-based logical coordinates. For a prose observation, all three are null.
- `endpoint` uses stable snake_case names. Prefer glutamate_ec50, glycine_ec50, magnesium_ic50, zinc_ic50, proton_response_ratio, open_probability, weighted_deactivation_tau, steady_state_peak_ratio, peak_current_density, surface_total_ratio, synaptic_charge_transfer, nonsynaptic_charge_transfer. Drug endpoints include the agent: e.g. memantine_ic50, ketamine_inhibition, d_serine_ec50, pregnenolone_sulfate_potentiation.
- `assay` is a concise source-backed string; use two_electrode_voltage_clamp, whole_cell_voltage_clamp, surface_expression, author_calculation where supported.
- `measurement_type` is measured, author_calculated, or secondary_summary. Fitted EC50 is a measured assay endpoint; modeled charge transfer is author_calculated.
- `sequence_context` is a source-reported accession/version or null. An unversioned construct accession is not a verified genomic allele mapping.
- `conditions` has exactly receptor, system, protocol. Receptor and system are strings/null. Protocol is an object mapping named experimental conditions to source-backed strings/null, not free narrative. Preserve unknowns and do not generalize figure-specific concentrations. Distinguish diheteromeric, triheteromeric, species, mutant-copy context and treatment conditions.
- `comparator` has exactly label, measurement, evidence. Label is string/null; measurement is the same measurement object below or null; evidence is a span list. Match the actual experiment/construct WT, not the nearest convenient WT row. Within-construct treatment controls remain distinct from WT comparisons.
- `evidence` must include the measured cell, variant identity, header/units and required methods/footnotes. Include source spans backing inferred gene/construct links.

## Measurement object

Exact keys: raw, estimate, relation, unit, uncertainty_type, uncertainty_value, ci_lower, ci_upper, n, n_unit, qualitative.

- `raw` preserves the reported text including markers.
- `estimate`, `uncertainty_value`, `ci_lower`, `ci_upper` are decimal strings or null. Remove thousands separators; convert explicit scientific notation faithfully. Do not estimate values from a graphic.
- `relation`: eq, lt, le, gt, ge, range, qualitative, not_reported. A threshold value with relation gt is never treated as an exact estimate for a ratio.
- `unit` is a string/null. Normalize μM to µM; preserve percent versus fraction and mixed table units.
- `uncertainty_type`: SEM, SD, 95%CI, unspecified or null, as actually supported. Do not extend figure-specific SEM to a table.
- `n` is a positive integer/null and `n_unit` a string/null. Do not infer what n counts from the expression system.
- `qualitative` is a string/null for literal qualitative statements. Not-reported cells can be included as records with null estimate and relation not_reported so row coverage is visible.

## Source-reported claim object

Exact keys: id, document_id, gene, protein, predicate, statement, category, evidence_type, evidence.

- `predicate`: author_functional_classification, reported_functional_effect, identity_conflict.
- `category`: Likely LoF, Possible LoF, Likely GoF, Possible GoF, GoF, LoF, No effect, Indeterminant, or null. Use only a category explicitly stated by the source for that variant; retain qualifications in statement. Source spelling Indeterminant is retained.
- `evidence_type`: primary_report or secondary_summary.
- `statement` is a source-faithful paraphrase, not a new classification.
- `evidence` contains exact source spans. If a class appears only in an untranscribed image, retain an omission, not a category. The supplied Myers PDF may be rendered locally and inspected visually; a visual-only reading requires a separate page/region audit and must not be disguised as an exact text quote.

Retain conflicting findings, missingness, uncertainty and secondary provenance. Claims do not automatically change cluster membership. No expert review or clinical recommendation is implied.

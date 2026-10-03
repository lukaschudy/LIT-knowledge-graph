# GRIN real-data demonstration

This reproducible pilot connects **selected GRIN2A and GRIN2B variants with published receptor-function evidence** to an existing registry, assay service and a research discussion brief. It uses real literature and public resource descriptions. Scientific interpretation and participant eligibility remain subject to expert review.

## Data and cluster

The curated set has ten protein substitutions: six core variants classified as Likely LoF by the published framework, one provisional Possible LoF case, two opposing-function controls and one unresolved control. The transparent inclusion gate requires primary assay data with a wild-type comparator and the reported integrated classification. Clinical pathogenicity alone never qualifies a variant.

Core variants:

| Gene | Selected protein substitutions |
|---|---|
| GRIN2A | p.Gly483Arg, p.Ala716Thr, p.Asp731Asn |
| GRIN2B | p.Glu413Gly, p.Ser541Arg, p.Pro553Thr |

GRIN2B p.Cys461Phe remains provisional. p.Ser541Gly and p.Ala639Val are opposing controls; p.Arg540His remains unresolved. One low assay result does not decide net functional direction. For example, the opposing controls retain reduced current or expression measurements alongside the other measurements and source interpretation.

This is a source-defined research cohort, not an unsupervised discovery or a new disease classification. The 57 source-specific assay-feature rows preserve units, sample sizes, WT controls and uncertainty notation. Derived ratios use central values only, remain separate by study, and leave missing or censored observations uncomputed. Do not pool them as independent observations or interpret ratios as clinical effect sizes.

## Reproduce

Run from the repository root with the Atlas framework available:

```bash
python3 -m harvest.grin_cluster
python3 -m harvest.grin_identity
python3 -m harvest.grin_bundle
python3 -m harvest.grin_brief
python3 -m unittest tests_harvest.test_grin_cluster tests_harvest.test_grin_bundle
python3 -m atlas ingest data/curated/grin_atlas_bundle.json --db data/grin-demo.sqlite
python3 -m atlas serve --db data/grin-demo.sqlite --port 18766
```

Use `--replace` only when intentionally refreshing this demo database. Restart its server after ingesting a changed bundle. The default/synthetic demo database is separate.

## Browser walkthrough

1. Open <http://127.0.0.1:18766> and search **GRIN2B**.
2. Select **GRIN2B-related neurodevelopmental disorder — selected Likely LoF variants**.
3. Inspect the GRIN2A connection and select a biological relationship to see primary source links, exact locators and measurements.
4. Check that provisional and unresolved cases say **Needs review**, while the opposing-function cohort says **Not supported** for this particular route.
5. Open **Research assets** and inspect the registry, maintainer organizations, data-sharing conditions and unanswered availability questions.
6. Review `data/curated/grin_research_proposal.json` for the concrete observational research question, partner routes and proposed feasibility milestone.

The bundle contains 35 entities, 12 cited sources, 44 claims and 56 evidence records. Reported source claims and proposed asset adaptation are distinguished. “Machine checked” describes source transcription, not expert clinical validation. The graph acknowledges the already-established cross-gene GRIN relationship and registry; its contribution is traceable preparation of a research question.

## Files and limitations

- `data/curated/grin_functional_evidence.json`: primary assay evidence and author classifications.
- `data/curated/grin_cluster.json` and `grin_assay_features.csv`: membership gate and source-specific numerical features.
- `data/curated/grin_identity_candidates.json`: candidates from the complete acquired ClinVar summary, with no automatic DNA-allele merges.
- `data/curated/grin_atlas_bundle.json`: normalized Atlas graph.
- `data/curated/grin_research_proposal.json`: discussion draft; nothing has been sent to research teams.
- `data/curated/grin_demo_validation.json`: graph behavior and bundle checksum.
- `docs/grin-evidence-notes.md`: primary references, source errors and interpretation limits.

The publication's S541G cDNA/protein inconsistency is preserved and flagged. P553T has no exact protein-name match in the acquired ClinVar summary. Transcript identities require independent reconciliation before enrolling people. No patient-level registry data or samples have been acquired. This is a selected demonstration rather than a comprehensive extraction of every published GRIN functional variant. Expert review, outcome-instrument access and any claim of faster research remain outstanding.

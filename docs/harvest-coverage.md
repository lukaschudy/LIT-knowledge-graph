# Harvest coverage and GRIN demonstration

Snapshot: 2026-10-03T23:45:48.439555+00:00.

This report describes acquired source snapshots and recorded query results. It does not claim that every source is accessible, that a search retrieves all relevant research, or that source records are expert-validated biological conclusions. Large acquired files remain in the local workspace; Git contains code, checksummed manifests and small curated demo artifacts.

## Collection

The manifests currently describe **21,746,825 normalized records** across **40 acquisition/reference collections**, with 23.47 GiB of registered raw artifacts and 3.98 GiB of compressed normalized data. These totals mix entities, annotations, assertions, ontology stanzas, repeated source representations and query memberships. They are not counts of distinct patients, diseases or biological facts.

All 21 source entries in the original PDF are accounted for below. “Complete” always refers to the manifest’s declared file or query scope. “Permission required” and other gaps are explicit; no private registry or patient-level data was acquired.

| PDF ID | Source named in PDF | Acquisition status |
|---|---|---|
| S01 | OMIM | omim: permission_required |
| S02 | ClinVar | clinvar: complete |
| S03 | HPO | hpo: complete |
| S04 | PubMed | pubmed: complete; europe_pmc_diseases: complete_for_scope; grin_literature: complete |
| S05 | PubMed Central (PMC) | pmc_grin_oa: partial_fulltext_retrieval |
| S06 | ClinicalTrials.gov | clinicaltrials_gov: complete_with_fallbacks |
| S07 | NIH RePORTER | nih_reporter: complete |
| S08 | NORD | nord: permission_required |
| S09 | Global Genes | global_genes: permission_required |
| S10 | Orphanet / Orphadata | orphadata: complete; orphanet_expert_resources: permission_required |
| S11 | Verified patient-group / patient-org websites | grin_resources: complete_for_scope |
| S12 | EURORDIS | eurordis: access_blocked |
| S13 | Rare Disease UK | genetic_alliance_uk: complete_for_scope |
| S14 | Genetic Alliance (US) | genetic_alliance_us: provider_export_needed |
| S15 | MONDO | mondo: complete |
| S16 | Press releases | grin_resources: complete_for_scope |
| S17 | Jackson Laboratory | mgi: complete_for_scope |
| S18 | RareConnect | rareconnect: retired_metadata_only |
| S19 | bioRxiv | europe_pmc_preprints: complete |
| S20 | medRxiv | europe_pmc_preprints: complete |
| S21 | RARe-SOURCE | raresource: complete_for_scope |

## Source datasets

| Collection | Status | Normalized records | Manifest |
|---|---|---:|---|
| clingen | complete | 11,338 | [scope, provenance and gaps](../data/harvest-manifests/clingen.json) |
| clinicaltrials_gov | complete_with_fallbacks | 89,770 | [scope, provenance and gaps](../data/harvest-manifests/clinicaltrials_gov.json) |
| clinvar | complete | 9,237,191 | [scope, provenance and gaps](../data/harvest-manifests/clinvar.json) |
| crossref_grin | complete_for_scope | 7 | [scope, provenance and gaps](../data/harvest-manifests/crossref_grin.json) |
| europe_pmc_diseases | complete_for_scope | 4,718,225 | [scope, provenance and gaps](../data/harvest-manifests/europe_pmc_diseases.json) |
| europe_pmc_preprints | complete | 2,579 | [scope, provenance and gaps](../data/harvest-manifests/europe_pmc_preprints.json) |
| europe_pmc_recheck | complete_for_scope | 465,071 | [scope, provenance and gaps](../data/harvest-manifests/europe_pmc_recheck.json) |
| eurordis | access_blocked | 0 | [scope, provenance and gaps](../data/harvest-manifests/eurordis.json) |
| gencc | complete | 30,328 | [scope, provenance and gaps](../data/harvest-manifests/gencc.json) |
| genetic_alliance_uk | complete_for_scope | 260 | [scope, provenance and gaps](../data/harvest-manifests/genetic_alliance_uk.json) |
| genetic_alliance_us | provider_export_needed | 0 | [scope, provenance and gaps](../data/harvest-manifests/genetic_alliance_us.json) |
| global_genes | permission_required | 0 | [scope, provenance and gaps](../data/harvest-manifests/global_genes.json) |
| go | complete | 954,790 | [scope, provenance and gaps](../data/harvest-manifests/go.json) |
| grants_gov | partial | 786 | [scope, provenance and gaps](../data/harvest-manifests/grants_gov.json) |
| grin_clinvar | complete_for_scope | 4,397 | [scope, provenance and gaps](../data/harvest-manifests/grin_clinvar.json) |
| grin_literature | complete | 7,775 | [scope, provenance and gaps](../data/harvest-manifests/grin_literature.json) |
| grin_primary | partial | 0 | [scope, provenance and gaps](../data/harvest-manifests/grin_primary.json) |
| grin_primary_pages | complete_for_scope | 0 | [scope, provenance and gaps](../data/harvest-manifests/grin_primary_pages.json) |
| grin_primary_tables | complete_for_scope | 687 | [scope, provenance and gaps](../data/harvest-manifests/grin_primary_tables.json) |
| grin_primary_xml | partial | 0 | [scope, provenance and gaps](../data/harvest-manifests/grin_primary_xml.json) |
| grin_reference | complete_for_scope | 9,749 | [scope, provenance and gaps](../data/harvest-manifests/grin_reference.json) |
| grin_resources | complete_for_scope | 7 | [scope, provenance and gaps](../data/harvest-manifests/grin_resources.json) |
| grin_supplements | complete_for_scope | 9 | [scope, provenance and gaps](../data/harvest-manifests/grin_supplements.json) |
| hgnc | complete | 50,478 | [scope, provenance and gaps](../data/harvest-manifests/hgnc.json) |
| hpo | complete | 657,216 | [scope, provenance and gaps](../data/harvest-manifests/hpo.json) |
| mgi | complete_for_scope | 759,112 | [scope, provenance and gaps](../data/harvest-manifests/mgi.json) |
| mondo | complete | 535,846 | [scope, provenance and gaps](../data/harvest-manifests/mondo.json) |
| nih_reporter | complete | 44,086 | [scope, provenance and gaps](../data/harvest-manifests/nih_reporter.json) |
| nord | permission_required | 0 | [scope, provenance and gaps](../data/harvest-manifests/nord.json) |
| omim | permission_required | 0 | [scope, provenance and gaps](../data/harvest-manifests/omim.json) |
| open_targets | partial | 2,864,271 | [scope, provenance and gaps](../data/harvest-manifests/open_targets.json) |
| orphadata | complete | 83,026 | [scope, provenance and gaps](../data/harvest-manifests/orphadata.json) |
| orphanet_expert_resources | permission_required | 0 | [scope, provenance and gaps](../data/harvest-manifests/orphanet_expert_resources.json) |
| pmc_grin_oa | partial_fulltext_retrieval | 1,907 | [scope, provenance and gaps](../data/harvest-manifests/pmc_grin_oa.json) |
| pubmed | complete | 54,131 | [scope, provenance and gaps](../data/harvest-manifests/pubmed.json) |
| rareconnect | retired_metadata_only | 0 | [scope, provenance and gaps](../data/harvest-manifests/rareconnect.json) |
| raresource | complete_for_scope | 11,712 | [scope, provenance and gaps](../data/harvest-manifests/raresource.json) |
| reactome | complete | 990,112 | [scope, provenance and gaps](../data/harvest-manifests/reactome.json) |
| ror | complete | 141,528 | [scope, provenance and gaps](../data/harvest-manifests/ror.json) |
| uniprot | complete | 20,431 | [scope, provenance and gaps](../data/harvest-manifests/uniprot.json) |

## Reconciled coverage

- Literature: **2,122,515 distinct article metadata records**, with **2,557,876 query memberships** across 424 completed query batches. Article records are not all full-text copies.
- Open Targets: **2,844,448 distinct disease–target pairs**, 0 duplicate rows and 0 provider-count mismatches for returned diseases. The 1,342 input MONDO IDs that the provider did not resolve remain explicit gaps.
- Focused PMC retrieval: **355 verified full-text articles** (329 JATS and 26 HTML). 18 license-eligible targets remain unavailable; 283 further targets remain in rights or metadata review queues.
- Raw-only reference collections can have zero normalized records in the table while still containing acquired files; the seven primary GRIN article HTML snapshots are one example. Their artifacts and checksums are recorded in their manifests.

## Scope and interpretation

- ClinVar covers the acquired full variant summary and gene-condition release; full VCV archives are additionally acquired for the single-gene GRIN2A/GRIN2B subset. It is not a global VCV full-XML download.
- The Europe PMC disease search uses every preferred name from the 7,200-disease vocabulary plus qualifying multiword aliases. The generic alias “the syndrome” is retained in the vocabulary but excluded from query execution; its superseded raw snapshots and quality correction are recorded. Results preserve article metadata and available abstracts; a vocabulary hit is a retrieval candidate, not an asserted disease association. PubMed generic and focused GRIN searches are retained separately.
- The focused full-text queue is a declared relevance slice of GRIN citations with primary PMC identifiers. Article-specific license metadata, unsupported rights, unresolved records and failed retrievals are distinguished. Full-text acquisition is not complete merely because metadata exists.
- ClinicalTrials.gov includes generic searches and disease-name expansion; 12 difficult name expressions use explicitly labeled broader fallback searches. Membership does not establish that a study concerns the specific named disease. NIH RePORTER uses recorded fiscal-year/query partitions. Trials, awards and proposed research do not establish efficacy.
- Open Targets is a mapped rare-disease slice, with identifiers not resolved by the API retained as gaps. Aggregate associations and full underlying evidence are distinct datasets; only the focused GRIN disease set has its underlying source-native evidence harvested here.
- MGI reports retain species, alleles, stock references and negated model assertions. A disease-level list of mouse genotypes does not identify a model of a particular human GRIN variant. Generic record rows and gene-level facilities require separate suitability checks.
- Patient-organization, press-release and model resource categories in the PDF are represented by declared structured reports and a bounded GRIN resource slice, not every organization on the internet. Indexed preprints are not complete dumps of the preprint servers.
- OMIM, NORD, Global Genes and Orphanet expert resources require access or permission for the intended collection. EURORDIS access was blocked, Genetic Alliance US needs an export, and RareConnect is retained as retired-service metadata.

## GRIN reduced-function demonstration

The selected core contains GRIN2A G483R, A716T and D731N, and GRIN2B E413G, S541R and P553T. They have published Likely LoF classifications and linked primary assay measurements with study-specific wild-type comparators. C461F remains provisional; S541G and A639V are opposing controls; R540H remains unresolved. All scientific interpretation remains pending expert review.

The graph has 35 entities, 12 sources, 44 claims and 56 evidence records. The feature table preserves 57 study-specific assay rows without imputing missing measurements. An independently source-linked review queue includes 39 published variants and 14 newly assayed candidates from Myers 2023; it does not automatically admit them to the cohort.

The demo supports a concrete research-preparation task: inspect cross-gene functional evidence, distinguish provisional/opposing cases, identify the published registry and assay-service routes, and review a feasibility brief for shared observational measures. It does not solve the disorders, recommend a treatment, confirm participant eligibility or claim that any resource has agreed to collaborate.

[Open local demo](http://127.0.0.1:18766/records) · [Reproduce the demo](grin-demo.md) · [Evidence and corrections](grin-evidence-notes.md) · [Research discussion brief](../data/curated/grin_research_proposal.json) · [Variant review queue](../data/curated/grin_functional_review_queue.json)

## Quality controls

The downloader checks response bytes, SHA-256 and resumable-download validators. Normalization preserves native fields, identifiers, negation and source attribution. Pagination audits compare provider counts, raw rows and distinct IDs; discrepancies remain explicit. Primary PubMed IDs are scoped to the article rather than accidentally extracted from its reference list. The GRIN table parser preserves image references and flags untranscribed values instead of representing image-only results as absent data.

Last [integrity audit](../data/harvest-audit.json): 2026-10-03T23:44:05.986607+00:00; 0 errors; deep record scan: True.

Run `python3 -m unittest discover -s tests_harvest -q`, then `python3 -m harvest.audit`, `python3 -m harvest.status` and `python3 -m harvest.report` after acquisitions finish.

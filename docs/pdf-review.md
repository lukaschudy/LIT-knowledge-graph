# PDF review and source coverage

Reviewed 2026-10-03. Input: `Knowledge graph`, a six-page PDF, 444,530 bytes, titled **AI Atlas for the World’s Rare Diseases — Challenge Brief**, author Hack-Nation. SHA-256: `9c502bdfcc0d5c400c11dd7a78bd9fc3c4b4f07529a973e076d109e28605d67e`.

## What the brief asks for

The atlas connects diseases, genes, variants, mechanisms, phenotypes, organizations, publications, studies, and reusable research assets. A family or patient-group leader should follow an explained route from a diagnosis to related research, a usable asset, a collaborator, and a practical next step. The key is evidence for each connection, including contradictions and missing evidence—not merely joining records with similar names.

| PDF page | Content reviewed | Consequence for extraction |
|---|---|---|
| 1 | Challenge title and sponsorship | Context, not an independent biomedical data source |
| 2 | Motivation, monogenic disease and mechanism/phenotype framing; RARe-SOURCE example | Preserve mechanism and variant specificity; include RARe-SOURCE even though it is absent from the later source table |
| 3 | Maria, Devon, Priya, Dr. Osei; graph-builder edges | Support public organizations, research assets, investigators and evidence-qualified relationships |
| 4 | Trial, funding and community edges; trustworthy/actionable network | Separate observation from inference; record contradictions; map registries and models to their scope |
| 5 | UI expectations, 24-hour ambition, AI extraction and full source table | Begin with one well-supported disease cluster, then expand; inventory all named sources and generic source classes |
| 6 | Submission/evaluation criteria | Reproducibility, evidence integrity, meaningful research progress and explicit gaps |

## Exhaustive inventory

Each row must have a corresponding numbered section in the extraction guide. PubMed and PMC are separate because metadata, full text, and reuse differ. Generic websites and press releases are separate workflows. RARe-SOURCE is a contextual source, not an explicit ingestion requirement in the table, but is included for completeness.

| ID | Source as mentioned | PDF pages | Role |
|---|---|---|---|
| S01 | OMIM | 3, 5 | Gene–disease and variant/mechanism evidence |
| S02 | ClinVar | 3, 5 | Variant interpretations |
| S03 | HPO | 3, 5 | Phenotype ontology and disease annotations |
| S04 | PubMed | 3, 5 | Publications, claims, investigators |
| S05 | PMC | 3, 5 | Full-text literature, where available and reusable |
| S06 | ClinicalTrials.gov | 4, 5 | Studies, conditions, interventions and assets |
| S07 | NIH RePORTER | 4, 5 | Funding, researchers and projects |
| S08 | NORD | 4, 5 | Patient-group directory |
| S09 | Global Genes | 4, 5 | Patient-group directory |
| S10 | Orphanet | 4, 5 | Disease terminology, biology and organizations |
| S11 | Verified patient-group / patient-org websites | 4, 5 | Communities, registries, assets and contacts |
| S12 | EURORDIS | 5 | Patient-group directory |
| S13 | Rare Disease UK | 5 | UK community network |
| S14 | Genetic Alliance | 5 | Ambiguous US/UK name; resolve both, avoid conflation |
| S15 | MONDO | 5 | Disease identifiers, synonyms and mappings |
| S16 | Press releases | 5 | Asset/program announcements, requiring corroboration |
| S17 | Jackson Laboratory | 5 | Experimental models and model availability |
| S18 | RareConnect | 5 | Community discovery; verify operational status |
| S19 | bioRxiv | 5 | Biology preprints |
| S20 | medRxiv | 5 | Medical preprints |
| S21 | RARe-SOURCE | 2 | Integrated NIH resource and comparison/reference source |

The brief also mentions unnamed registries, natural-history studies, models, biomarkers, conference talks, clinical observations, RFAs, investors/funders, and patient contributions. These are data/asset classes, not uniquely identifiable providers. The additional-source plan addresses them. OpenAI, Buffalo Initiative, Hack-Nation and NIH as umbrella institutions are contextual names; their names alone do not imply a biomedical dataset to ingest. OpenAI is also a suggested processing tool.

## Scope of this research task

The requested deliverable is a researched acquisition plan in Markdown, extra source recommendations, frequent commits and a GitHub repository. The PDF's prototype, deployment and video requirements describe a subsequent hackathon build; they are not implemented by this planning task.

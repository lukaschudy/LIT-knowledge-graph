# Additional sources for the knowledge graph

Research checked 2026-10-03. These are proposed additions, separate from the 21 PDF sources. Priorities and ingestion cadence are design recommendations. Unless explicitly marked as a sample probe, access is documentation-reviewed rather than connector-tested. These sources should fill an identified gap, not merely make the graph larger.

## What the brief's source list leaves missing

HPO and MONDO normalize phenotypes and diseases, but the initial list lacks a dedicated human gene identity spine, a well-defined pathway/reaction source, strong gene–disease validity/dosage curation, reliable researcher/institution identifiers, and a forward-looking funding-opportunity source. It also gives limited structured coverage of human cell models and registry data dictionaries. Those gaps directly affect whether a family can find a defensible connection and an existing asset.

| Priority | Additions | What they enable |
|---|---|---|
| P0: first cluster | HGNC; Reactome; ClinGen; GenCC | Resolve genes; represent pathways and evidence strength; compare conflicting gene–disease assertions |
| P1: strengthen explanation and action | UniProt; GO; ORCID; ROR; RDCRN; TREAT-NMD | Protein functions, evidence-qualified processes, collaborators, institutions, clinical networks and reusable registry standards |
| P2: broaden discovery | Europe PMC; Crossref; Open Targets; Grants.gov; Coriell; BioStudies | Literature links/status, target evidence, upcoming funding, human models and reusable datasets |

## A01 — HGNC: human gene identity (P0)

**Acquire:** Use the [HGNC complete dataset and withdrawn-symbol downloads](https://www.genenames.org/download/statistics-and-files/) in TSV or JSON; pin a dated archive rather than downloading only a mutable latest file. Its [download help](https://www.genenames.org/help/statistics-and-downloads/) explains fields. Preserve HGNC ID, approved symbol, aliases, previous symbols, status, NCBI Gene, Ensembl and UniProt cross-references. Refresh monthly for the prototype.

**Graph value:** A canonical `HGNC:n` gene key makes OMIM, ClinVar, HPO, RePORTER and literature joins less error-prone. Treat symbols as names with history, not permanent identities. Alias collisions need review; do not merge two genes simply because an old symbol matches. The download page states no restrictions on data access/use; retain provenance regardless. Documentation checked; no HGNC data download probe was run.

## A02 — Reactome: pathways and reactions (P0)

**Acquire:** The [official downloads](https://reactome.org/download-data) provide pathway data and mapping files, with versioned releases and a Content Service API. Import human pathways and their gene/protein membership; retain stable `R-HSA-…` identifiers, hierarchy, reaction context and evidence references. For a focused lookup use the documented [Content Service](https://reactome.org/ContentService/); for bulk use pinned download files. Retain [Reactome license](https://reactome.org/license) and attribution with the selected files.

**Graph value:** `Protein PARTICIPATES_IN Reaction/Pathway` provides an explicit bridge across diseases. Preserve whether annotation is curated or computationally inferred and the organism. Pathway overlap generates a testable candidate, not proof that the same therapy or direction of intervention applies. Proposed update: each provider release. This is one of the most valuable additions because the challenge's central “mechanism” edge is otherwise underspecified.

## A03 — ClinGen: validity and dosage sensitivity (P0)

**Acquire:** [ClinGen File Downloads & APIs](https://search.clinicalgenome.org/kb/downloads) publishes CSV summaries for gene–disease validity and dosage sensitivity, plus links to detailed reports. Use those exports; save HGNC/MONDO identifiers, inheritance, classification, panel, report/evidence URL and evaluation date. Import dosage regions as regions, not fake gene nodes. Check the selected resource's terms before distribution. Proposed refresh: monthly snapshot plus diff.

**Graph value:** Separate `GeneDiseaseAssertion` and `DosageAssertion` objects support strong/limited/disputed/refuted evidence and loss/gain dosage distinctions. Preserve panel-specific disagreements and human-versus-model evidence. [ClinGen's classification guidance](https://www.clinicalgenome.org/docs/gene-disease-validity-classification-information/) describes evidence strength and an animal-model-only designation. Dosage sensitivity is not the complete mechanism of every sequence variant. This is enrichment, not a license to infer clinical conclusions automatically.

## A04 — GenCC: cross-provider gene–disease assertions (P0)

**Acquire:** [GenCC downloads](https://pub.clinicalgenome.org/download) offer CSV/TSV/XLS/XLSX assertions with gene, disease, inheritance, submitter and evidence links under CC0. The checked page describes its API as forthcoming; use the available files rather than designing against an assumed API. Its export excludes OMIM data because of licensing. Pin each download and proposed monthly refresh.

**Graph value:** Compare submitted classifications across contributors and retain submitter-specific assertions. Link to HGNC/MONDO where the file supplies them. Avoid double counting a ClinGen assertion once through ClinGen and again through GenCC: record upstream origin and curation identity. GenCC can provide useful open assertions while OMIM access is being resolved, but it is not a complete OMIM replacement.

## A05 — UniProt: protein functions and variant context (P1)

**Acquire:** Use the UniProt REST interface or release downloads, starting with reviewed human records for the seed genes. The [API documentation](https://www.uniprot.org/api-documentation/support-data) describes access and CC BY 4.0 licensing. A small live [STXBP1 query](https://rest.uniprot.org/uniprotkb/search?query=gene_exact%3ASTXBP1%20AND%20organism_id%3A9606&format=json&size=1) returned accession `P61764`; evidence is in [asset-probes.json](research/asset-probes.json). This confirms one query, not completeness of the gene's isoforms or variants.

**Graph value:** Store accession, isoforms, gene crossrefs, function annotations, features, subcellular locations and cited evidence. Connect gene → protein → function/pathway, maintaining isoform and species. Distinguish reviewed annotations from predictions. Refresh by provider release; reconcile secondary/deleted accessions. Protein annotations do not prove the effect of every patient variant. Do not substitute a returned first result for an exhaustive isoform-aware lookup.

## A06 — Gene Ontology (GO): functions/processes with evidence (P1)

**Acquire:** Import a pinned [GO ontology](https://www.geneontology.org/page/download-ontology) and human [annotation files](https://www.geneontology.org/page/downloads) in GAF/GPAD as appropriate. Retain GO IDs, gene-product identifiers, relation/qualifier, evidence code, reference, taxon, date and assigned-by. The [evidence-code guide](https://www.geneontology.org/docs/guide-go-evidence-codes/) explains how experimental evidence differs from other evidence types. Inspect the license carried by the specific ontology/annotation release. Proposed refresh: monthly.

**Graph value:** `GeneProduct INVOLVED_IN BiologicalProcess` and `HAS_FUNCTION MolecularFunction` can expose related research. Preserve `NOT` and relation semantics; ancestors are inferred, not fresh independent observations. Do not give broad process terms the same clustering weight as precise phenotypes/mechanisms. Avoid counting UniProt-derived GO assertions twice when also importing UniProt.

## A07 — ORCID: researcher identity (P1)

**Acquire:** The [ORCID Public API](https://info.orcid.org/documentation/features/public-api/) supports reading/searching public records; use registered client credentials and the applicable API terms. The public data file is an alternative for bulk planning. Do not assume public API service terms and bulk-data licensing are identical. Store ORCID iD, work identifiers and public affiliation history; ingest no private fields. Prefer an ORCID already supplied by a paper or researcher rather than broad name matching.

**Graph value:** Helps distinguish investigators who share a name and connect publications/projects across institutions. ORCID records may be incomplete or self-maintained; absence of a work is not evidence against authorship. Proposed refresh: monthly for the small linked set. Public contact does not authorize automated outreach. No authenticated API request was made in this task.

## A08 — ROR: institution/funder identity (P1)

**Acquire:** [ROR's data dump](https://ror.readme.io/docs/data-dump) is available as versioned JSON under CC0. JSON preserves full structure; CSV is a flattened subset. Use the current schema, record status, names/aliases, locations and successor relationships. The current documentation says the bulk dump includes inactive/withdrawn records while the API defaults to active records. Refresh by release.

**Graph value:** Connect labs, institutions and grants with stable ROR IDs. Do not mistake institutions, their departments and hospitals for identical entities without a source-backed relationship. Keep author affiliation as it was at the time of publication. Patient organizations may not all have ROR IDs; use local IDs for those and avoid forcing a match.

## A09 — RDCRN: research consortia and patient partners (P1)

**Acquire:** The [Rare Diseases Clinical Research Network](https://www.rarediseasesnetwork.org/) links disease coverage, studies, consortia and patient advocacy partners. Curate public consortium/study/partner pages for the seed cluster; no public bulk API was established here. Capture study IDs, consortium name, participating institutions, disease scope and source URLs, and verify NCT links against ClinicalTrials.gov.

**Graph value:** These links are closer to actual collaboration infrastructure than author co-occurrence alone. Keep `PARTNER_OF`, `MEMBER_OF`, `STUDIES` and `OPERATES` separate. A public “contact registry” entry point does not expose participant data. Respect website terms; seek an export agreement before bulk reuse. Proposed refresh: monthly and before presenting a current collaboration lead. Network membership does not establish a study's enrollment eligibility.

## A10 — TREAT-NMD: registry network and data dictionaries (P1, neuromuscular clusters)

**Acquire:** [TREAT-NMD core datasets](https://www.treat-nmd.org/what-we-do/core-datasets/) describe disease-specific minimum datasets and linked materials. Extract public dataset versions, variable definitions, units/coding and covered condition, retaining the exact document source and rights statement. Consult network pages for registry metadata; participant-level data requires its own governed access and is outside this plan.

**Graph value:** `Registry USES DataDictionary`, `DataDictionary DEFINES Variable` makes “reusable infrastructure” concrete. Record instrument version, language, unit and measurement timing before proposing compatibility. The network comprises independent registries; it is not itself one freely downloadable patient registry. Proposed refresh: when dataset versions change; quarterly link/status checks. Standards can support harmonization but do not make two disease cohorts scientifically interchangeable.

## A11 — Europe PMC: literature crosslinks and accessible text (P2)

**Acquire:** The [official REST service](https://europepmc.org/RestfulWebService) documents JSON/XML search at `https://www.ebi.ac.uk/europepmc/webservices/rest/search`, with `query`, `format` and `resultType=core` for richer records; follow documented cursor continuation for larger queries. Full-text XML is provided for eligible open-access records, and article status/data links are additional endpoints. Direct documentation fetch was blocked on one attempt; the official indexed documentation was accessible. No data response was probed here.

**Graph value:** Adds data accession links, references, work status and supplementary literature metadata. Deduplicate against PMID/PMCID/DOI rather than counting Europe PMC and PubMed as independent scientific support. License checks remain item-specific, including abstracts and full text. Proposed daily overlap-window refresh for the seed's literature and periodic reconciliation of known records.

## A12 — Crossref: DOI metadata, updates and funding links (P2)

**Acquire:** [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) provides `/works` searches and DOI lookup via `https://api.crossref.org/`. Capture DOI, authors/ORCID, affiliations, funders, relation fields, licenses and available post-publication updates. Use documented filters/cursors for incremental retrieval and provide a real contact in the polite-pool request. Most metadata is unrestricted, but abstracts may carry copyright.

**Graph value:** Resolve publication versions and corroborate funding/identity links. Crossref documents trusted-source updates including Retraction Watch; still keep the underlying notice and do not infer that absence of an update means a paper is valid. Coverage depends on deposits. Proposed weekly rechecks of graph-linked works and a separate retraction/correction update pass; the DOI route was documentation-reviewed, not live-tested.

## A13 — Open Targets: target–disease evidence (P2)

**Acquire:** [Open Targets data access](https://platform-docs.opentargets.org/data-access) recommends GraphQL for focused entity/association queries and bulk downloads/BigQuery for systematic work. Pin a release, select relevant evidence/target/disease datasets, retain Ensembl target IDs, disease identifiers and original evidence provenance. Review its license documentation and upstream rights per selected dataset before public redistribution.

**Graph value:** Provides target evidence and therapeutic context for Priya's discovery view. Scores prioritize research; they do not establish efficacy for a patient or prove identical mechanisms across diseases. Avoid circular confirmation where Open Targets already incorporates the same ClinVar/literature sources in the graph. Proposed refresh: provider releases. Useful after the primary-source assertion model works, because aggregation makes evidence lineage harder.

## A14 — Grants.gov: prospective funding opportunities (P2)

**Acquire:** The [Grants.gov API guide](https://grants.gov/api/api-guide) documents unauthenticated `POST https://api.grants.gov/v1/api/search2` with JSON such as `{"keyword":"rare disease"}` and the `fetchOpportunity` detail operation. Follow the current schema for pagination/detail parameters rather than inventing offsets; store opportunity ID/number, agency, title, eligibility, deadlines, status, award range and official notice URL. These are documentation-reviewed operations, not tested calls in this task.

**Graph value:** `FundingOpportunity TARGETS Topic` and `ACCEPTS_APPLICANT_TYPE …` complement RePORTER's already-awarded projects. Check dates/timezones, amended notices and applicant/geography requirements before surfacing a lead. A keyword hit is not verified eligibility, and a forecast is not an open competition. Proposed daily refresh for active opportunities, with stale-status warnings and source links. Review API fair-use terms before scaling.

## A15 — Coriell: human cell-line and biospecimen assets (P2)

**Acquire:** The [Coriell catalogue](https://catalog.coriell.org/) and [cell-line overview](https://catalog.coriell.org/1/Browse/Cell-Lines) provide an entry point for human research models. Curate public catalogue accessions and condition/gene/material metadata for a focused cluster. No public bulk API was established here; seek a permitted catalogue export for scale. Keep availability/access requirements and links to repository-specific terms.

**Graph value:** Adds human cell models alongside JAX mouse models. Connect asset accession to material type, genotype as actually stated, condition, provider and scientific characterization references. Catalogue availability is different from permission to obtain or reuse material; material-transfer agreements and researcher eligibility remain separate. Avoid storing donor-identifying or unnecessary individual clinical details. Proposed monthly metadata refresh and availability recheck before a recommendation.

## A16 — BioStudies: reusable datasets and study assets (P2)

**Acquire:** [EMBL-EBI BioStudies](https://www.ebi.ac.uk/biostudies/) groups study descriptions, files and links to external data archives. Begin with accessions linked by the seed's papers; capture study accession, associated DOI/PMID, file metadata, external accessions, protocol/document links and declared access/license. Use public downloads linked from each study; discover and validate the current public retrieval API before building a broad connector. The submission API is a different interface and should not be mistaken for unrestricted public search.

**Graph value:** `Publication HAS_DATASET StudyAsset` and `StudyAsset USES_PROTOCOL …` make reuse discoverable. Keep experiment design, species, sample type and measurement method; do not ingest every large raw sequencing file merely to index its existence. Restricted datasets remain metadata-only. Proposed monthly recheck of cited accessions and versioned snapshots. Access and reuse conditions are dataset-specific.

## Other inputs to plan, with explicit boundaries

- **Patient-group contributions:** a structured, consented asset submission form can capture registry/model availability, correction requests and role contacts. Every contribution needs organization verification, a source/document, review state and timestamp. Never ingest private clinical observations into the public graph by default.
- **Conference abstracts/talks:** add only through publisher/society proceedings or speaker-authorized materials with clear citation and rights. Label preliminary evidence and link later publications. This research did not establish one universal conference data provider.
- **Investors and private funders:** later curate official portfolios, award announcements and RFAs with dates and modality/disease evidence. An investor's historical portfolio is not proof of current funding appetite. No comprehensive open investor database was verified; do not make a commercial people/portfolio database a first-build dependency.
- **Biomarkers and clinical outcome assessments:** initially extract explicitly named measures from trial records, publications and public registry dictionaries; distinguish proposed, validated and regulatory-qualified roles. Add a specialized authoritative provider only once the pilot reveals a specific gap.

## Recommended first expansion

Build the disease/gene/phenotype spine from the PDF sources plus **HGNC, Reactome, ClinGen and GenCC**, then add one verified organization and one real asset for each pilot disease. Add researcher/institution identity only for the investigators encountered in those records. This sequence gives the graph useful paths while making evidence review tractable. There is no requirement to ingest all proposed additional sources before a coherent pilot exists.

# Source-by-source extraction guide

Research date: **2026-10-03**. This is the consolidated plan for all **21 named sources or source categories** in the six-page rare-disease atlas brief, including RARe-SOURCE from its introduction. The [PDF review](pdf-review.md) records page-level coverage and the original links. Each source below has its own acquisition workflow, identifiers/fields, graph mapping, access/reuse limitations and maintenance considerations.

## Recommended approach

Use **bulk ontology/data files** for MONDO, HPO and broad structured datasets; **documented APIs** for focused literature, variant, trial and grant queries; **approved exports or curated public pages** for organizations and assets. Retain native records and cited assertions before resolving them into a graph. An identifier match is not evidence of a shared disease mechanism, and a public web page is not necessarily a reusable bulk dataset.

The most material findings are:

- **Orphanet has two different access paths:** open scientific products cover disease/gene/phenotype data, while expert-resource data such as organizations and registries have request/contract conditions. Do not apply the scientific-product license to the whole site.
- **OMIM, NORD and Global Genes need source-specific access/rights decisions.** The guide identifies the access/export route and records what remains unverified; it does not claim permission was obtained. In particular, NORD's CSV request is for a disease-database subset, not a confirmed organization export.
- **RareConnect is archival**, following retirement on 5 December 2023. It is not a source of current messaging or fresh community activity.
- **PMC's old OA Web Service is retired.** Plan around current OAI-PMH/approved PMC Cloud distribution and item-specific rights rather than old download recipes.
- **Genetic Alliance in the PDF means the US organization.** Its embedded link settles the identity. Genetic Alliance UK is a distinct related source for Rare Disease UK's community network.

These findings are supported in the corresponding source sections below. Access failures are observations from this research environment, not proof that a source is globally unavailable.

## Evidence status and reproducibility

**Live-probed** means a bounded read-only sample or file header succeeded; it does not prove whole-dataset completeness, production throughput, pagination exhaustion or redistribution permission. **Documentation-reviewed** means official provider material was inspected but the proposed data route was not executed. **Proposed** labels graph design and recommended refresh schedules. **Conditional/unresolved** marks access, rights or interface details that must be settled before implementing that connector.

Compact evidence logs: [biology/release/API probes](research/biology-probes.json), [literature/trial/grant probes](research/literature-probes.json), and [MGI/UniProt probes](research/asset-probes.json). Community-page and terms observations are recorded inline. No full corpus harvest, account registration, access request, payment, outreach or production graph ingestion was performed as part of this research.

This file is assembled from reviewed notes under `docs/research/` and the [source catalog](../data/source/catalog.json). Rebuild with `python3 scripts/build_source_guide.py`; check inventory/link coverage and freshness with `python3 scripts/build_source_guide.py --check`. That check verifies document structure and inventory alignment, not biological correctness or endpoint behavior.

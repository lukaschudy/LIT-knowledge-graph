# LIT rare-disease knowledge graph

Research and extraction planning for the **AI Atlas for the World’s Rare Diseases** challenge.

The original six-page PDF is [`Knowledge graph`](Knowledge%20graph) (its filename has no extension). Its text is preserved in [`data/source/challenge-brief.txt`](data/source/challenge-brief.txt).

## Deliverables

- [PDF review and complete source inventory](docs/pdf-review.md)
- [Source-by-source extraction guide](docs/source-extraction-guide.md)
- [Additional sources and ingestion priorities](docs/additional-sources.md)
- [Graph design and implementation sequence](docs/ingestion-plan.md)

This repository documents how to acquire and model the sources. It does not yet contain a populated knowledge graph or production ingestion connectors. Access and reuse conditions vary by provider; evidence and unresolved dependencies are recorded per source.

## Reproduce the PDF extraction

Requires Poppler (`pdfinfo`, `pdftotext`). Run from the repository root:

```bash
pdfinfo 'Knowledge graph'
pdftotext -layout 'Knowledge graph' data/source/challenge-brief.txt
sha256sum 'Knowledge graph'
```

Expected SHA-256: `9c502bdfcc0d5c400c11dd7a78bd9fc3c4b4f07529a973e076d109e28605d67e`.

The page boundaries in the extracted text are form-feed characters. Source inventory page numbers refer to the PDF's physical pages, numbered 1–6.

## Maintain the research guide

The guide covers **21 PDF sources/categories**; the expansion plan recommends **16 additional sources**. Edit source notes under `docs/research/`, then rebuild the consolidated Markdown file:

```bash
python3 scripts/build_source_guide.py
python3 scripts/build_source_guide.py --check
```

The check verifies the PDF checksum, source inventory, all 18 embedded PDF URLs, section citations, and generated-file freshness. It does not test production connectors or certify scientific claims. Small read-only API/file probes are recorded under `docs/research/*-probes.json`; access failures and unresolved rights are documented in the guide. See the [research completion audit](docs/research-audit.md) for verification scope.

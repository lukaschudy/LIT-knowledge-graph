# LIT rare-disease knowledge graph

The main graph now connects **TopK search → Astra answers and extraction → evidence review → deterministic recommendations → editable brief**. Open `/explore`; the former `/research` page redirects there. See [setup and demo instructions](docs/research-workspace.md).

```bash
python3 -m atlas build-graph --source-root /path/to/harvest-repository
python3 -m atlas resolve-neuro --provider codex
python3 -m atlas app --env-file .env --search topk --provider codex
```

Install the `topk` and `graph` extras and prepare the verified local passage export first, as described in the setup guide. This local app uses the signed-in Codex CLI or an OpenAI API key; credentials stay on the server.

**Connected data:** the full harvest graph covers **21,746,825 source records across 105 datasets**, indexing **8,914,689 entities and 53,429,267 source relationships**, with dense views, full-index entity search and original-record inspection. See [build and browsing instructions](docs/full-harvest-graph.md). The focused review/planning layer starts with 45 real entities and 53 curated assertions, plus **15,502 GRIN passages and 19 neuro passages** in separate verified TopK collections. Search results retain source URLs, exact text, locators and review status. [Harvest coverage](docs/harvest-coverage.md) includes 40 source collections, including unavailable sources; the full graph indexes the 105 locally available datasets. This is distinct from the focused [TopK passage index](docs/topk-search.md).

**Default graph:** the dense full-harvest view, starting at 10,000 entities. The optional resolved neuro view starts at 120 entities and supports neighborhood expansion, canonical identity inspection and quoted evidence. [Entity ingestion and resolution](docs/neuro-entity-resolution.md) explains identity rules, model extraction, setup and current coverage.

**Voice:** Ask Atlas supports local microphone transcription into an editable question. No speech API key is needed. [Setup and controls](docs/research-workspace.md#voice-in-ask-atlas).

The planning scope is **EPG5 / Vici syndrome**, with WDR45 / BPAN and AP4B1 / SPG47 as candidate comparators. New extracted claims stay unreviewed; unresolved scientific, maintainer and access gates remain visible. No real candidate is made ready by an AI-generated answer alone.

The original six-page PDF is [`Knowledge graph`](Knowledge%20graph) (its filename has no extension). Its text is preserved in [`data/source/challenge-brief.txt`](data/source/challenge-brief.txt).

## Architecture and visual walkthroughs

The challenge asks for a journey from diagnosis to a justified connection, reusable asset, partner and practical next step. Read the architecture in three stages: **prepare evidence → find opportunities → recommend an action**. Feedback, source updates and evaluation keep those stages useful over time.

The preparation, discovery and decision loop runs in the local graph interface. Source maintenance and comparative evaluation below remain target workflows. Live TopK retrieval and Astra calls have been exercised; comparative scientific performance is not yet measured.

### 1. Prepare the evidence once

Before users search, preserve source records and ask Astra to extract claims with their supporting passages. Validation and scientific review determine which claims can support recommendations. TopK stores searchable passages; the graph stores entities, relationships and provenance.

```mermaid
flowchart LR
    Sources[Source records] --> Extract[Astra extracts claims]
    Extract --> Review[Validate and review]
    Review --> Graph[Qualified graph claims]
    Sources --> TopK[TopK passage index]
```

**Why it matters:** this work is reused across queries. A searchable passage is not automatically an accepted scientific claim.

### 2. Find relevant opportunities

Resolve the exact variant and the user's research goal. Retrieve TopK passages and a small graph neighborhood, then combine their evidence into candidate assets, partners and actions.

```mermaid
flowchart LR
    Goal[Variant + research goal] --> Search[TopK finds passages]
    Goal --> Graph[Graph finds relationships]
    Search --> Candidates[Candidate opportunities]
    Graph --> Candidates
```

**Why it matters:** semantic similarity helps find evidence, while graph relationships connect that evidence to people and assets. Neither alone establishes that an opportunity is suitable.

### 3. Check the opportunity and recommend a next step

Astra proposes source-grounded claims and drafts cited explanations. The deterministic decision engine checks source-qualified scientific fit, access and contradictions before an action can become ready for discussion. If a searchable missing fact could change the decision, request one bounded follow-up round; new extracted evidence stays unreviewed. Return a cited next step with its partner and unresolved blockers.

```mermaid
flowchart TD
    Candidates[Candidate opportunities] --> Check[Assess fit, access and contradictions]
    Check --> Gap{Decisive evidence missing?}
    Gap -->|Yes, budget remains| Search[Targeted search via step 2]
    Search --> Check
    Gap -->|No, or budget reached| Action[Action + partner + evidence + blockers]
```

**Why it matters:** the system can recommend a feasibility discussion, ask for clarification or reject a candidate. It does not have to produce a positive recommendation. Precomputed evidence, cached retrieval and a bounded follow-up keep live work limited.

### 4. Refine the result with user and expert feedback

A user's priorities can change which action is most useful. A factual correction needs evidence and review before it changes the graph.

```mermaid
flowchart LR
    Result[Recommendation] --> Feedback[User or expert feedback]
    Feedback -->|New preference| Goal[Refine goal in step 2]
    Feedback -->|Factual correction| Review[Validate evidence in step 1]
```

**Why it matters:** feedback improves relevance without treating a user's acceptance as scientific proof.

### 5. Recheck recommendations when evidence changes

In the background, trace a new study, correction or asset update to the claims and recommendations it affects. Review the changes, refresh the stores and invalidate affected cached results before reassessing them.

```mermaid
flowchart LR
    Change[Source changes] --> Review[Review affected claims]
    Review --> Refresh[Update stores and invalidate caches]
    Refresh --> Recheck[Reassess via step 3]
```

**Why it matters:** a recommendation must remain tied to the evidence that justified it. Maintenance happens outside the normal live query.

### 6. Measure whether the workflow is actually better

Compare search, basic retrieval-augmented chat, graph-assisted retrieval and our workflow on the same held-out research tasks. Qualified reviewers assess the proposals; include corrections, failures, human effort, latency and cost.

```mermaid
flowchart LR
    Tasks[Held-out tasks] --> Compare[Run comparable workflows]
    Compare --> Review[Review quality and measure effort]
    Review --> Improve[Improve and retest]
    Improve --> Compare
```

**Why it matters:** these techniques are not individually new. Our advantage must come from reducing the effort to an acceptable research proposal. **10× is a target, not a measured result**, and does not imply 10× faster treatment development.

### Interactive walkthroughs

- **[Explore all five loops and compare approaches](docs/visualizations/research-decision-loops.html):** evidence preparation, discovery/recommendation (steps 2–3 above), feedback, maintenance and evaluation. Switch the example between supporting, missing and incompatible evidence.
- **[Explore the interface concept](docs/visualizations/rare-atlas-interface.html):** follow a fictional diagnosis through connections, evidence, assets and a collaboration brief. This explains the intended experience, not live scientific findings.

Download the interactive files and open them in a browser; GitHub displays their source. The diagrams above render directly in the README.

## Deliverables

- [PDF review and complete source inventory](docs/pdf-review.md)
- [Source-by-source extraction guide](docs/source-extraction-guide.md)
- [Additional sources and ingestion priorities](docs/additional-sources.md)
- [Graph design and implementation sequence](docs/ingestion-plan.md)
- [Earlier GRIN cluster, demo and evaluation plan](docs/grin-cluster-plan.md)
- [Frontend strategy](docs/frontend-strategy.md)
- [Proposed recommendation loops and model architecture](docs/architecture/recommendation-loops.md)
- [Implemented decision engine, critical review and assay-reuse demo](docs/architecture/decision-engine.md)

This repository includes harvested-source graph adapters, a resumable bulk indexer, a curated biomedical evidence slice, a synthetic acceptance graph and an offline HPOA converter. The graph covers available local harvests; missing source access and unsupported semantic mappings remain visible through the source records. Access and reuse conditions vary by provider; evidence and unresolved dependencies are recorded per source.

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

# Submission record — one GRIN journey

Documentation snapshot: **4 October 2026**. Start with the [README](../README.md), then use this page to verify what was submitted, what runs publicly, and which claims the evidence supports. The canonical demo is the pinned public GRIN release below. Broader research components are documented separately rather than implied to run in that release.

## Submission artifacts

The [challenge brief](../data/source/challenge-brief.txt) requests a working prototype, a source repository with architecture and dataset reproduction instructions, a team video, and a one-minute walkthrough. Track prizes also require use of OpenAI models or tools.

| Item | Location / status |
| --- | --- |
| Public prototype | [Atlas graph](https://atlas.varentik.com/explore), [annotation viewer](https://atlas.varentik.com/cluster), [proposal form](https://atlas.varentik.com/propose) |
| Source and architecture | Public repository; [README](../README.md) explains the three components and pins the deployed source |
| Dataset reproduction | [Instructions below](#reproduction-and-verification), [source guide](source-extraction-guide.md), [coverage manifests](harvest-coverage.md) |
| One-minute product walkthrough | “The idea” video linked at the top of the README |
| Technical explanation | Additional “How it works” video linked at the top of the README; includes local implementation beyond the public runtime |
| Team video | Uploaded separately, as confirmed by the submitter; GitHub hosting is not required |
| OpenAI contribution | Codex-supported source annotation/reconciliation, plus the separate local Codex/OpenAI model adapter; see [annotation method](grin-ai-annotation.md) and local implementation below |

This record tracks the supplied brief. It is not a receipt from the competition portal and does not independently confirm any additional portal fields, deadlines or acceptance decisions.

## Canonical version and implementation boundaries

| Reference | Version |
| --- | --- |
| Deployed application source | `25158ce` |
| Source plus verified release receipt | [6d3ccd18ee55023b083b1a46ac10acba70111d98](https://github.com/lukaschudy/LIT-knowledge-graph/tree/6d3ccd18ee55023b083b1a46ac10acba70111d98) |
| Source branch | `feat/atlas-production-performance` |
| Cloudflare Worker version | `ea3f905c-36cb-45c9-adb9-8af3505fbbd3` |
| Recorded deployment | 4 October 2026, 100% traffic, Worker `varentik-atlas` |
| Release provenance | [Dense release receipt](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/deploy/cloudflare/dense-release.json), [gene identity release](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/deploy/cloudflare/gene-identity-release.json), [sealed build manifest](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/deploy/cloudflare/gene-identity-build-manifest.json) |
| Documentation entry point | `main`, README and this submission record |

These are immutable source references for the documented release, not a promise that the mutable website will never change. Later releases should update this table, the README, the walkthrough and the release receipt together. Historical receipts and benchmark reports retain their original scope and dates.

The public Worker provides snapshot-backed graph search, neighborhoods, raw source-record inspection, fixed-scope annotation answers, the GRIN2B support overview, and durable pending proposals. It does not call TopK, a live language model, or local Whisper. The 10,033-node display is a bounded HGNC projection with a curated GRIN overlay; most nodes do not have the depth of the GRIN evidence path.

### Local research implementation

The broader implementation is pinned at [31a20e279de520a509fcdc05fb5024de07acaa98](https://github.com/lukaschudy/LIT-knowledge-graph/tree/31a20e279de520a509fcdc05fb5024de07acaa98), branch `feat/research-recommendations`.

| Implemented component | Evidence / instructions |
| --- | --- |
| TopK retrieval and Codex/OpenAI model adapters | [Research workspace](https://github.com/lukaschudy/LIT-knowledge-graph/blob/31a20e279de520a509fcdc05fb5024de07acaa98/docs/research-workspace.md) |
| Extraction, review, compatibility gates and bounded follow-up | [Decision engine](https://github.com/lukaschudy/LIT-knowledge-graph/blob/31a20e279de520a509fcdc05fb5024de07acaa98/docs/architecture/decision-engine.md) |
| Model calls and persisted research actions | [Integration receipt](https://github.com/lukaschudy/LIT-knowledge-graph/blob/31a20e279de520a509fcdc05fb5024de07acaa98/docs/research/integrated-smoke-2026-10-04.json) |
| Observed live model/retrieval call | [Ask Atlas reliability receipt](https://github.com/lukaschudy/LIT-knowledge-graph/blob/31a20e279de520a509fcdc05fb5024de07acaa98/docs/research/live-ask-atlas-reliability-2026-10-04.json) |
| Current default GRIN answer boundary | [Demo scope](https://github.com/lukaschudy/LIT-knowledge-graph/blob/31a20e279de520a509fcdc05fb5024de07acaa98/docs/demo-answer-scope.md) |

The workspace guide includes an earlier EPG5/Vici planning demonstration. That is a separate development scenario, **not a second submission cluster**. The current default Ask Atlas scope is GRIN; explicit custom workspace/bundle workflows are for development. Historical EPG5 timing receipts do not measure the hosted GRIN experience. Follow the pinned demo-scope document when older examples disagree.

The pinned local configuration uses `gpt-6-astra` through the Codex or OpenAI adapter; model access remains an environment prerequisite, not a capability supplied by the public Worker.

Running this optional implementation requires prepared local data and its own service/model access. Its saved local Codex login is not transferred into Cloudflare. It is not necessary for the public judge walkthrough.

## Judge walkthrough

Use the same GRIN case throughout. Maria is an illustrative patient-organization leader, not a claim of a real patient engagement.

| Step | Action | What the judge can verify |
| --- | --- | --- |
| Diagnosis to knowledge | Search GRIN2B; select it; choose Ask about this; send the natural overview/help question | Curated knowledge, uncertainty and support signposts; no claim that every recorded gene has an equivalent answer |
| Knowledge to connection | Search NMDA receptor signaling; inspect selected GRIN2A/GRIN2B variant connections | A shared published functional category, with source-qualified relationships |
| Connection to evidence | Open the annotation viewer; inspect S541R, C461F and S541G | Core vs provisional vs opposing-function evidence, exact source locators, WT comparators and assay conditions |
| Evidence to reusable asset | Search GRIN Variant Patient Registry and inspect its resource/maintainer neighborhood | An existing registry, potential partner routes and access questions |
| Asset to shared action | Read the committed research discussion brief | A concrete observational-research question and feasibility criteria, not a generated protocol or approval |
| Honest gap | Search an outside entity or missing item; inspect the coverage response or proposal route | Broader record discovery stays separate from deep GRIN answers; contributions remain pending |

[Research discussion brief](../data/curated/grin_research_proposal.json): **Could existing GRIN registry measures support a functionally stratified observational comparison across selected GRIN2A and GRIN2B variants with published evidence of reduced receptor function?**

The brief identifies the Colorado and Leipzig registry teams and a functional-assay resource using public source routes. Before reuse, researchers must resolve exact alleles, compare clinical phenotype/outcome definitions, establish consent/data access, and confirm aggregate case availability. No partner commitment, participant eligibility, access permission or treatment benefit is established. The brief is a committed data artifact; the public chat does not provide an autonomous brief editor or contact workflow.

The ready-to-send S541R/C461F question is a short evidence drill within this larger journey. It should not replace the final asset/partner/action step.

## How the cluster earns trust

Core inclusion requires a source-reported Likely LoF classification and an eligible quantitative intrinsic-function measurement with a WT comparator. Protein notation is not treated as a fully resolved genomic allele.

| Category | Variants |
| --- | --- |
| Core, likely reduced function | GRIN2A G483R, A716T, D731N; GRIN2B E413G, S541R, P553T |
| Provisional, possible reduced function | GRIN2B C461F |
| Opposing-function controls | GRIN2B S541G, A639V |
| Unresolved control | GRIN2B R540H |

This is a source-defined cohort with explicit gates, not a newly discovered unsupervised cluster. Gene identity merging uses exact unambiguous HGNC IDs; it does not add biological edges. See the [cluster evidence](grin-cluster-evidence.md), [annotation receipt](../data/benchmarks/grin-v1/cluster-annotation-receipt-v2.json) and [public identity rules](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/docs/demo-answer-scope.md).

Two separate AI drafts and a third source-based audit preserve reported measurements, units, bounds, WT references and contradictions. Expert human review is pending. Source-span checks prove provenance, not that every interpretation is scientifically correct. The seven development papers are exposed examples and cannot double as a held-out accuracy evaluation.

## Impact case and validation

**Target milestone:** prepare a brief that a qualified researcher can accept for feasibility review, toward a decision on whether to pursue a shared observational study. This is earlier than study launch or candidate treatment selection.

| Work | Illustrative manual budget | Illustrative Atlas budget |
| --- | --- | --- |
| Discover relevant material | 8 h | 0.25 h |
| Verify evidence and assess resources/partners | 10 h: 6 h evidence + 4 h resources | 1.5 h |
| Draft the brief | 2 h | 0.25 h |
| Total person-hours | **20 h** | **2 h** |

These are planning assumptions for a falsifiable **10× target**, not observed results. Assume an already-curated slice, equivalent source access, and an unchanged expert-review standard. Record initial curation/maintenance separately; access delays, recruitment and downstream research are not accelerated by assumption.

Validation should compare equivalent tasks with and without Atlas, counterbalance task order, and include useful connections, misleading neighbors and no-supported-route cases. Log total person-hours including corrections, false leads, reviewer acceptance, model cost and latency. Have qualified reviewers assess usefulness and grounding without being told which workflow produced the brief. Report the measured ratio even if it is below 10×.

Some presentation narration states a stronger achieved-speed claim. The evidence record supports only the target above; neither a measured 10× research speedup nor faster treatment development has been demonstrated. Updating documentation does not change the uploaded video.

## Reproduction and verification

### 1. Rebuild the public artifact

Use the exact clone/check-out/build commands in the [README](../README.md#reproduce-the-documented-public-version). Packaging requires Python 3.11+; the Worker runtime requires Python 3.13+, Node.js and uv. No paid model call, TopK account or full harvest is needed for packaging.

The pinned production checkout contains:

- `data/curated/grin_atlas_bundle.json`: curated graph input; the build derives the hosted graph using the richer reviewed annotations.
- `data/curated/grin_cluster_demo_v2.json`: seven-paper observation and annotation bundle.
- `data/curated/grin_public_excerpts_v2.json`: 545 bounded source spans.
- `data/curated/hgnc_dense_snapshot.json.gz`: 10,000-node, 5,346-relationship public projection.
- `data/curated/cloudflare_public_data_receipt.json`: hashes and declared scope of the public snapshots.
- Annotation receipts and the build/verifier scripts that check input and output consistency.

The complete local frozen source snapshot is **optional for rebuilding the public artifact**. If present, its digest and re-extracted excerpts must also match. If absent, the sealed committed public excerpts are used. This supersedes older instructions saying a fresh clone cannot build the hosted evidence view.

### 2. Reproduce acquisition and scientific preparation

Rebuilding the public artifact does not rerun the entire scientific preparation process. For that, follow the [source extraction guide](source-extraction-guide.md), [harvest instructions](harvesting.md), [annotation method](grin-ai-annotation.md) and [cluster rebuild instructions](grin-cluster-evidence.md#rebuild-and-run).

Full raw sources, normalized harvest files and complete source packets are not committed. Reacquisition may require provider access, source-specific permissions and additional storage. Providers can change: compare receipt hashes and declared source scope rather than assuming a fresh download is byte-identical. Preserve unavailable supplements and image-only evidence as gaps. Re-running AI annotation is not expected to produce identical prose; the submitted public bundle is a frozen development artifact.

### 3. Verify software separately from scientific performance

The release receipt records **168 application tests**, a sealed **37-file build with 71 inputs**, and live checks of the unique GRIN2B result, eight incident relationships and curated answer. Earlier [reliability reports](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/docs/research/reliability-review-2026-10-04.md) include Python/browser matrices and endurance checks at their own revisions. Those historical totals should not be presented as a fresh test run of every later commit.

Run the README's application tests and build verification in the pinned checkout. For the wider offline suites and browser checks, follow [check-reliability.sh](https://github.com/lukaschudy/LIT-knowledge-graph/blob/6d3ccd18ee55023b083b1a46ac10acba70111d98/scripts/check-reliability.sh), which lists the additional Python/Playwright dependencies. Public data receipts validate packaging; [TopK's known-case regression](topk-search.md) validates retrieval on ten known variants. Neither measures held-out scientific extraction accuracy or patient outcomes.

Documentation verification on 4 October 2026: a clean Git archive of `6d3ccd1`, without ignored harvest/source files, successfully built and passed the build verifier and all **168 application tests**. Repository file/anchor checks passed for **57 links** across the updated guides. This check did not rerun Cloudflare runtime setup, model calls or the full scientific annotation process.

## Requirement-to-evidence map

| Judging criterion | Evidence in this submission | Remaining limit |
| --- | --- | --- |
| Graph quality | Stable HGNC identities, source-qualified GRIN claims, explicit cohort gate and opposing controls | Broad HGNC display is not a densely reviewed disease graph; cohort is curated |
| Evidence integrity | Versioned snapshots, citations, WT comparisons, contradictions and annotation receipts | Human expert review and held-out accuracy measurement remain pending |
| Patient progress | Registry/partner path and a specific feasibility brief | Access, cohort availability and researcher acceptance unconfirmed |
| 10× impact | Named milestone, explicit 20 h / 2 h assumptions and comparative evaluation plan | No measured speedup |
| Ambition and product craft | Searchable globe, progressive evidence, Ask Atlas, missing-item proposal receipts | Full local AI workflow is not deployed; no autonomous public evidence refresh |

## Documentation maintenance

When making another release, update the README and this record together: application/source SHA, deployment receipt, data counts, runtime boundaries, walkthrough and checks actually run. Preserve historical receipts. Label new experiments as local or deployed, and simulated or observed. Do not silently turn planned features, model-generated hypotheses or pending proposals into verified capabilities.

Earlier [architecture loops](architecture/recommendation-loops.md) are design history; the status map on this page describes implementation availability. The old synthetic demo remains useful for software checks but is not the submission story. The team video remains an external submission artifact, not an outstanding GitHub task.

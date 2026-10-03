# Evidence and recommendation loops

Updated 4 October 2026. The [action-specific decision engine](decision-engine.md) now implements assay-reuse gates, cited recommendations, one bounded follow-up interface, preference ordering and explicit snapshot reassessment, with a synthetic demo and CLI/HTTP entry points. Live TopK/Astra integration, scientific review UI, background maintenance and comparative evaluation remain proposed. The separately curated [GRIN demo](../grin-demo.md) and legacy neighbour explorer remain available.

## Product outcome

Help a patient-group leader move from a specific research question to an evidence-backed opportunity, a relevant asset or partner, and a concrete next step. The selected next scope is EPG5 / Vici syndrome, with WDR45 / BPAN and AP4B1 / SPG47 as candidate comparators after extraction and coverage review. The first action is assay reuse: measure a specified defect while preserving differences in biological step, readout and model context. The [GRIN cluster plan](../grin-cluster-plan.md) documents the earlier scope, not the new default. See the [critical review and implementation contract](decision-engine.md).

The challenge's action requirements include mechanistic overlap, assessment of shared registries/study designs/models/biomarkers, and overlapping research networks. A recommendation should identify what might be reusable, why, who maintains it, access conditions, the questions still unresolved, and the next research milestone. It is not an individualized treatment recommendation or proof that an asset transfers between populations.

## Components

| Component | Intended responsibility |
| --- | --- |
| Source records | Preserve snapshots, versions, dates, stable identifiers and passage locations. |
| TopK | Hybrid semantic and keyword retrieval over the corpus we actually index. Similarity is a retrieval signal, not scientific confidence. |
| Structured graph | Store entities, source-qualified claims, supporting/contradicting evidence, researcher links, assets and review states. SQLite is sufficient for the prototype's current graph representation. |
| Astra | Extract structured claims and assess proposed research actions from supplied evidence. Keep extraction and action assessment as separate tasks. |
| Validation and review | Check identifiers, source spans, schema and scientific interpretation; preserve uncertainty. Matching a quotation does not establish entailment. |
| Recommendation records | Preserve proposed actions, referenced claims, evidence versions, assumptions, blockers and status separately from scientific observations. |
| Frontend | Show a focused evidence path, recommendation status, contradictions and an editable cited handoff brief. |

TopK's current semantic-index documentation identifies `topk-embed-v1` as the production retrieval model. Its multi-vector retrieval is distinct from Astra's generation and reasoning role. Visual-document retrieval is a possible later extension, subject to confirming the ingestion and API path; it is not assumed to be implemented. Sources: [TopK semantic search](https://docs.topk.io/guides/semantic-search), [TopK model card](https://huggingface.co/topk-io/topk-embed-v1-small).

GPT-6 Astra is the proposed quality-first starting model, subject to access and evaluation on our corpus. Use medium reasoning as an initial extraction setting and high for difficult comparisons, then measure the quality/latency tradeoff. No GRIN-specific superiority has been established. Source: [official model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra).

## Five loops

### 1. Prepare and validate evidence

Collect permitted source records → preserve identifiers and snapshots → extract claims → validate and review → publish eligible claims and searchable passages. Route unresolved extractions back for correction. Do this ahead of user queries and incrementally when documents change.

### 2. Discover, challenge and recommend

Resolve the exact variant and research goal → retrieve TopK passages and a bounded graph neighborhood in parallel → propose candidate actions → check scientific fit, access and contradictions → investigate decision-changing gaps → validate and rank eligible actions → return a cited brief.

Start with at most one live follow-up search round. Skip it when the missing information cannot change the decision. If the budget is exhausted, disclose the gap instead of guessing. A graph path can generate a hypothesis; it cannot by itself establish that an assay, measure or treatment transfers across variants.

Recommendation types:

- Assess a documented asset or study component for reuse.
- Explore a collaboration supported by relevant work and a verified professional contact route.
- Resolve a specific missing link through a literature check, expert question or proposed experiment requiring review.

Apply hard compatibility gates before ranking. Distinguish **ready for discussion**, **needs clarification**, and **not supported**. The implemented assay engine uses step/readout/model compatibility, versioned human review, maintainer/access and action-specific exclusions. It orders by status, unresolved gates and user preference; citation counts and model confidence do not boost rank. Broader utility ranking remains to be evaluated. Do not present an ordinal ordering as a clinical probability.

The deterministic engine owns eligibility. A future model can propose and explain candidates, but cannot approve its own extraction. New live evidence stays unreviewed; a candidate may remain unresolved after follow-up. Reviewed offline evidence can already justify a feasibility discussion.

### 3. User and expert feedback

Recommendation → user constraint, correction or reported outcome → distinguish preferences from factual claims → validate new evidence → reassess affected candidates. Accepting a recommendation changes workflow status, not the truth of the supporting science. Contacting a partner is a separate user-authorized action.

### 4. Evidence maintenance

Changed source → affected claims and dependent recommendations → re-extraction/review → updated graph and search records → cache invalidation → retain, downgrade or withdraw affected recommendations. Explicit whole-snapshot change detection and reassessment are implemented, including newly added counterevidence. Selective invalidation, background watching and automatic notification remain planned.

### 5. Evaluation and improvement

Held-out tasks → comparable baseline runs → blind qualified review → measure acceptable outcomes including corrections → revise one component and retest. Include a useful connection, a misleading neighbor and a no-supported-route case. Keep development examples separate from held-out evaluation.

## Why this could improve existing workflows

Search portals help find records; basic retrieval-augmented chat synthesizes passages; graph-assisted retrieval adds connected context. Our proposed contribution is a complete, inspectable assessment of a research action: compatibility, access, contradictory evidence, a useful partner, and unresolved questions.

These are conceptual baselines, not a claim that existing products lack these features. Advanced agents and specialist portals can combine them already. The GRIN Portal is a strong domain baseline; merely adding semantic search or drawing a graph is insufficient differentiation.

The hypothesis is that reusable evidence and targeted checks reduce the human work needed to prepare an acceptable research proposal. Measure baseline person-hours divided by our person-hours, including reviewer corrections and failures. Report actual results, even if below 10×. Track curation/maintenance cost separately. Faster preparation does not establish faster study access, recruitment, treatment development or clinical success.

## Keeping the live experience fast

- Precompute extraction, identifier resolution, asset properties and researcher links.
- Use direct graph lookups and bounded parallel retrieval.
- Shortlist candidates in code, then assess a compact evidence bundle.
- Limit live follow-up work; return unresolved blockers honestly.
- Cache against source versions and invalidate affected results when evidence changes.
- Show stored evidence first and visibly update the assessment as it finishes.

Initial targets, not measurements: stored results around one second, first assessment in 5–10 seconds and deeper investigation in 15–30 seconds. Measure actual latency and adjust scope before making demo promises.

## Subscription-backed local prototype

OpenAI documents Sign in with ChatGPT for eligible Plus/Pro users in open-source apps and personal projects running locally. The app must use the official OAuth flow, discover models available to the signed-in account, and confirm Astra is available. Account eligibility has not been checked and no integration has been implemented.

The documented flow uses the public Responses API, `store: false` and streaming, with application-managed request context and preview restrictions. Our backend can call TopK and the graph before inference. Keep credentials local and out of frontend bundles and Git. Ordinary API billing remains an alternative behind the same model adapter. Hosted private/commercial availability is restricted; a personal subscription is not assumed to fund a public multi-user service.

Sources: [integration guide](https://developers.openai.com/cookbook/articles/sign-in-with-chatgpt), [models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference), [preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations). These product details were checked on the snapshot date and should be rechecked before implementation.

## Interactive explanations

- [All loops and baseline comparison](../visualizations/research-decision-loops.html)
- [Earlier fictional interface concept](../visualizations/rare-atlas-interface.html)

Open the standalone HTML files in a browser. Their adjacent `.fragment.html` files preserve the editable inline sources. The examples explain intended behavior; they are not live biomedical findings or implemented backend functionality.

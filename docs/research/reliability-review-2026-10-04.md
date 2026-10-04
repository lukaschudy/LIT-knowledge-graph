# Atlas reliability review — 4 October 2026

Status: integration and release verification in progress. Review started at 03:24 UTC; this report is updated as checks finish.

## Scope and release boundaries

The review covers the production Worker and browser UI in `feat/atlas-production-performance`, and the local model, recommendations, ingestion and resolution pipeline in `feat/research-recommendations`. The main user checkout contains unrelated work and is left untouched.

Production retains the white background, dark green lotus, earlier multicolour palette, fixed node positions, camera orbit/pan/zoom, 10,000 public HGNC nodes plus 35 reviewed GRIN nodes, and the private ProposalInbox Durable Object. Ask Atlas on Cloudflare remains deterministic reviewed-source lookup. Live TopK, Codex and Whisper remain local services; this review does not claim they run inside the Worker.

## Findings and changes

| Area | Failure addressed | Verification |
| --- | --- | --- |
| Workspace persistence | Stale server instances could overwrite review history; partial and late job writes needed stronger handling. | Atomic file replacement and disk compare-and-swap under a stable lock; stale instances, failed persistence and overlapping revisions covered by regressions. |
| Evidence and recommendations | Unknown scope, variant-specific capabilities, access conflicts, stale review versions and unverified retrieved text could overstate readiness. | Scope gates, current-version excerpt binding, active counterevidence selection and recomputed assessments; adversarial recommendation and assistant tests. |
| Retrieval and model boundaries | Failed searches could remain cached; SDK and model response errors were not consistently bounded or safe to display. | Retry expiry, refreshed local corpora, bounded structured responses and safe errors. A real TopK/Codex smoke test passed in an isolated temporary workspace. |
| Ingestion and resolution | Resume and artifact paths could accept stale source state, corrupt offsets or inconsistent identities/provenance. | Source checksums, exclusive builders, offset receipts, atomic artifacts, exact PMCID matches, and validation of source quotes, versions, aliases and references. |
| Database selection | Opening the wrong SQLite file could add curated tables to an unrelated database. | Schema guard runs before writes; byte-for-byte preservation regression. Actual 4.5 GB harvest database passed read-only SQLite `quick_check`. |
| Clustering | Complete-link clustering repeatedly recomputed merge distances and admitted features with only retracted support. | Cached linkage distances with deterministic tie ordering; active supporting evidence required. Exhaustive five-node tie checks match the earlier method. A 500-disease dense fixture improved from 22.31 to 1.57 seconds with identical output. |
| Graph and chat UI | Graph refreshes could move nodes or lose selection; stale searches/jobs could overwrite newer scopes; temporary errors could silently change chat mode. | Request invalidation, preserved world coordinates, bounded pointer state and job reconnection; offline browser regression suite and sustained dense-graph interaction tests. |
| Public API and proposals | Ambiguous query parameters, missing focus anchors and malformed/oversized proposal bodies could produce inconsistent results. | Shared validation, scoped coverage gaps, bounded streamed bodies, durable validation and retry-safe receipts. Local Worker restart preserved receipt IDs. |
| Build and deployment | Stale generated assets, unverified source caches and concurrent edits could enter releases. | Independent file allowlists, pinned public data receipts, input/output hashes, atomic complete builds and a shared build/upload lock. An independent vendor verifier authenticates every installed file against the SHA-pinned SDK wheel; forged RECORD metadata and extra files are rejected. |

## Observed runtime evidence

- Ten-minute WebGL interaction run: 10,000 nodes and 5,346 edges retained, 961 cycles, stable world coordinates, zero browser exceptions, suspend/resume passed. Post-GC heap stayed approximately 11.6 MB. This is one local run, not a guarantee for every device.
- Real Ask Atlas question about EPG5/autophagy: TopK retrieval 443 ms, Codex `gpt-6-astra` answer approximately 19.5 s, end-to-end 20.31 s. Three citations from one public source retained `unreviewed_discovery` classification. The completed answer and run persisted at revision 1 in a temporary workspace; no production data, search indexes or saved research workspace were changed.
- Actual resolved artifact passed validation with 1,056 nodes and 2,734 claims. Actual harvest SQLite `quick_check` returned `ok`.
- Cached local Whisper `small.en` processed a one-second silent fixture in 0.87 s with an empty transcript, without downloading a model or recording a microphone. This verifies local loading and a silent-input path, not speech accuracy.

Machine-readable reports accompany this document in `docs/research/`.

## Remaining limits

- Citation and exact-span validation prove provenance, not that every model interpretation follows scientifically from its sources. Scientific review remains necessary.
- Existing completed legacy offset indexes lack the new checksum receipts. Bounded monotonic checks remain, but coordinated corruption in multiple legacy rows requires a verified rebuild or migration to rule out fully. New/resumed indexes receive receipts.
- Interrupted local in-memory model jobs do not survive a process restart. They do not remain permanently running, but an explicit durable interruption audit is not yet recorded.
- File locking uses POSIX `flock`; Windows requires a portability layer.
- Synthetic benchmarks and offline browser fixtures do not replace device diversity, production load testing or a multi-user deployment design. The local research server remains a trusted single-user service.

## Final verification and release

Application suites currently pass: production 125 tests; local 302 tests with optional integrations enabled; both harvest suites 51 tests; both search suites 15 tests; production benchmark suite 56 tests. After vendor integration, 29 packaging regressions pass (14 build/upload and 15 vendor). Production and local browser suites pass 27 scenarios each; cluster browser regressions pass 3, and proposal browser regressions pass 7. The local demo was restarted with the verified changes: policy `assay-reuse-v3`, model available, saved workspace revision 3 and file SHA-256 unchanged.

OpenAI total deadlines now use a small isolated stdlib helper process, covering DNS, connect, TLS, status/headers, chunk metadata and body reads. Timeout kills and reaps the helper. Local transport regressions passed; no paid OpenAI call was needed. The helper must ship with the application; in-process custom urllib openers are not inherited.

Pending Canvas endurance completion, final integration review, commits and production release checks. No reliability release is claimed by this draft.

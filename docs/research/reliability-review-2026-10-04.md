# Atlas reliability review — 4 October 2026

Status: integration and release verification in progress. Review started at 03:24 UTC; this report is updated as checks finish.

## Scope and release boundaries

The review covers the production Worker and browser UI in `feat/atlas-production-performance`, and the local model, recommendations, ingestion and resolution pipeline in `feat/research-recommendations`. The main user checkout contains unrelated work and is left untouched.

Production retains the white background, dark green lotus, earlier multicolour palette, fixed node positions, camera orbit/pan/zoom, 10,000 public HGNC nodes plus 35 reviewed GRIN nodes, and the private ProposalInbox Durable Object. Ask Atlas on Cloudflare remains deterministic reviewed-source lookup. Live TopK, Codex and Whisper remain local services; this review does not claim they run inside the Worker. The GRIN annotations are source-audited; independent expert review is still pending.

## Findings and changes

| Area | Failure addressed | Verification |
| --- | --- | --- |
| Workspace persistence | Stale server instances could overwrite review history; partial and late job writes needed stronger handling. | Atomic file replacement, file/directory fsync and disk compare-and-swap under a stable lock; stale instances, failed persistence and overlapping revisions covered by regressions. A post-rename sync failure keeps the committed revision and explicitly reports saved-but-durability-unconfirmed state. |
| Evidence and recommendations | Unknown scope, variant-specific capabilities, access conflicts, stale review versions and unverified retrieved text could overstate readiness. | Scope gates, current-version excerpt binding, active counterevidence selection and recomputed assessments; adversarial recommendation and assistant tests. |
| Retrieval and model boundaries | Failed searches could remain cached; SDK and model response errors were not consistently bounded or safe to display. | Retry expiry, refreshed local corpora, bounded structured responses and safe errors. A real TopK/Codex smoke test passed in an isolated temporary workspace. |
| Ingestion and resolution | Resume and artifact paths could accept stale source state, corrupt offsets or inconsistent identities/provenance. | Source checksums keyed by complete file identity, exclusive builders, offset and gzip-cache receipts, schema/key guards before writes, atomic artifacts, exact PMCID matches, and validation of source quotes, versions, aliases and references. Swapping a valid gzip seek cache could silently substitute another source’s text; the new regression proves the receipt check blocks this. |
| Acquisition and extraction | Incomplete byte ranges and repeated pagination could claim completeness; duplicate HPOA headers could erase a NOT qualifier; repeated extraction IDs could hide altered provenance. | Range/validator checks, distinct IDs and stable provider totals, cursor-cycle guards, exact raw HPOA rows, snapshot-bound extraction and collision rejection. All JSON metadata is validated before persistence; JSON-LD retains source versions. |
| Database selection | Opening the wrong SQLite file could add curated tables to an unrelated database. | Schema guard runs before writes; byte-for-byte preservation regression. Actual 4.5 GB harvest database passed read-only SQLite `quick_check`. |
| Clustering | Complete-link clustering repeatedly recomputed merge distances and admitted features with only retracted support. | Cached linkage distances with deterministic tie ordering; active supporting evidence required. Exhaustive five-node tie checks match the earlier method. A 500-disease dense fixture improved from 22.31 to 1.57 seconds with identical output. |
| Graph and chat UI | Graph refreshes could move nodes or lose selection; stale searches/jobs could overwrite newer scopes; temporary errors could silently change chat mode. | Request invalidation, preserved world coordinates, bounded pointer state and job reconnection; offline browser regression suite and sustained dense-graph interaction tests. |
| Public API and proposals | Ambiguous query parameters, missing focus anchors and malformed/oversized proposal bodies could produce inconsistent results. | Shared validation, scoped coverage gaps, bounded streamed bodies, durable validation and retry-safe receipts. Local Worker restart preserved receipt IDs. |
| Build and deployment | Stale generated assets, unverified source caches and concurrent edits could enter releases. | Independent file allowlists, pinned public data receipts, input/output hashes, atomic complete builds and a shared build/upload lock. An independent vendor verifier authenticates every installed file against the SHA-pinned SDK wheel; forged RECORD metadata and extra files are rejected. |

## Observed runtime evidence

- Ten-minute WebGL interaction run: 10,000 nodes and 5,346 edges retained, 961 cycles, stable world coordinates, zero browser exceptions, suspend/resume passed. Post-GC heap stayed approximately 11.6 MB. This is one local run, not a guarantee for every device.
- Twenty-minute Canvas interaction run: 10,000 nodes, 5,346 edges, 1,920 interaction cycles, 48 pinch gestures and 192 chat open/draft/close cycles; zero browser exceptions. All 32 tracked DOM targets kept their world coordinates. Post-GC heap grew about 198 KB (1.7%). Startup-only changes landed after this tab loaded and passed separate regressions.
- Eight-minute real-server read exercise: eight concurrent readers, 137 successful HTTP requests, zero failures, final graph 10,000 nodes, and unchanged saved workspace revision/hash. Read-request p95 was 33.7 ms on this host. Memory levelled off after warm-up; the final dense graph fetch allocated another 3.4 MiB. This is not a capacity test.
- Real Ask Atlas question about EPG5/autophagy: TopK retrieval 443 ms, Codex `gpt-6-astra` answer approximately 19.5 s, end-to-end 20.31 s. Three citations from one public source retained `unreviewed_discovery` classification. The completed answer and run persisted at revision 1 in a temporary workspace; no production data, search indexes or saved research workspace were changed.
- Actual resolved artifact passed validation with 1,056 nodes and 2,734 claims. Actual harvest SQLite `quick_check` returned `ok`. Its schema also passes the new key/column contract. A real HGNC row passed source-SHA authentication: cold read 68 ms, repeat read 42 ms.
- Twelve separate processes raced to save the same temporary workspace revision: exactly one committed, eleven stale writes were rejected, the saved winner remained intact, and no temporary files remained.
- Cached local Whisper `small.en` processed a one-second silent fixture in 0.87 s with an empty transcript, without downloading a model or recording a microphone. This verifies local loading and a silent-input path, not speech accuracy.

Machine-readable reports accompany this document in `docs/research/`.

## Remaining limits

- Citation and exact-span validation prove provenance, not that every model interpretation follows scientifically from its sources. Scientific review remains necessary.
- Legacy gzip seek caches without authenticated receipts are bypassed; reading late source rows can therefore take longer until explicit regeneration. Source files are hashed once per filesystem version. Topology and entity-search paths do not read those source rows.
- Existing completed legacy offset indexes lack the new checksum receipts. Bounded monotonic checks remain, but coordinated corruption in multiple legacy rows requires a verified rebuild or migration to rule out fully. New/resumed indexes receive receipts.
- Interrupted local in-memory model jobs do not survive a process restart. They do not remain permanently running, but an explicit durable interruption audit is not yet recorded.
- Acquisition still requires one process per source. Artifact replacement and manifest publication are separate operations; an interruption between them may require a rerun, but status remains incomplete and the previous checksum cannot certify replacement bytes. No live provider acquisition was performed during this review.
- File locking uses POSIX `flock`; Windows requires a portability layer. Snapshot rename durability also depends on filesystem/storage guarantees; newly created ancestor directories are not recursively synced.
- Approximately 1.3–1.4 GB of disk space remained during this audit, including after removal of the temporary CI exports/environments. No full real-corpus rewrite or cache migration was attempted; the source and corpus were kept read-only.
- Cloudflare rejected an optional generic Python HTTP check with error 1010. Production verification therefore uses the successful live browser checks; no direct HTTP endurance result is claimed. Edge rules were unchanged.
- Synthetic benchmarks and offline browser fixtures do not replace device diversity, production load testing or a multi-user deployment design. The local research server remains a trusted single-user service.

## Final verification and release

Final integrated Python 3.11 and 3.14 checks: production 300 tests (155 application/build/vendor, 74 harvest, 15 search, 56 benchmark); local 419 discovered tests (330 application, 74 harvest, 15 search), with one explicit optional audio-decoder skip in the lightweight CI environment. The audio-decoder path and cached Whisper model were also exercised in the optional-dependency environment. Both final matrix runs passed. Follow-up test-only SQLite cleanup removed resource warnings; no runtime module changed.

Node 20 browser checks passed: production 64 (27 WebGL, 27 Canvas, 7 proposal, 3 cluster under generated CSP), local 54 (27 per renderer). Genuine WebGL context loss switched to a working Canvas renderer while preserving camera, selection and world coordinates. These offline suites require neither the ignored real corpus nor model credentials.

The local app was restarted after the application fixes: policy `assay-reuse-v3`, model available, saved workspace revision 3 and SHA-256 unchanged. CI now runs the offline Python matrix and browser checks on pushes and pull requests, with read-only repository permissions and retained test logs. Commands: `bash scripts/check-reliability.sh python` and `NODE_PATH=<Playwright node_modules> bash scripts/check-reliability.sh browser`.

OpenAI total deadlines now use a small isolated stdlib helper process, covering DNS, connect, TLS, status/headers, chunk metadata and body reads. Timeout kills and reaps the helper. Local transport regressions passed; no paid OpenAI call was needed. The helper must ship with the application; in-process custom urllib openers are not inherited.

Production version `ab5a8ebd-8a82-48d4-ad4c-36f767beb089` is deployed at 100% traffic from commit `0228845`; graph/theme, scoped ARX coverage-gap answer, proposal form and exact source/comparator evidence have passed live browser checks. Rollback is `f5d059b4-8b9a-4748-bffa-8d720294e332`. The private Durable Object and domain routes remain intact.

After the final extraction/model/store changes, a fresh build produced the same 36 generated file hashes as the deployed release. Vendor verification again authenticated all 29 installed files against the pinned wheel. The preserved release manifest records the exact deployed input state; build-time-only follow-up fixes therefore require no second deployment.

All application fixes are committed and pushed: production `2968748` (following deployed runtime fixes in `ad23ebc`/`0228845`), local research `bf9d4a5`. Hosted GitHub Actions passed all three jobs on both exact commits: [production run](https://github.com/lukaschudy/LIT-knowledge-graph/actions/runs/37176289095), [research run](https://github.com/lukaschudy/LIT-knowledge-graph/actions/runs/37176399846). The research run was explicitly dispatched after its push did not create an Actions run. The validation JSON includes commit IDs, suite totals and log hashes.

Runtime endurance and final integration are complete. The audit-only Cloudflare preview was stopped; the live site and local research server remain running. Final review-window completion is recorded below.

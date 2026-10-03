# Local research workspace

The current workflow is a local workspace for following a bounded rare-disease research question from source snapshots through machine-proposed claims, human review, assay-reuse gates, and an editable cited brief. It requires Python 3.11 or later and uses the standard library for this workflow. Start it from the repository root:

```bash
python3 -m atlas research --workspace /tmp/atlas-vici-session.json
```

Open <http://127.0.0.1:8767/research>. The server binds to loopback by default and stores review records and brief edits at the workspace path. Choose a private, persistent path if the work should survive a reboot; a new workspace path starts a clean review history. The default inputs are `data/curated/neuro_bundle.json`, `data/curated/neuro_documents.json`, and `data/curated/neuro_request.json`. Override them with `--bundle`, `--documents`, and `--request`; change the port with `--port`.

The default curated source slice contains real literature snapshots relevant to EPG5/Vici and assay context. It is a small, selected evidence slice, not a complete literature search. The separately bundled `data/fixtures/recommendation-demo.json` and the legacy graph demo are fictional acceptance data. The workspace displays the loaded dataset label and synthetic status so those contexts remain distinct.

## Model provider

Opening the workspace, reading its current state, editing the question, assessing known evidence, searching the loaded documents locally, and preparing the deterministic gap brief do not call a generative model. Extraction, AI brief drafting, and the single bounded follow-up investigation do. Those are explicit user actions in the interface.

Provider selection defaults to `auto`: it uses `OPENAI_API_KEY` when present, otherwise it checks whether the Codex CLI is installed and signed in. The CLI runs locally and uses its configured Codex service account; inference is not performed on the workstation. Set the provider explicitly when desired:

```bash
python3 -m atlas research --provider codex --workspace /tmp/atlas-vici-session.json
```

For the OpenAI API, set `OPENAI_API_KEY` in the environment that starts the server and use `--provider openai`. The key stays on the server; never put it in a page, command-line argument, or repository file. API use may incur charges under the configured account. When you invoke an AI action, the relevant source text and task context are sent to the selected provider. The OpenAI adapter sets `store: false`. The default model is `gpt-6-astra`; `--model` can select another supported model, and `--model-timeout` sets the request timeout in seconds. If no provider is available, the workspace still shows its loaded records and deterministic assessment, while model actions report unavailable rather than pretending to run.

A standalone smoke run using the signed-in Codex CLI provider extracted three grounded claims from a WDR45 source in 10.896 seconds. In a separate HTTP workflow smoke run, extraction took 21.017 seconds and AI brief drafting took 24.908 seconds; all three new claims remained unreviewed and all three candidates still needed clarification. These runs confirm individual requests completed, not scientific validity, general latency, or comparative performance.

After refining gap selection, a live maintainer/access investigation returned zero additions in 3.672 seconds because the selected source did not answer those questions. The app kept the candidates unresolved and generated an updated cited brief. The [sanitized development-run record](research/workspace-smoke-2026-10-04.json) includes the earlier failed extraction and subsequent successful runs, test scope and remaining limits.

## Follow the workflow

1. **Frame the request.** Set disease, mechanism, biological step, readout, species, tissue/cell context, and optional stage. Reassessment applies the exact supplied context; it does not infer ontology equivalence.
2. **Inspect sources.** The current `local_lexical` retriever searches only the loaded document snapshots and displays exact passages with source and offsets. Its score is a ranking aid, not scientific confidence. Coverage counts describe this loaded slice only.
3. **Extract one paper at a time.** Each extraction proposes claims tied to its selected source. The structural and exact-quote checks do not establish that an interpretation is correct.
4. **Review each claim.** Approval requires the reviewer to attest that they checked the source and interpretation and to enter a rationale. Rejected claims leave the active assessment but remain part of the workspace record. These local attestations record a person's decision; the application does not authenticate identity, qualifications, or scientific expertise.
5. **Assess candidate reuse.** The broad shared-pathway baseline helps find candidates; it does not check assay eligibility. Candidate cards expose evidence, mechanism/context, access, maintainer, and exclusion gates. `Ready for discussion` describes a feasibility conversation only. Missing gates remain visible, and a failure or empty result is not proof that a biological path cannot work.
6. **Investigate a decisive gap when useful.** Search targets missing facts or disputed evidence, skipping tasks that only require human review. The action is limited to one source pass. New extracted claims still require human review. A source with no answer returns no additions; it does not automatically resolve a gap or approve a candidate.
7. **Prepare the brief.** The deterministic draft cites the active assessment. The optional AI draft remains an unverified interpretation. Edit and save it in the local workspace or download Markdown. Regeneration replaces the draft from current evidence. A changed source/review snapshot marks an older brief stale.

Neither a claim, candidate, nor brief promises treatment benefit, proves transfer of an assay between biological contexts, or provides clinical advice. Check each source and interpretation before relying on a research lead.

## Retrieval and indexing status

The default interactive workspace uses `local_lexical` retrieval over supplied documents. `--retrieval topk` selects the optional TopK semantic retriever. This does not create or populate an index: indexing is a separate operation, and TopK has not been verified against a live account in this project.

To prepare a TopK index, install the optional SDK, configure the three environment variables, and run the separate indexing command yourself:

```bash
pip install '.[topk]'
export TOPK_API_KEY='…'
export TOPK_REGION='…'
export TOPK_COLLECTION='…'
python3 -m atlas index-research --documents data/curated/neuro_documents.json
```

This command explicitly writes the supplied document snapshot to the configured remote collection. Check your TopK account terms and charges before running it. To use that index, start the workspace with `--retrieval topk`; without this flag it stays local:

```bash
python3 -m atlas research --retrieval topk --workspace /tmp/atlas-vici-session.json
```

TopK search is scoped to the workspace corpus identity, and each returned passage is checked against the local source manifest and exact source text. Remote index coverage is unknown; an integration error is reported as a TopK failure and never silently relabeled as local search. The current CLI options are `atlas research --retrieval local|topk` and the explicit `atlas index-research --documents PATH` command.

For the deterministic four-case acceptance example and engine details, see [the decision-engine guide](architecture/decision-engine.md). For the larger proposed research loops, see [the architecture overview](architecture/recommendation-loops.md).

## Persistence and current limits

Run one server process per workspace file. Edits to the question, reviews and briefs persist across restarts with the original seed inputs. Changing the seed bundle, documents or initial request requires a new workspace path; the application refuses to silently reuse earlier reviews for a different seed. Source-refresh ingestion and a background update watcher are not part of this interface.

Extraction currently links existing registered entities; it does not automatically create new diseases, researchers or assets. Clustering computes an explainable neighborhood within the supplied disease slice, not the entire harvested corpus. The default slice is four selected papers, three disease neighborhoods and three assay candidates; maintainer/access evidence and qualified scientific reviews remain missing. The shared-pathway baseline is a candidate lookup, not a competitive RAG benchmark. A held-out comparison is still needed to measure an advantage.

## Verification

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s tests_harvest -v
python3 scripts/build_source_guide.py --check
node --check atlas/web/research.js
```

An optional read-only browser smoke test checks page rendering, the source dialog and desktop/mobile widths. With Playwright installed separately and its Chromium browser downloaded, run `node scripts/check_research_browser.cjs` against the running local workspace. Set `NODE_PATH` if Playwright is installed outside the repository, or `ATLAS_URL` to select a different local URL. This check does not run models, edit briefs or approve evidence.

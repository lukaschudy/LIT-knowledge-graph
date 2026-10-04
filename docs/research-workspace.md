# Connected Atlas workspace

The main graph at `/explore` now connects the source catalog, Astra, claim review and deterministic research planning. `/research` redirects to the graph; there is no separate research page.

## Run locally

From the repository root with Python 3.11 or later:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[topk]'
.venv/bin/python -m atlas app --env-file .env --search topk --provider codex
```

Open <http://127.0.0.1:8767/explore>. The artwork cover remains at `/`. Save `TOPK_API_KEY` and `TOPK_REGION` in an ignored `.env`. The local GRIN export at `data/processed/search/grin-passages.jsonl.gz` must match the tracked receipt; see [TopK setup](topk-search.md) to prepare it. Remote results are checked against this export before they can become citations. Starting the app performs no indexing writes.

`--provider codex` uses the signed-in local Codex CLI through isolated, read-only `codex exec` calls. `--provider openai` uses `OPENAI_API_KEY`, read from the environment or the specified `.env`. The default model is `gpt-6-astra`; `--model` and `--model-timeout` configure it. Provider failures remain visible. The app never substitutes a canned answer for a failed live model call. A hosted backend needs its own model access; a static deployment cannot use this computer's Codex login.

For explicit offline retrieval, use `--search local`. This still needs a model for AI actions; it labels passage retrieval `local_lexical`. `--search auto` selects TopK when credentials exist, otherwise local retrieval. The older `research` CLI command is an alias for `app`.

## What is connected

- **Graph:** the default combines the real neuro and GRIN curated bundles: 45 entities, 53 assertions and 16 sources before session changes. The displayed graph updates after extraction or rejection.
- **TopK:** 15,502 GRIN passages and 19 chunks from four neuro source snapshots are separate collections. The neuro read-back checks every field, and its semantic queries use strong consistency so recent writes are searchable. Index receipts are in `data/curated/topk-*-index.json`.
- **Ask Atlas:** selected-node graph context and retrieved passages go to Astra. Software validates returned graph IDs and citation numbers. Source cards retain exact canonical passage text, source URL, locator and review classification. This verifies provenance, not the correctness of every model interpretation.
- **Literature:** search either scope from the graph drawer. “Use passage” imports the catalog's canonical text as a versioned source. Curated annotation cards link to existing claims; they cannot be imported as if they were original paper text.
- **Extraction and review:** Astra proposes typed claims over registered entities. Each accepted proposal needs an exact, unique source span and remains unreviewed. Review requires an explicit person, rationale and source attestation. Rejected claims leave the active graph but stay in the audit history.
- **Plan:** contextual gates assess assay fit, contradictions, review, maintainer and access evidence. Missing facts stay unresolved. One explicit investigation searches the catalog, imports at most one eligible source passage and extracts against the current gaps. It cannot approve its own output.
- **Brief:** generate deterministic Markdown, request an AI draft, edit, save and download it. Evidence or question changes mark an earlier brief stale.

The selected planning scope remains EPG5/Vici, with WDR45/BPAN and AP4B1/SPG47 comparators. GRIN supplies an additional search and graph slice. A shared pathway or retrieved passage does not establish transferability. Real maintainer/access evidence and qualified scientific reviews are still needed before the neuro candidates can be ready for discussion.

## Demo sequence

1. Enter the main graph. Search/select **GRIN2B** and ask what the evidence says about **S541R**, including uncertainty. Open its citations.
2. Open **Research → Literature**, search **EPG5 Vici autophagy fusion**, and use a source passage. Extract it; inspect the exact source span and the new unreviewed assertion.
3. In **Evidence / review**, inspect the source and record a decision only if you have actually reviewed it. Rejection removes the edge from the active graph.
4. Open **Plan** to see the Vici request and separate passed, blocked and unresolved gates. Run one gap investigation if useful; zero additions is a valid result when a passage does not answer the question.
5. Open **Brief**, edit and download a cited discussion draft.

Use the fictional acceptance fixture for a staged ready-for-discussion demonstration. Do not present fixture approvals as expert review of real papers. The wider harvest contains 21,746,825 normalized records; it has not all been indexed or extracted into this graph. The broad-pathway baseline is a candidate lookup, not a measured comparison with other products; 10× remains an evaluation target.

## Persistence and limits

The default workspace is `data/workspaces/atlas.json` (ignored). `--workspace PATH` selects another file; `--bundle`, `--documents` and `--request` override the seeds. Run one server process per workspace. Writes are atomic and revision checked. A changed seed requires a fresh workspace so old review decisions cannot silently apply to new evidence. Imports retain source identity, content hash, original locator, URL and license. The workspace accepts up to 50 source documents.

This local server binds to loopback. It is not a multi-user authenticated service. Review attestations record a person's decision without authenticating expertise. Bulk source refresh, automatic entity creation and a background maintenance watcher remain future work.

The [sanitized integration run](research/integrated-smoke-2026-10-04.json) records live TopK retrieval, Astra chat, source import/extraction, bounded investigation and brief generation. Timings are from individual development calls.

## Verify

```bash
python3 -m unittest discover -s tests -q
python3 -m unittest discover -s tests_harvest -q
.venv/bin/python -m unittest discover -s tests_search -q
node --check atlas/web/graph.js
node --check atlas/web/workspace.js
```

With Playwright installed separately and Chromium downloaded, run `node scripts/check_research_browser.cjs`. `NODE_PATH` may point to its modules; `ATLAS_URL` selects another local server. This browser smoke check uses the main graph and does not approve evidence or invoke models.

To explicitly index the four neuro snapshots into their dedicated collection:

```bash
.venv/bin/python -m atlas index-neuro --env-file .env
```

This is a remote write; ordinary app startup and search do not call it. See [decision-engine details](architecture/decision-engine.md) and the [architecture loops](architecture/recommendation-loops.md).

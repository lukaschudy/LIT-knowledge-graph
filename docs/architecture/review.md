# Critical architecture review

Independent review of the repository against the challenge brief and published judging criteria. Snapshot: 4 October 2026.

## Verdict

The architecture is unusually rigorous for a hackathon, but "innovative" is the wrong axis — and rigor alone probably will not win. The evidence model is better designed than what most teams will ship, but there is **zero AI in the running product**, and the brief says challenge-track prizes require OpenAI models. That is the gap that matters most, and it is fixable because the right boundary is already built.

## What is genuinely differentiated

1. **Claim-level evidence integrity is real, not slideware.** Nodes, claims, evidence, sources and coverage are separate first-class objects, with `stance` (supports/contradicts), `review_status`, `assertion_type` (reported vs. inferred) and context qualifiers (effect direction, species, tissue, stage, negation) in `atlas/model.py`. Most competitors will dump LLM-extracted triples into a graph store and call it a knowledge graph. This repo can actually answer "why do you believe this edge?"

2. **Conservative compatibility gating is the strongest scientific feature.** The reasoner rejects opposite variant effects, downgrades unknown effects to `needs_review`, treats phenotype overlap as context-only and keeps contradictions visible — see `_candidate_mechanisms` in `atlas/reasoning.py`. The GRIN dataset makes this concrete and dramatic: **S541R vs. S541G — the same residue, opposite functional effect** — exactly the "names hide mechanisms" insight the brief asks for. That is a better demo moment than most teams will have.

3. **The extraction grounding boundary** (`atlas/extraction.py`) — exact character-offset span validation plus a SHA-256 snapshot digest — is a real anti-hallucination gate. Few teams at this hackathon will have one.

4. **Honest abstention as a product state.** Coverage records and the "no supported route" flow directly implement Module 2 of the brief, which most teams will skip because it is unglamorous.

5. **The harvest is massive and honest.** ~14.2M normalized records across all 21 PDF-named sources, with permission gaps recorded rather than hidden (`docs/harvest-coverage.md`). The GRIN cohort has real primary assay data with wild-type controls — actual curation, not vibes.

## What hurts the chances — critically

1. **No AI anywhere in the shipped product.** This is the biggest problem. `atlas/questions.py` is regex matching ("No language model or external requests"), `atlas/extraction.py` validates proposals but nothing generates them, and the docs repeatedly admit "the prompt alone does not satisfy the challenge's OpenAI prize requirement." Judges will ask "where does the AI do something?" and right now the answer is "it is documented in a proposal." This risks both the eligibility bar and the ambition criterion.

2. **The differentiator is invisible unless dramatized.** "We don't hallucinate connections" loses to a slick GraphRAG demo unless the judge *sees* the naive approach fail. A conservative rejection looks boring next to a competitor's confident (wrong) answer — unless both are shown.

3. **The scale story is disconnected from the product.** 14M records harvested, but the queryable real graph is 35 entities / 44 claims, and the impressive 471-entity demo is fictional. Judges see the small graph; the harvest is invisible. Two separate databases on two ports makes this worse — the polish and the truth live in different demos.

4. **"Graph analytics" is thin.** The reasoner does bounded traversal and rule-based gating — no clustering algorithm, no embeddings, no community detection. The brief explicitly asks for graph analytics revealing clusters. The cohorts are curated, not discovered. Defensible scientifically, but a team showing community detection over 100k nodes will *look* more like an atlas.

5. **The collaboration brief is not fully wired.** `data/curated/grin_research_proposal.json` exists as a file, but the UI only surfaces `opportunity.proposal` as one paragraph — there is no editable/shareable brief in the frontend, which `docs/frontend-strategy.md` itself calls "the strong demo moment."

6. **Repo hygiene for submission.** There is one unpushed commit and uncommitted/untracked files including the explorer UI (`graph.js`, `records.html`, `questions.py`, `demo.py`). The repository is a scored deliverable — push it.

## Scorecard vs. the published criteria

| Criterion | Assessment |
|---|---|
| Graph quality | Strong design + counterexamples; weak on scale/discovery |
| Evidence integrity | Best-in-class — clearly the top criterion |
| Patient progress | Complete real journey exists (GRIN2B → 2A → registry → partner → question) |
| 10× impact | Honestly framed but unmeasured — judges may discount it |
| Ambition & craft | Clean UI, but "ambition" suffers with no live AI |

## Highest-leverage actions, in order

1. **Wire one real OpenAI call through the existing boundary.** Run `prompts/claim-extraction.txt` against one real GRIN paper, feed proposals through `ground_proposals` (it already rejects bad spans), and show unreviewed extractions marked as such in the UI. That converts "no AI" into "AI with a verification boundary nobody else has" — which *is* the innovative story.

2. **LLM-write the path explanation and the Ask Atlas fallback**, with generated sentences required to cite claim IDs that resolve. Keep the deterministic path as a fallback; demo the comparison.

3. **Merge the demo story:** make the GRIN real-data dataset the primary demo through the polished explorer UI.

4. **Surface harvest scale in the UI** as a coverage panel: "54k publications, 9.2M ClinVar rows searched — here is what is missing." That turns invisible work into evidence integrity made visible.

5. **Dramatize S541G vs. S541R** in the video: same residue, opposite effect — naive clustering merges them, the atlas separates them. One sentence a judge remembers.

6. **Do one informal 10× measurement** — time the GRIN question answered manually vs. via the atlas. Even n=1 with real numbers beats "target, not measured."

7. **Commit and push everything** before submission.

## Bottom line

Is it innovative enough? **The concept is not novel — GraphRAG with provenance is well-trodden. But the honesty architecture is genuinely unusual, and the counterexample-driven demo is a real differentiator.** Right now it is a beautifully governed answer to a question nobody asked live, because the AI half exists only in docs. The single highest-leverage move is making one model call flow through the grounding boundary — then the pitch writes itself: *"Every other atlas will show you a connection. Ours is the only one that can prove it — or tell you honestly that it can't."*

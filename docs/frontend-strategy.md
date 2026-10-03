# Frontend strategy: a research path a patient group can act on

Research date: 3 October 2026. Decision proposal for the **AI Atlas for the World’s Rare Diseases** challenge.

## Recommendation

Build a **Research Path workspace**: unified search → understandable opportunity → inspectable evidence path → asset comparison → collaboration brief. Make a small, stable graph the visual explanation of the opportunity. Keep the broader atlas available as a secondary exploration view.

The product promise: **“Find related research, understand why it matters, and prepare your next step.”**

This is a design recommendation inferred from the brief and the sources below, not a tested finding that this particular layout wins competitions. The brief supplies no judging weights. Optimize for demonstrable patient progress and evidence integrity across all five criteria.

## What the PDF actually requires

Primary source: [original six-page brief](../Knowledge%20graph), with [extracted text](../data/source/challenge-brief.txt). Page numbers below refer to physical PDF pages.

| Requirement | Frontend consequence | Demonstration |
|---|---|---|
| Maria leads the journey; other personas support it (p.3) | Default to patient-group tasks; offer scientific detail within the same workspace | A non-specialist can name an actionable opportunity |
| Meaningful paths and mechanism-aware clusters (pp.3–4, 6) | Show direction and scope of variant effects; explain cluster membership | One cross-gene connection and one excluded counterexample |
| Source, date, confidence, observations vs inference, contradictions (pp.3–5) | Selectable relationship labels open a claim-level inspector | Open the exact evidence and a limitation without leaving the path |
| One global search and progressive reveal (p.5) | Search disease/gene/phenotype/group/mechanism, resolve aliases visibly | A synonym lands on the same canonical entity |
| Shared assets, partners, next experiments (pp.4–6) | Compare reusable components and blockers; produce a sourced research brief | Maria identifies an asset owner and a specific question to ask |
| Honest absence of a supported route (pp.4, 6) | Show coverage, unavailable sources, missing links and a next research question | A separate no-route example remains useful |
| Meaningful 10× milestone (pp.5–6) | A transparent time-to-milestone comparison with assumptions | Show what is accelerated and which work remains |
| Working prototype and one-minute walkthrough (p.6) | No login before exploration; stable demo dataset and shareable state | Complete one journey live in under a minute |
| Use OpenAI models/tools for track-prize eligibility (p.5) | Connect the explanation to traceable extraction/reconciliation work | Show generated explanation linked to retrieved claim IDs |

The page-4 diagram is explicitly a starting point, not a required layout. Its centrality score and cluster sidebar need not become the default. The accompanying mechanism counterexample is more important to preserve than its visual styling.

## What to borrow from existing tools

| Reference | Observed/documented pattern | Adaptation for this challenge |
|---|---|---|
| [Open Targets](https://platform-docs.opentargets.org/web-interface) | Unified search provides entry into evidence-oriented tools | Keep one search and stable entity pages; translate evidence into patient-group decisions |
| [NIH Translator relationship evidence](https://ui.ci.transltr.io/relationship-evidence) | Its indexed guide describes clicking relationship terms to inspect publications, studies and source databases | Make the *edge* inspectable, with contradiction and applicability alongside support |
| [Monarch Phenogrid](https://monarch-app.monarchinitiative.org/Phenogrid/) | Compares phenotype sets in a grid | Use a focused comparison to explain similarities and differences; keep phenotype similarity distinct from mechanism compatibility |
| [RARe-SOURCE](https://ncats.nih.gov/research/research-activities/rare-source) | Combines rare-disease information to reveal molecular connections | Integration alone is an established direction; emphasize the path from discovery to a reusable asset and partnership |
| [Nielsen Norman Group: progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/) | Start with core functions and reveal advanced detail on demand | Show the opportunity first, scientific depth on selection, while retaining material caveats in the summary |
| [W3C cognitive accessibility guidance](https://www.w3.org/WAI/WCAG2/supplemental/objectives/o3-clear-content/) | Simple language, short chunks, clear layout and whitespace aid understanding | Use familiar task labels, short explanations and inline definitions |

Verification limits: this was desk research, not a comparative usability study. Translator's production homepage was inspected in a browser; it offered examples and required login for a new search. The edge-inspector description comes from its indexed official CI guide; direct text retrieval of that guide returned an app shell. Other comparisons use official documentation, not claimed end-to-end product testing. No patient interviews were conducted. Agent-reach/mcporter were unavailable, so research used the available web search/browser tools.

## Choose the interface around the task

| Candidate | Useful for | Risk for this challenge | Decision |
|---|---|---|---|
| Large free-form graph | Expert discovery and overall structure | Maria must discover which path matters and what to do | Secondary Explore view |
| Chat as the main interface | Follow-up questions in familiar language | Important entities, evidence and comparison state become buried in turns | Optional contextual helper |
| Search results and tables | Scanning assets and comparing candidates | Relationships and causal qualifications become hard to follow | Use for results and comparisons |
| Guided workspace with linked graph and evidence | Understanding a lead, checking it and acting | Requires disciplined scope and clear state | **Primary interface** |

These are design tradeoffs, not experimentally measured scores. The workspace should allow backtracking between evidence and assets; a rigid multi-step wizard would make that harder.

## Screen and interaction specification

### 1. Start with a familiar question

One prominent search: **“Search a disease, gene, symptom, group or mechanism.”** Provide a real, sourced example from the demo dataset. Suggestions show entity type, canonical name and matched alias. Ambiguous aliases require a choice; gene search must expose mechanism-specific disease contexts rather than silently choose one.

Do not require an account, genotype upload or patient history to discover public research. Devon should see an exact-diagnosis community first when one is verified. Related communities must be explicitly labeled as related rather than exact matches.

### 2. Land on an opportunity, with a map that explains it

Persistent top bar: product name, global search and saved brief. Disease header: canonical name, matched alias, scope and data snapshot date.

At desktop widths, use a central workspace plus a contextual evidence panel. A compact results rail can appear when there are several leads; avoid three permanent dense columns. At narrow widths, stack the opportunity, path and evidence in reading order.

Default workspace sections: **Connections · Shared assets · People · Next step**. These are different views of the selected opportunity and retain its context.

Each opportunity answers:

- What is the possible shared research opportunity?
- Why did it appear? Show mechanism, informative phenotype overlap and relevant infrastructure separately.
- What differs or could rule it out?
- What can the group investigate this week?

Start with roughly 6–10 visible nodes as a prototype design constraint, not a universal usability rule. Use a deterministic layout, labeled directed edges and one selected path. Expand adjacent evidence or entities on request without moving everything else. Clearly label screen direction separately from the biological predicate: an exploratory route is not necessarily a causal chain.

Do not size nodes by “importance” or rank disease opportunities by publication count alone. Those choices can privilege already well-studied diseases. Offer an explicit explanation of ranking dimensions: mechanism support, phenotype specificity, asset applicability, unresolved evidence and source coverage.

### 3. Make every edge inspectable

Selecting a relationship or its equivalent text row opens the same evidence inspector:

1. Plain-language claim and relationship type.
2. Context: variant/effect, species, disease subtype and relevant population when available.
3. Supporting evidence with source title, stable identifier, date, link and a short supporting passage or source field.
4. Contradictory findings and their scope; unresolved disagreement stays visible.
5. Assertion type: reported or inferred. Review state is separate.
6. Confidence and its basis. If confidence is numeric, identify what it measures and how it was produced. Never label extraction confidence as a probability of treatment success.
7. “What would change this conclusion?” and the next verification question.

Keep three independent axes: **reported/inferred**, **supported/mixed/insufficient evidence**, and **unreviewed/machine checked/human reviewed**. A source-reported claim can still have weak or contradictory evidence. A human-reviewed label requires a recorded review; source indexing does not confer it.

Use solid vs dashed lines for reported vs inferred relationships, with text labels. Contradictions get an explicit marker and wording; color alone is insufficient. Do not average away a weak critical edge into an apparently strong overall route. Show the weakest relevant link and unresolved blockers.

### 4. Make asset reuse concrete

An asset needs an owner, source and last-checked status. “A registry exists” is different from “its data are available for our use.”

| Asset detail | What Maria needs to see |
|---|---|
| What might transfer | E.g. a questionnaire, data dictionary, assay protocol or study design, supported by its actual source |
| What does not automatically transfer | Disease-specific endpoints, variant context, permissions, population eligibility, sample availability |
| Access | Public download, request access, public contact or unknown |
| Applicability | Verified within stated scope, candidate reuse requiring review, or unsupported |
| Next action | Ask the owner a specific question, supported by the comparison |

Use a side-by-side comparison with rows for variant effect, pathway, informative phenotype, study population, asset scope and unresolved questions. Show missing data explicitly. A disease neighbor or shared researcher does not establish scientific interchangeability or willingness to collaborate.

### 5. Finish with a collaboration brief

Primary action: **“Prepare collaboration brief.”** Produce an editable, printable/shareable summary containing the two communities, rationale with citations, proposed reusable component, differences, unresolved checks, public partner contact, first research milestone and suggested next question. Keep observations, hypotheses and proposed actions distinct.

The strong demo moment is Maria leaving with a proposal she can explain to a researcher. Any outreach remains a draft for her review; contact availability is not a partnership commitment.

### 6. Treat no-route and error states as part of the product

Use: **“We did not find a supported connection in the sources checked.”** Show sources searched, date and scope, sources not searched, failed retrievals, the missing claim and the next question to investigate.

Distinguish an empty result from a timeout or failed source. During loading, show real completed stages rather than invented progress. Allow retry without losing the selected disease. Keep a versioned, clearly dated cached dataset for reliable demos. Do not claim a fresh live search if serving that snapshot.

## Visual direction

Aim for a calm research tool: warm light surfaces, dark readable text, generous whitespace, restrained teal for the selected path, and amber for unresolved evidence. Dark appearance can follow system preference. These colors are proposed design choices, not findings from the references.

Use approximately 16px body text, clear sentence-case labels, modest corner rounding and limited borders. Keep charts stable and remove decorative motion. Explain terms inline: “loss of function — the protein does less than expected.” Add scientific detail without changing the underlying evidence or hiding caveats.

Provide a complete text/list equivalent of the graph, keyboard selection, visible focus, touch-friendly relationship targets and reduced-motion support. Test zoom, small screens and long names. W3C's [use-of-color guidance](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) requires a further cue beyond color; its [target-size guidance](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum) explains minimum sizing and spacing. Aim for 44px touch controls as a design target; do not confuse that target with the 24px WCAG 2.2 AA criterion and its exceptions.

## Frontend implementation choice

For the focused hackathon journey, use **React + TypeScript + React Flow** with a small deterministic layout and regular HTML panels. Use the team's familiar app scaffold; there is no need to add framework complexity for this scope.

| Renderer | Fit | Recommendation |
|---|---|---|
| [React Flow](https://reactflow.dev/learn/advanced-use/accessibility) | Custom interactive nodes, relationship controls, keyboard/screen-reader facilities | Preferred for the focused path. Disable graph editing/deletion and provide a text equivalent; library support does not guarantee app accessibility |
| [Cytoscape.js](https://js.cytoscape.org/) | Network exploration, graph algorithms, many layouts | Prefer if broad network exploration becomes the central product or the team already knows it |
| [Sigma.js](https://www.sigmajs.org/docs/) | WebGL rendering of thousands of nodes and edges | Consider later for a separate large atlas view |

This is a scope-based choice, not a performance benchmark. Do not introduce multiple graph renderers during the initial build.

The existing `atlas/model.py` already separates nodes, claims, evidence, sources and coverage. Build a view adapter around that model. Preserve IDs and map backend predicates to readable relationship labels. Pass claim IDs into explanations and reject citations that do not resolve to retrieved claims. Preserve `synthetic`, `assertion_type`, evidence stance and review flags visibly.

The view layer will additionally need path ordering, ranking reasons, asset applicability/permissions, contact provenance and a structured action brief. Treat these as proposed contracts, not existing backend capabilities. URL state should restore disease, opportunity, selected claim and active view. Version the data used in exported briefs.

## Scope that can win attention in 24 hours

**Must work:** one real sourced cluster, global search with aliases, one cross-disease path, evidence inspector, mechanism counterexample, one sourced reusable asset, one public collaborator/contact, collaboration brief and a useful no-route state.

**If time remains:** saved/shareable view, richer phenotype comparison, ranked mechanism search for Priya, evidence contribution as a draft awaiting review.

**Defer:** full-world ingestion, 3D graphs, live multiplayer, chat as the primary navigation, complex accounts, investor dashboards and patient data uploads. The optional personas should reuse the same entities and evidence, not become four separate applications.

Suggested sequence: first agree the real evidence and counterexample; then build search and workspace; then edge inspection and reuse comparison; then brief and coverage states; finally test and rehearse. Data and scientific verification are dependencies, not final polish.

## Show 10× without overstating it

Pick a named milestone such as **“expert-ready proposal for a shared natural-history study”**. Separate discovery and proposal preparation from scientific review, permissions, recruitment and longitudinal follow-up. Track elapsed time as well as staff effort; parallel tasks must not be added as if sequential.

A numerical illustration only: if measured baseline preparation takes 20 working days and assisted preparation takes 2, that stage is 10× faster. If an unchanged review adds 20 working days, the combined route is 40/22 ≈ 1.8×, not 10×. These numbers are not evidence or a claim about this product. Display assumptions, measurements, ranges and excluded stages; replace the illustration with observed task timings and expert estimates.

## One-minute walkthrough

| Time | What the judge sees | Criterion made visible |
|---|---|---|
| 0–8 sec | Maria searches a real disease alias; the canonical diagnosis is resolved | Product craft |
| 8–20 sec | A related community appears through an explained mechanism path | Graph quality |
| 20–32 sec | Click one relationship, inspect its source and a mechanistic limitation/counterexample | Evidence integrity |
| 32–45 sec | Compare the existing asset, transferable component and required checks | Patient progress |
| 45–55 sec | Prepare a sourced brief with a partner and next question | Concrete shared action |
| 55–60 sec | Show the milestone comparison and explicit validation assumptions | 10× impact |

Keep the no-route example one click away for live questions. Do not invent supporting papers or researcher availability to complete the storyline. The interface concept uses fictional placeholders; a submission must use verified data.

## Validate the decision before committing to polish

Run short formative sessions with a patient advocate or non-specialist and a researcher. Ask each to identify the connection, find its source, explain its uncertainty, name the reusable component and state the next action. Test a mechanism mismatch and a no-route example as well as the successful route.

Proposed acceptance targets: users can identify the next step in under 60 seconds; every displayed critical claim has an accessible source; participants can distinguish a lead from validated applicability; the key journey works using keyboard and at mobile width. These are targets, not results. Record errors and timing, revise the layout, and preserve unresolved scientific limits even when they complicate the story.

## Concept verification

The accompanying interactive concept uses explicitly fictional entities. Browser checks verified relationship selection updates the evidence inspector, the asset comparison opens the collaboration brief, and the mismatch and no-route selectors display their respective explanations. Desktop and narrow-screen rendering were inspected; at a 390px browser viewport the concept's inner width and scroll width both measured 341px. JavaScript syntax and unique HTML IDs were checked. This verifies the concept interactions, not biomedical validity, full accessibility conformance, user comprehension or a working data integration.

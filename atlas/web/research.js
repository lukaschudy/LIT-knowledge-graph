(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const el = (tag, className = "", text = null) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== null && text !== undefined) node.textContent = String(text); return node; };
  const safeText = (value, fallback = "") => (typeof value === "string" || typeof value === "number") ? String(value) : fallback;
  const list = value => Array.isArray(value) ? value : (value == null ? [] : [value]);
  const state = { data: null, busy: false, dirty: false, editVersion: 0, pendingAiDraftAt: null, pollTimer: null, briefDraft: "" };
  const notice = (message, warning = false) => { const n = $("#notice"); n.textContent = message; n.className = warning ? "notice notice--warning" : "notice"; n.hidden = !message; };
  const error = message => { const n = $("#error"); n.textContent = message || ""; n.hidden = !message; };
  const errText = (body, status) => safeText(body?.error?.message, `The request could not be completed (${status}).`);
  const api = async (path, { method = "GET", body } = {}) => {
    const headers = { Accept: "application/json" };
    if (body !== undefined) { headers["Content-Type"] = "application/json"; headers["X-Atlas-Token"] = safeText(state.data?.csrf_token); }
    const response = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) { const e = new Error(errText(payload, response.status)); e.status = response.status; throw e; }
    return payload;
  };
  const revision = () => state.data?.revision;
  const requestData = () => ({ ...state.data?.request, ...Object.fromEntries(new FormData($("#question-form")).entries()) });
  const refresh = async ({ quiet = true } = {}) => {
    try {
      const fresh = await api("/api/research/state");
      state.data = fresh; render(); error("");
      if (!quiet) notice("Workspace refreshed with the latest source and review state.");
    } catch (e) { error(`Could not load the research workspace. ${e.message}`); $("#loading").hidden = true; $("#app").hidden = false; }
  };
  const mutate = async (path, body, success) => {
    if (state.busy) return;
    state.busy = true; notice("Saving this workspace change…"); error("");
    try {
      const next = await api(path, { method: "POST", body: { ...body, revision: revision() } });
      if (next && next.revision !== undefined) { if (path === "/api/research/brief" || path === "/api/research/brief/reset") state.dirty = false; state.data = next; render(); }
      if (success) notice(success);
      return next;
    } catch (e) {
      if (e.status === 409) { await refresh(); notice("The workspace changed while this page was open. It has been refreshed; review the current evidence and try again.", true); }
      else error(e.message);
    } finally { state.busy = false; }
  };
  const count = (value) => value === null || value === undefined ? "—" : String(value);
  const nodeLabel = value => {
    const id = typeof value === "string" ? value : safeText(value?.id || value?.label);
    const node = list(state.data?.nodes).find(n => n?.id === id);
    return safeText(node?.label || (typeof value === "object" ? value?.label : value), "Unlabelled entity");
  };
  const sourceFor = id => list(state.data?.documents).find(d => d?.source_id === id) || {};
  const sourceLink = url => { try { const parsed = new URL(url, location.href); return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : ""; } catch (_) { return ""; } };
  const citeButton = (evidence, claim) => {
    const title = sourceFor(evidence.source_id).title || evidence.source_id || "Source";
    const button = el("button", "citation-link", title.length > 75 ? `${title.slice(0, 72)}…` : title);
    button.title = `${title} · View exact source excerpt and location`;
    button.type = "button"; button.addEventListener("click", () => showEvidence(evidence, claim)); return button;
  };
  const showEvidence = (evidence, claim) => {
    const dialog = $("#evidence-dialog"), detail = $("#evidence-detail"), doc = sourceFor(evidence.source_id);
    detail.replaceChildren();
    const p = el("p", "evidence-source");
    const href = sourceLink(doc.url);
    if (href) { const a = el("a", "", doc.title || evidence.source_id || "Source document"); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; p.append(a); }
    else p.textContent = doc.title || evidence.source_id || "Source document";
    const excerpt = el("div", "evidence-excerpt", evidence.excerpt || "No excerpt was supplied for this evidence record.");
    const locator = el("p", "evidence-locator", [evidence.locator, evidence.source_version || doc.version].filter(Boolean).join(" · "));
    const qualifier = el("p", "evidence-locator", `Claim review status: ${safeText(evidence.review_status || claim?.review_status, "unreviewed")}`);
    detail.append(p, excerpt); if (locator.textContent) detail.append(locator); detail.append(qualifier);
    if (typeof dialog.showModal === "function") dialog.showModal();
  };
  const badge = (label, synthetic) => { const b = el("span", `badge${synthetic ? " badge--synthetic" : ""}`, label); return b; };

  function render() {
    const data = state.data; if (!data) return;
    $("#loading").hidden = true; $("#app").hidden = false;
    const dataset = data.dataset || {};
    $("#dataset-title").textContent = safeText(dataset.title, "Research dataset");
    const datasetBadge = $("#dataset-badge"); datasetBadge.textContent = dataset.synthetic ? "Synthetic demonstration" : "Source dataset"; datasetBadge.className = `badge${dataset.synthetic ? " badge--synthetic" : ""}`;
    $("#dataset-meta").textContent = data.workspace_id ? `Workspace ${safeText(data.workspace_id)}` : `Revision ${safeText(data.revision)}`;
    $("#indexed-count").textContent = count(data.coverage?.indexed_documents);
    $("#acquired-count").textContent = count(data.coverage?.acquired_records);
    $("#reviewed-count").textContent = `${count(data.coverage?.reviewed_claims)} / ${count(data.coverage?.total_claims)}`;
    const model = data.model || {};
    $("#model-mode").textContent = model.available ? safeText(model.provider, "AI available") : "Unavailable";
    $("#model-mode").title = model.available ? `Available provider: ${safeText(model.provider)}${model.model ? ` · ${safeText(model.model)}` : ""}` : "AI extraction is unavailable; check the local service setup.";
    $("#coverage-note").textContent = safeText(data.coverage?.note, "Document coverage is a record of indexed sources, not a measure of literature completeness.");
    const aiButton = $("#ai-draft"); if (aiButton) { aiButton.disabled = !model.available; aiButton.title = model.available ? "Ask the configured model to draft a cited brief. It will remain unverified." : "AI drafting is unavailable because no AI provider is configured."; }
    const investigateButton = $("#investigate"); if (investigateButton) { investigateButton.disabled = !model.available; investigateButton.title = model.available ? "Use one bounded follow-up source pass to investigate unresolved evidence gaps." : "Follow-up investigation is unavailable because no AI provider is configured."; }
    fillQuestion(data.request || {}); renderSources(data); renderClaims(data.claims || []); renderAnalysis(data.analysis || {}); renderBrief(data.brief || {});
    renderJobs(data.jobs || []);
  }
  function fillQuestion(req) {
    ["disease_id", "mechanism_id", "mechanism_step", "readout", "species", "tissue", "stage"].forEach(key => {
      const input = $(`#${({ disease_id:"disease", mechanism_id:"mechanism", mechanism_step:"mechanism-step", readout:"readout", species:"species", tissue:"tissue", stage:"stage" })[key]}`);
      if (key === "disease_id" || key === "mechanism_id") {
        const type = key === "disease_id" ? "Disease" : "Mechanism";
        const prompt = key === "disease_id" ? "Choose a disease" : "Choose a mechanism";
        input.replaceChildren(new Option(prompt, ""));
        list(state.data?.nodes).filter(node => node?.type === type).sort((a, b) => nodeLabel(a).localeCompare(nodeLabel(b))).forEach(node => input.add(new Option(nodeLabel(node), safeText(node.id))));
        const selected = safeText(req[key]);
        if (selected && ![...input.options].some(option => option.value === selected)) input.add(new Option("Current selection (label unavailable)", selected));
        input.value = selected;
        return;
      }
      if (document.activeElement !== input) input.value = safeText(req[key]);
    });
  }
  function renderSources(data) {
    const root = $("#source-list"); root.replaceChildren();
    const docs = list(data.documents);
    if (!docs.length) { root.append(el("div", "empty-state", "No source documents are available in this workspace yet.")); return; }
    docs.forEach(doc => {
      const row = el("article", "source-row"), copy = el("div", "source-copy"), title = el("h3", "source-title");
      const href = sourceLink(doc.url);
      if (href) { const a = el("a", "", safeText(doc.title, "Untitled source")); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; title.append(a); } else title.textContent = safeText(doc.title, "Untitled source");
      const meta = el("p", "source-meta", [doc.source_id, doc.version, doc.license].filter(Boolean).join(" · "));
      copy.append(title, meta); if (doc.text) copy.append(el("p", "source-snippet", String(doc.text).slice(0, 380)));
      const actions = el("div", "source-actions"), extracted = list(data.claims).some(c => list(c.evidence).some(e => e.source_id === doc.source_id));
      actions.append(el("span", "source-status", extracted ? "Claims extracted" : "Not examined"));
      const button = el("button", "button button-outline", extracted ? "Extract again" : "Extract this paper"); button.type = "button"; button.disabled = !data.model?.available || state.busy;
      button.title = data.model?.available ? "Extract proposed claims from this selected source document" : "Extraction is unavailable because no AI provider is configured.";
      button.addEventListener("click", () => startJob("/api/research/extract", { source_id: doc.source_id }, `Extraction started for ${safeText(doc.title, "this paper")}.`));
      actions.append(button); row.append(copy, actions); root.append(row);
    });
  }
  function claimPredicate(claim) { return safeText(claim.predicate, "related to").replaceAll("_", " ").toLowerCase(); }
  function renderClaims(claims) {
    const root = $("#claim-list"); root.replaceChildren();
    const unresolved = claims.filter(c => !["approved", "human_reviewed", "rejected"].includes(c.review_status));
    $("#claim-count").textContent = `${unresolved.length} need review · ${claims.length} total claims`;
    if (!claims.length) { root.append(el("div", "empty-state", "No extracted claims yet. Choose a source above and request extraction. Only source-attributed claims will appear here.")); return; }
    claims.forEach(claim => {
      const card = el("article", "claim-card"), main = el("div", "claim-main"), review = el("div", "claim-review");
      main.append(el("span", "claim-type", safeText(claim.assertion_type, "source assertion").replaceAll("_", " ")));
      main.append(el("h3", "claim-title", `${nodeLabel(claim.subject)} ${claimPredicate(claim)} ${nodeLabel(claim.object)}`));
      const context = el("p", "claim-context"); context.append(el("span", "", "Context: "), document.createTextNode(Object.entries(claim.context || {}).map(([k,v]) => `${k.replaceAll("_", " ")} ${safeText(v)}`).join(" · ") || "Not specified in the extracted record")); main.append(context);
      const evidence = el("div", "claim-evidence"); list(claim.evidence).forEach(ev => evidence.append(citeButton(ev, claim))); if (!list(claim.evidence).length) evidence.append(el("span", "source-meta", "No source excerpt attached")); main.append(evidence);
      const status = safeText(claim.review_status, "pending").toLowerCase(); review.append(el("span", `review-status${["approved", "human_reviewed"].includes(status) ? " review-status--approved" : status === "rejected" ? " review-status--rejected" : ""}`, status.replaceAll("_", " ")));
      if (status === "human_reviewed" || status === "approved" || status === "rejected") {
        const last = claim.last_review || {};
        const note = el("p", "review-note", [last.reviewer, last.note].filter(Boolean).join(" · ") || (status === "rejected" ? "Claim excluded from active evidence." : "Human-reviewed claim.")); review.append(note);
        const change = el("details", "review-change"), summary = el("summary", "", "Record a new review decision"); change.append(summary, reviewControls(claim)); review.append(change);
      } else {
        review.append(reviewControls(claim));
      }
      card.append(main, review); root.append(card);
    });
  }
  function reviewControls(claim) {
    const form = el("div", "review-change-form");
    const reviewer = el("label", "", "Reviewer name"), name = el("input"); name.name = "reviewer"; name.autocomplete = "name"; reviewer.append(name);
    const rationale = el("label", "", "Review rationale"), note = el("input"); note.name = "note"; note.placeholder = "What supports or weakens this reading?"; rationale.append(note);
    const attest = el("label", "attest", ""), check = el("input"); check.type = "checkbox"; check.name = "attested"; attest.append(check, el("span", "", "I checked the source and interpretation."));
    const buttons = el("div", "review-buttons");
    const approve = el("button", "button button-primary", "Approve reviewed claim"); approve.type = "button";
    approve.disabled = !list(claim.evidence).length; approve.title = approve.disabled ? "Approval requires at least one source-attached evidence record." : "Record a new human review approval.";
    approve.addEventListener("click", () => {
      if (!list(claim.evidence).length) { notice("This claim has no source-attached evidence and cannot be approved.", true); return; }
      if (!check.checked) { notice("To approve, first attest that you checked both the source and the interpretation.", true); check.focus(); return; }
      submitReview(claim, "approve", name.value, note.value, true);
    });
    const reject = el("button", "button reject", "Reject claim"); reject.type = "button"; reject.addEventListener("click", () => submitReview(claim, "reject", name.value, note.value, false));
    buttons.append(approve, reject); form.append(reviewer, rationale, attest, buttons); return form;
  }
  async function submitReview(claim, decision, reviewer, note, attested) {
    if (!reviewer.trim() || !note.trim()) { notice("Enter your name and a short rationale before recording a review.", true); return; }
    if (decision === "approve" && !list(claim.evidence).length) { notice("This claim has no source-attached evidence and cannot be approved.", true); return; }
    await mutate("/api/research/review", { claim_id: claim.id, decision, reviewer: reviewer.trim(), note: note.trim(), ...(attested ? { attested: true } : {}) }, decision === "approve" ? "Review recorded. This is a human review decision, not an expert endorsement." : "Claim rejected and removed from eligible evidence.");
  }
  function gateValues(candidate) {
    const gates = candidate?.gates;
    if (Array.isArray(gates)) return gates;
    if (gates && typeof gates === "object") return Object.entries(gates).map(([name, v]) => typeof v === "object" ? { name, ...v } : { name, status: v });
    return [];
  }
  const gateStatus = gate => safeText(gate.status || gate.result || gate.state, "pending").toLowerCase();
  const gateStateLabel = status => ({ pass: "Pass", block: "Blocked", unknown: "Unresolved", disputed: "Disputed" })[status] || status.replaceAll("_", " ");
  const gateName = value => ({ anchor: "Disease mechanism evidence", capability_evidence: "Assay capability evidence", mechanism_step: "Mechanism step", readout: "Readout", species: "Species", tissue: "Tissue / cell context", stage: "Developmental stage", maintainer_evidence: "Maintainer evidence", access: "Access conditions", contact: "Contact route", exclusion: "Exclusion check" })[value] || safeText(value, "Decision gate").replaceAll("_", " ");
  const evidenceCitation = (evidence, claim = null) => citeButton(evidence, claim);
  function renderCandidate(candidate, { baseline = false } = {}) {
    const card = el("article", `candidate${baseline ? " candidate--baseline" : ""}`), top = el("div", "candidate-top"), titlebox = el("div");
    titlebox.append(el("h3", "candidate-title", safeText(candidate.asset_label || candidate.label || candidate.name || candidate.title || candidate.id, baseline ? "Broad-pathway candidates" : "Research candidate")));
    const partner = candidate.partner && typeof candidate.partner === "object" ? nodeLabel(candidate.partner.organization_id) : candidate.partner;
    titlebox.append(el("p", "candidate-subtitle", safeText(partner || candidate.asset || candidate.description || candidate.summary, baseline ? "Shared pathway context" : "Candidate research asset")));
    const rawStatus = safeText(candidate.status, baseline ? "exploratory" : "needs_clarification");
    const status = ({ ready_for_discussion: "Ready for discussion", needs_clarification: "Needs clarification", not_supported: "Not supported for this request" })[rawStatus] || rawStatus.replaceAll("_", " ");
    top.append(titlebox, el("span", `candidate-status${rawStatus === "ready_for_discussion" ? " candidate-status--ready" : ""}`, status)); card.append(top);
    const gates = gateValues(candidate); const ul = el("ul", "gate-list");
    if (!gates.length) gates.push({ name: baseline ? "Pathway overlap" : "Eligibility gates", status: "pending", detail: candidate.note || "No gate detail was supplied." });
    gates.forEach(gate => {
      const st = gateStatus(gate), pass = ["pass", "passed", "satisfied", "approved", "eligible"].includes(st), fail = ["block", "fail", "failed", "blocked", "rejected", "unmet"].includes(st);
      const li = el("li"), mark = el("span", `gate-mark${pass ? " gate-mark--pass" : fail ? " gate-mark--fail" : " gate-mark--pending"}`, pass ? "✓" : fail ? "×" : "○"); mark.setAttribute("aria-hidden", "true");
      const copy = el("span"), label = el("span", "gate-label", gateName(gate.label || gate.name || gate.code || gate.gate));
      const detailText = gate.detail || gate.message || gate.reason || gate.value || gate.state || "Evidence needed";
      copy.append(label, el("span", "gate-detail", `${gateStateLabel(st)} · ${safeText(detailText).replaceAll("_", " ")}`));
      list(gate.claim_ids).forEach(id => { const c = list(state.data.claims).find(x => x.id === id); if (c) list(c.evidence).forEach(ev => copy.append(evidenceCitation(ev, c))); });
      li.append(mark, copy); ul.append(li);
    });
    card.append(ul);
    if (candidate.next_action || candidate.next_step || candidate.next_action_note) card.append(el("p", "candidate-next", `Next step: ${safeText(candidate.next_action || candidate.next_step || candidate.next_action_note)}`));
    const citations = list(candidate.citations || candidate.claim_ids), citeline = el("div", "candidate-citations");
    citations.forEach(value => {
      if (typeof value === "object" && value?.source_id) citeline.append(evidenceCitation(value));
      else { const c = list(state.data.claims).find(x => x.id === value); if (c) list(c.evidence).forEach(ev => citeline.append(evidenceCitation(ev, c))); }
    }); if (citeline.childNodes.length) card.append(citeline);
    return card;
  }
  function renderAnalysis(analysis) {
    const root = $("#analysis"); root.replaceChildren(); const recs = list(analysis.recommendations);
    const baseline = analysis.baseline || {};
    if (!recs.length && !baseline.asset_ids?.length) { root.append(el("div", "empty-state", "No candidate routes are available for this question yet. Review source evidence and reassess. Missing gates remain unresolved; an empty result is not evidence that a pathway or assay will work.")); }
    else {
      if (baseline.asset_ids?.length) baseline.asset_ids.forEach(id => root.append(renderCandidate({ id, label: nodeLabel(id), status: "Exploratory baseline", gates: [{ name: "Shared pathway", status: "context only", detail: baseline.note || "Broad pathway lookup; no eligibility inferred." }] }, { baseline: true })));
      recs.forEach(rec => root.append(renderCandidate(rec)));
    }
    const clusters = analysis.clusters, n = $("#neighborhood"); n.replaceChildren(); n.hidden = !clusters;
    if (clusters) {
      n.append(el("h3", "", "Research neighborhood"));
      n.append(el("p", "section-footnote", `${safeText(clusters.method, "Neighborhood method not stated")} · ${safeText(clusters.note, "Groups organize records for exploration; similarity is not evidence of scientific equivalence.")}`));
      const labels = new Map(); list(clusters.groups).forEach(g => list(g.disease_ids).forEach(id => labels.set(id, `${safeText(g.label, g.id)}: ${nodeLabel(id)}`)));
      const edges = el("div", "edge-list"); list(clusters.links).forEach(link => {
        const edge = el("div", "edge"); edge.append(el("strong", "", nodeLabel(link.source)), el("span", "edge-label", `↔ ${Number.isFinite(link.similarity) ? `score ${link.similarity.toFixed(3)}` : "related"} ↔`), el("strong", "", nodeLabel(link.target)));
        const reasons = list(link.reasons).map(safeText).join(" · "); if (reasons) edge.append(el("span", "edge-label", `— ${reasons}`));
        if (!link.reviewed) edge.append(el("span", "candidate-status", "unreviewed"));
        list(link.claim_ids).forEach(id => { const c = list(state.data.claims).find(x => x.id === id); if (c) list(c.evidence).forEach(ev => edge.append(citeButton(ev, c))); }); edges.append(edge);
      });
      list(clusters.groups).forEach(g => { const line = el("p", "section-footnote", `${safeText(g.label, g.id)}: ${list(g.disease_ids).map(nodeLabel).join(", ")}`); n.append(line); });
      if (edges.childNodes.length) n.append(edges);
    }
    renderRetrieval(analysis.retrieval || null);
  }
  function renderRetrieval(retrieval) {
    const root = $("#retrieval"); root.replaceChildren(); root.hidden = !retrieval;
    if (!retrieval) return;
    const heading = el("div", "retrieval-heading"); heading.append(el("h3", "", "Follow-up literature search"));
    heading.append(el("span", "retrieval-meta", `${safeText(retrieval.provider, "retriever")} · ${count(retrieval.searched_documents)} documents searched`)); root.append(heading);
    root.append(el("p", "retrieval-note", safeText(retrieval.note, "Search excerpts are leads to inspect in the source; retrieval is not scientific validation.")));
    if (!list(retrieval.hits).length) { root.append(el("div", "empty-state", "No follow-up excerpts were returned. The searched-document count describes this bounded search only.")); return; }
    list(retrieval.hits).forEach(hit => {
      const item = el("article", "retrieval-hit"), title = el("h4", "retrieval-hit-title");
      const href = sourceLink(sourceFor(hit.source_id).url);
      if (href) { const link = el("a", "", safeText(hit.title || sourceFor(hit.source_id).title, "Untitled source")); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; title.append(link); }
      else title.textContent = safeText(hit.title || sourceFor(hit.source_id).title, "Untitled source");
      item.append(title, el("p", "retrieval-hit-source", `${safeText(hit.source_id, "Unknown source")}${Number.isFinite(hit.start) && Number.isFinite(hit.end) ? ` · characters ${hit.start}–${hit.end}` : ""}`));
      item.append(el("p", "retrieval-hit-text", safeText(hit.text, "No exact snippet supplied.")));
      item.append(el("p", "retrieval-hit-score", Number.isFinite(hit.score) ? `Retrieval score ${hit.score.toFixed(3)} · ranking aid only` : "Unscored retrieved excerpt")); root.append(item);
    });
  }
  function renderBrief(brief) {
    const editor = $("#brief-editor");
    if (!state.dirty) { editor.value = safeText(brief.markdown); state.briefDraft = editor.value; }
    $("#stale-note").hidden = !brief.stale;
    $("#brief-state").textContent = brief.stale ? "Outdated · source state changed" : brief.edited ? "User-edited draft · unverified" : brief.markdown ? (brief.ai_draft ? "AI draft · unverified" : "Prepared draft · unverified") : "Draft not yet prepared";
    $("#brief-state").className = `brief-state${brief.edited ? " brief-state--edited" : ""}`;
    $("#edit-indicator").textContent = state.dirty ? "Unsaved edits · verify all claims and citations" : "Workspace draft · verify claims and citations";
  }
  function renderJobs(jobs) {
    const active = list(jobs).filter(j => j.status === "running");
    if (active.length) { active.forEach(job => pollJob(job.id)); }
  }
  async function startJob(path, body, message) {
    if (state.busy) return; state.busy = true; notice(message); error("");
    try {
      const result = await api(path, { method: "POST", body: { ...body, revision: revision() } });
      if (result.status === "completed") { if (path === "/api/research/explain" && state.pendingAiDraftAt === state.editVersion) state.dirty = false; state.pendingAiDraftAt = null; await refresh(); notice(result.message || "The selected workflow step is complete."); }
      else { const id = result.id || result.job_id; if (!id) throw new Error("The service accepted the request but did not return a job id."); pollJob(id); }
    } catch (e) { state.pendingAiDraftAt = null; if (e.status === 409) { await refresh(); notice("The workspace changed. It has been refreshed; review the latest state and try again.", true); } else error(e.message); }
    finally { state.busy = false; }
  }
  async function pollJob(id) {
    if (!id || state.pollTimer) return;
    const poll = async () => {
      try {
        const job = await api(`/api/research/jobs/${encodeURIComponent(id)}`);
        notice(safeText(job.message, `Research task ${job.status}.`), job.status === "failed");
        if (job.status === "completed" || job.status === "failed") {
          if (job.status === "completed" && state.pendingAiDraftAt === state.editVersion) state.dirty = false;
          state.pendingAiDraftAt = null;
          state.pollTimer = null; await refresh();
          if (job.status === "failed") error(safeText(job.message, "The research task failed."));
          else notice(safeText(job.message, "Task complete. Workspace state refreshed."));
          return;
        }
      } catch (e) { state.pollTimer = null; error(`Could not check task progress. ${e.message}`); return; }
      state.pollTimer = setTimeout(() => { state.pollTimer = null; poll(); }, 1300);
    };
    await poll();
  }
  $("#question-form").addEventListener("submit", async event => {
    event.preventDefault(); const req = requestData();
    const result = await mutate("/api/research/analyze", { request: req }, "Question updated and decision gates reassessed.");
      if (result) document.activeElement.blur();
  });
  $("#analyze").addEventListener("click", () => mutate("/api/research/analyze", { request: requestData() }, "Decision gates reassessed against the reviewed evidence."));
  $("#investigate").addEventListener("click", () => startJob("/api/research/investigate", {}, "One bounded follow-up source review started. New claims will remain pending human review."));
  $("#brief-editor").addEventListener("input", () => { state.dirty = true; state.editVersion += 1; $("#brief-state").textContent = "Unsaved user edits · unverified"; $("#brief-state").className = "brief-state brief-state--edited"; $("#edit-indicator").textContent = "Unsaved edits · verify all claims and citations"; });
  $("#save-brief").addEventListener("click", () => mutate("/api/research/brief", { markdown: $("#brief-editor").value }, "Draft saved in this research workspace. No message was sent."));
  $("#reset-brief").addEventListener("click", () => mutate("/api/research/brief/reset", {}, "Brief regenerated from the current workspace state. Verify citations and interpretation."));
  const aiDraft = el("button", "button button-outline", "Draft brief with AI"); aiDraft.type = "button"; aiDraft.id = "ai-draft"; aiDraft.title = "Ask the configured model to draft a cited brief. It will not be approved automatically.";
  $("#reset-brief").parentElement.insertBefore(aiDraft, $("#reset-brief"));
  aiDraft.addEventListener("click", () => { state.pendingAiDraftAt = state.editVersion; startJob("/api/research/explain", {}, "AI brief drafting started. The result will remain an unverified draft."); });
  $("#download-brief").addEventListener("click", () => {
    const markdown = $("#brief-editor").value; if (!markdown.trim()) { notice("There is no brief text to download yet.", true); return; }
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" }); const url = URL.createObjectURL(blob); const a = el("a"); a.href = url; a.download = "atlas-research-brief.md"; document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  });
  $("#close-evidence").addEventListener("click", () => $("#evidence-dialog").close());
  $("#evidence-dialog").addEventListener("click", event => { if (event.target === $("#evidence-dialog")) $("#evidence-dialog").close(); });
  refresh({ quiet: false });
})();

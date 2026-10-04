(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const el = (tag, cls = '', text = null) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== null && text !== undefined) node.textContent = String(text); return node; };
  const safe = (value, fallback = '') => typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
  const rows = value => Array.isArray(value) ? value : [];
  const workspace = { state: null, selected: null, active: false, tab: 'literature', briefDirty: false, briefVersion: 0, aiDraftVersion: null, requestDirty: false, timers: new Map(), pending: new Map(), searching: false, lastAskClaimIds: [] };
  const status = (text, tone = '') => { const target = $('#workspace-status'); target.textContent = text; target.dataset.tone = tone; };
  const alertIn = (container, message, tone = 'warning') => { let item = container.querySelector('.workspace-empty'); if (!item) { item = el('div', `workspace-empty workspace-empty--${tone}`); container.prepend(item); } item.textContent = message; };
  const nodeById = id => rows(workspace.state?.nodes).find(node => node.id === id);
  const nodeName = id => safe(nodeById(id)?.label || id, 'Unlabelled record');
  const sourceById = id => rows(workspace.state?.sources).find(source => (source.id || source.source_id) === id) || rows(workspace.state?.documents).find(doc => doc.source_id === id) || {};
  const documentById = id => rows(workspace.state?.documents).find(doc => doc.source_id === id);
  const validHref = value => { try { const u = new URL(value, location.href); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch (_) { return ''; } };
  const link = (label, href) => { const url = validHref(href); if (!url) return el('span', 'workspace-muted', label); const a = el('a', 'workspace-link-button', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a; };
  const revision = () => workspace.state?.revision;
  const setCoverage = () => {
    const root = $('#workspace-coverage'); root.replaceChildren();
    const data = workspace.state, coverage = data?.coverage || {}, retrieval = data?.analysis?.retrieval || {}, catalog = data?.catalog || {};
    const items = [
      [`${rows(data?.nodes).length}`, 'nodes'], [`${rows(data?.claims).length} · ${safe(coverage.reviewed_claims, 0)} reviewed`, 'claims'],
      [safe(coverage.indexed_documents ?? retrieval.searched_documents, '—'), 'loaded docs'],
      [safe(data?.model?.provider || 'off'), 'model'], [safe(catalog.provider || 'local_lexical'), 'catalog search'],
    ];
    items.forEach(([value, label]) => { const span = el('span'); span.append(el('strong', '', value), document.createTextNode(` ${label}`)); root.append(span); });
    rows(catalog.scopes).forEach(scope => {
      const span = el('span', 'workspace-coverage-scope'); span.title = `${safe(scope.label || scope.id, 'scope')}: ${safe(scope.loaded_passages, '—')} loaded passages; ${safe(scope.indexed_passages, '—')} indexed passages`;
      span.append(el('strong', '', safe(scope.label || scope.id, 'scope')), document.createTextNode(` ${safe(scope.loaded_passages, '—')} loaded · ${safe(scope.indexed_passages, '—')} indexed`)); root.append(span);
    });
  };
  async function request(path, { method = 'GET', body } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['X-Atlas-Token'] = safe(workspace.state?.csrf_token); }
    const response = await fetch(path, { method, credentials: 'same-origin', headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(safe(payload?.error?.message, `Request failed (${response.status}).`)); error.status = response.status; error.code = payload?.error?.code; throw error; }
    return payload;
  }
  async function refresh({ quiet = true } = {}) {
    try {
      const data = await request('/api/research/state');
      workspace.active = true; workspace.state = data;
      status(`${data.dataset?.synthetic ? 'Synthetic example' : 'Source dataset'} · revision ${safe(data.revision)}`, data.dataset?.synthetic ? 'warning' : '');
      $('#workspace-toggle').disabled = false;
      renderAll(); dispatchUpdated(data);
      if (!quiet) status(`${data.dataset?.synthetic ? 'Synthetic example' : 'Source dataset'} · revision ${safe(data.revision)}`, data.dataset?.synthetic ? 'warning' : '');
      rows(data.jobs).filter(job => job.status === 'running' && !workspace.pending.has(job.id)).forEach(job => pollJob(job.id));
      return data;
    } catch (error) {
      workspace.active = false; workspace.state = null;
      status(error.status === 404 ? 'No writable research workspace on this server. Graph view remains read-only.' : `Research workspace unavailable: ${error.message}`, 'warning');
      $('#workspace-coverage').replaceChildren();
      $('#workspace-claims').replaceChildren(el('div', 'workspace-empty', 'Start the research workspace to review source-backed claims and draft a plan.'));
      $('#workspace-analysis').replaceChildren(el('div', 'workspace-empty', 'Planning controls are unavailable in this read-only graph view.'));
      $('#workspace-brief').value = '';
      $('#workspace-panel').dataset.readonly = 'true';
      setControls(false);
      return null;
    }
  }
  function dispatchUpdated(data) { window.dispatchEvent(new CustomEvent('atlas:workspace-updated', { detail: { state: data } })); }
  function setControls(enabled) {
    ['literature-query', 'workspace-disease', 'workspace-mechanism', 'workspace-request-form', 'workspace-investigate', 'brief-regenerate', 'brief-ai', 'brief-save', 'brief-download', 'show-all-claims'].forEach(id => { const target = document.getElementById(id); if (target) target.disabled = !enabled; });
  }
  function fillRequest(req) {
    if (!req || workspace.requestDirty) return;
    for (const [id, type, prompt, key] of [['workspace-disease', 'Disease', 'Choose a disease', 'disease_id'], ['workspace-mechanism', 'Mechanism', 'Choose a mechanism', 'mechanism_id']]) {
      const select = document.getElementById(id); select.replaceChildren(new Option(prompt, ''));
      rows(workspace.state.nodes).filter(node => node.type === type).sort((a, b) => nodeName(a.id).localeCompare(nodeName(b.id))).forEach(node => select.add(new Option(nodeName(node.id), node.id)));
      const selected = safe(req[key]); if (selected && ![...select.options].some(option => option.value === selected)) select.add(new Option('Current selection (label unavailable)', selected)); select.value = selected;
    }
    const form = $('#workspace-request-form');
    ['mechanism_step', 'readout', 'species', 'tissue', 'stage'].forEach(key => { if (document.activeElement !== form.elements[key]) form.elements[key].value = safe(req[key]); });
  }
  function renderAll() {
    const data = workspace.state; if (!data) return;
    $('#workspace-panel').dataset.readonly = 'false'; setControls(true); fillRequest(data.request || {}); setCoverage(); renderSources(); renderClaims(); renderPlan(); renderBrief(data.brief || {});
    $('#send-question').disabled = workspace.asking || !data.model?.available;
    $('#send-question').title = data.model?.available ? 'Ask Atlas about this graph slice with source citations.' : 'Ask Atlas is unavailable because no live model provider is configured.';
  }
  function switchTab(tab, focus = false) {
    workspace.tab = tab;
    document.querySelectorAll('[data-workspace-tab]').forEach(button => { const selected = button.dataset.workspaceTab === tab; button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1; if (selected && focus) button.focus(); });
    document.querySelectorAll('.workspace-tab-panel[role="tabpanel"]').forEach(panel => { panel.hidden = panel.id !== `panel-${tab}`; });
  }
  document.querySelectorAll('[data-workspace-tab]').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.workspaceTab)));
  $('#workspace-panel').addEventListener('keydown', event => {
    const tab = event.target.closest('[data-workspace-tab]'); if (!tab) return;
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) { event.preventDefault(); const tabs = [...document.querySelectorAll('[data-workspace-tab]')]; let index = tabs.indexOf(tab); index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; switchTab(tabs[index].dataset.workspaceTab, true); }
  });
  $('#workspace-toggle').addEventListener('click', () => {
    const panel = $('#workspace-panel'), open = panel.hidden; panel.hidden = !open; $('#workspace-toggle').setAttribute('aria-expanded', String(open));
    if (open) { $('#chat-panel').hidden = true; $('#chat-toggle').setAttribute('aria-expanded', 'false'); switchTab(workspace.tab); $('#tab-' + workspace.tab).focus(); }
    else $('#workspace-toggle').focus();
  });
  $('#workspace-close').addEventListener('click', () => { $('#workspace-panel').hidden = true; $('#workspace-toggle').setAttribute('aria-expanded', 'false'); $('#workspace-toggle').focus(); });
  $('#help-research-button').addEventListener('click', () => { $('#graph-help').close(); $('#workspace-toggle').click(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('#workspace-panel').hidden) { $('#workspace-panel').hidden = true; $('#workspace-toggle').setAttribute('aria-expanded', 'false'); $('#workspace-toggle').focus(); } });

  function renderSources() {
    // Show only already loaded source snapshots here; literature search results remain a separate record type.
    const root = $('#literature-results'); root.replaceChildren();
    const docs = rows(workspace.state.documents);
    root.append(el('div', 'workspace-list-heading', 'Loaded source snapshots'));
    if (!docs.length) root.append(el('div', 'workspace-empty', 'No source documents are loaded. Search the corpus and use an exact passage to add a source snapshot.'));
    docs.forEach(doc => {
      const item = el('article', 'workspace-result'); item.append(el('h3', '', safe(doc.title, 'Untitled source')));
      item.append(el('p', 'workspace-result-source', [doc.source_id, doc.version, doc.license].filter(Boolean).join(' · ')));
      if (doc.text) item.append(el('p', 'workspace-snippet', String(doc.text).slice(0, 240)));
      const actions = el('div', 'workspace-result-actions'); const exists = rows(workspace.state.claims).some(claim => rows(claim.evidence).some(evidence => evidence.source_id === doc.source_id));
      const extract = el('button', 'workspace-button', exists ? 'Extract again' : 'Extract claims'); extract.type = 'button'; extract.disabled = !workspace.state.model?.available;
      extract.title = extract.disabled ? 'Extraction is unavailable because no model provider is configured.' : 'Extract source-grounded claims from this selected paper.';
      extract.addEventListener('click', () => startJob('/api/research/extract', { source_id: doc.source_id }, 'extract'));
      actions.append(extract); item.append(actions); root.append(item);
    });
  }
  function localDocumentContains(claim) {
    const evidence = rows(claim.evidence); return evidence.length > 0 && evidence.every(item => { const doc = documentById(item.source_id); return !!doc && item.source_version === doc.version && typeof item.excerpt === 'string' && doc.text.includes(item.excerpt); });
  }
  function evidenceButton(evidence, claim) {
    const source = sourceById(evidence.source_id); const label = `${safe(source.title || evidence.source_id, 'Source')}${evidence.locator ? ` · ${safe(evidence.locator)}` : ''}`;
    const button = el('button', 'workspace-link-button', label); button.type = 'button';
    button.addEventListener('click', () => { if (nodeById(claim.subject)) window.dispatchEvent(new CustomEvent('atlas:select-node', { detail: { node_id: claim.subject } })); window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: claim.id } })); }); return button;
  }
  function reviewControls(claim, review = null) {
    const form = el('div', 'review-fields'), reviewerLabel = el('label', '', 'Reviewer name'), reviewer = el('input'); reviewer.autocomplete = 'name'; reviewer.value = safe(review?.reviewer); reviewerLabel.append(reviewer);
    const noteLabel = el('label', '', 'Review rationale'), note = el('input'); note.maxLength = 2000; note.placeholder = 'What supports or weakens this interpretation?'; note.value = safe(review?.note); noteLabel.append(note);
    const attestLabel = el('label', 'review-attestation', ''), attest = el('input'); attest.type = 'checkbox'; attestLabel.append(attest, el('span', '', 'I checked the source and interpretation.'));
    const actions = el('div', 'review-actions'); const approve = el('button', 'workspace-button workspace-button-primary', 'Approve reviewed claim'); approve.type = 'button';
    const eligible = localDocumentContains(claim); approve.disabled = !eligible;
    if (!eligible) form.append(el('p', 'review-locked', rows(claim.evidence).length ? 'Approval unavailable: this evidence does not all match a loaded source snapshot and exact excerpt.' : 'Approval unavailable: this claim has no source-attached evidence. Inspect the source metadata; do not infer approval.'));
    approve.addEventListener('click', () => { if (!eligible) return; if (!attest.checked) { status('Approval requires the source-and-interpretation attestation.', 'warning'); attest.focus(); return; } submitReview(claim, 'approve', reviewer.value, note.value, true); });
    const reject = el('button', 'workspace-button', 'Reject claim'); reject.type = 'button'; reject.addEventListener('click', () => submitReview(claim, 'reject', reviewer.value, note.value, false));
    actions.append(approve, reject); form.append(reviewerLabel, noteLabel, attestLabel, actions); return form;
  }
  function renderClaims() {
    const root = $('#workspace-claims'); root.replaceChildren(); const all = rows(workspace.state.claims); const selected = workspace.selected;
    const visible = $('#show-all-claims').checked || !selected ? all : all.filter(claim => claim.subject === selected.node_id || claim.object === selected.node_id);
    const context = $('#selection-context'); context.replaceChildren();
    if (selected) context.append(el('strong', '', `${selected.node?.label || nodeName(selected.node_id)} · ${selected.node?.type || nodeById(selected.node_id)?.type || 'Graph node'}`), el('span', '', `${visible.length} related claim${visible.length === 1 ? '' : 's'} in this workspace slice.`));
    else context.append(el('strong', '', 'All claims in the loaded slice'), el('span', '', 'Select a graph node to narrow the evidence list.'));
    if (!visible.length) { root.append(el('div', 'workspace-empty', 'No claims are linked to this node in the current loaded slice. Try “Show all claims” or choose another graph node.')); return; }
    visible.forEach(claim => {
      const card = el('article', 'workspace-claim'); card.append(el('span', 'workspace-predicate', safe(claim.assertion_type, 'source claim').replaceAll('_', ' ')));
      card.append(el('h3', '', `${nodeName(claim.subject)} ${safe(claim.predicate, 'relates to').replaceAll('_', ' ').toLowerCase()} ${nodeName(claim.object)}`));
      const contextText = Object.entries(claim.context || {}).map(([key, value]) => `${key.replaceAll('_', ' ')} ${safe(value)}`).join(' · '); if (contextText) card.append(el('p', 'workspace-claim-meta', contextText));
      card.append(el('p', `workspace-classification${claim.review_status === 'human_reviewed' ? ' workspace-classification--reviewed' : ''}`, safe(claim.review_status, 'unreviewed').replaceAll('_', ' ')));
      const citations = el('div', 'workspace-citation-links'); rows(claim.evidence).forEach(item => citations.append(evidenceButton(item, claim)));
      if (!rows(claim.evidence).length) citations.append(el('span', 'workspace-muted', 'No source excerpt attached.'));
      card.append(citations);
      const previous = claim.last_review;
      if (previous) card.append(el('p', 'workspace-claim-meta', `Last review · ${safe(previous.reviewer)} · ${safe(previous.note)}`));
      if (claim.review_status === 'unreviewed') card.append(reviewControls(claim));
      else { const details = el('details', 'review-change'), summary = el('summary', '', 'Record a new review decision'); details.append(summary, reviewControls(claim, previous)); card.append(details); }
      root.append(card);
    });
  }
  async function submitReview(claim, decision, reviewer, note, attested) {
    if (!reviewer.trim() || !note.trim()) { status('Enter a reviewer name and rationale before recording a decision.', 'warning'); return; }
    const body = { claim_id: claim.id, decision, reviewer: reviewer.trim(), note: note.trim() }; if (attested) body.attested = true;
    await mutate('/api/research/review', body, decision === 'approve' ? 'Review recorded. It is a local attestation, not independently verified expertise.' : 'Claim rejected from the active assessment; its record remains visible.');
  }
  function renderPlan() {
    const analysis = workspace.state.analysis || {}, root = $('#workspace-analysis'); root.replaceChildren();
    const baseline = analysis.baseline || {}, recs = rows(analysis.recommendations);
    if (baseline.asset_ids?.length) {
      baseline.asset_ids.forEach(id => { const card = el('article', 'workspace-candidate'); card.append(el('span', 'workspace-predicate', 'Broad pathway baseline · candidate lookup'), el('h3', '', nodeName(id)), el('p', 'workspace-claim-meta', safe(baseline.note, 'Candidate discovery context only; it does not assess assay eligibility.'))); root.append(card); });
    }
    if (!recs.length) root.append(el('div', 'workspace-empty', 'No assay-reuse candidates are present in this assessment. The small loaded graph slice may not contain every relevant method.'));
    recs.forEach(rec => {
      const card = el('article', 'workspace-candidate'), head = el('div', 'workspace-candidate-head'); head.append(el('h3', '', safe(rec.asset_label || rec.asset_id, 'Research asset')));
      const labels = { ready_for_discussion: 'Ready for discussion', needs_clarification: 'Needs clarification', not_supported: 'Not supported for this request' };
      const rawStatus = safe(rec.status, 'needs_clarification'); head.append(el('span', `workspace-candidate-status${rawStatus === 'ready_for_discussion' ? ' workspace-candidate-status--ready' : ''}`, labels[rawStatus] || rawStatus.replaceAll('_', ' '))); card.append(head);
      if (rec.partner?.organization_id) card.append(el('p', 'workspace-claim-meta', `Maintainer candidate: ${nodeName(rec.partner.organization_id)} · access ${safe(rec.partner.access_status, 'unknown')}`));
      const gates = el('ul', 'workspace-gates'); rows(rec.gates).forEach(gate => {
        const li = el('li'), stateLabel = { pass: '✓', block: '×', unknown: '○' }[gate.state] || '○'; li.append(el('span', '', stateLabel));
        const copy = el('span'); copy.append(el('span', 'workspace-gate-label', safe(gate.code, 'Decision gate').replaceAll('_', ' ')), document.createTextNode(`${safe(gate.state, 'unknown')} · ${safe(gate.reason, 'Evidence required')}`));
        rows(gate.claim_ids).forEach(id => { const claim = rows(workspace.state.claims).find(item => item.id === id); if (claim) rows(claim.evidence).forEach(item => copy.append(evidenceButton(item, claim))); }); li.append(copy); gates.append(li);
      }); card.append(gates);
      if (rec.next_action) card.append(el('p', 'workspace-next', `Next step: ${rec.next_action}`));
      root.append(card);
    });
    const neighborhood = $('#workspace-neighborhood'); neighborhood.replaceChildren(); const clusters = analysis.clusters;
    const retrieval = analysis.retrieval;
    if (retrieval) {
      const retrievalNote = retrieval.note || (retrieval.status === 'failed' ? retrieval.error : '');
      const message = retrieval.status === 'failed'
        ? `Evidence retrieval failed; no fallback was used. ${safe(retrievalNote)}`
        : `${safe(retrieval.provider || retrieval.mode, 'Evidence retrieval')} · searched ${safe(retrieval.searched_documents, '—')} loaded documents. ${safe(retrievalNote)}`;
      neighborhood.append(el('p', retrieval.status === 'failed' ? 'workspace-retrieval-warning' : 'workspace-muted', message));
    }
    if (clusters) {
      neighborhood.append(el('h3', '', 'Research neighborhood'), el('p', '', `${safe(clusters.method, 'Graph grouping')} · ${safe(clusters.note, 'Clusters are exploratory and do not show biological equivalence.')}`));
      rows(clusters.groups).forEach(group => neighborhood.append(el('p', '', `${safe(group.label, group.id)}: ${rows(group.disease_ids).map(nodeName).join(', ')}`)));
      rows(clusters.links).forEach(edge => {
        const item = el('div', 'workspace-edge'); item.append(el('strong', '', nodeName(edge.source)), document.createTextNode(` ↔ score ${Number.isFinite(edge.similarity) ? edge.similarity.toFixed(3) : 'n/a'} ↔ `), el('strong', '', nodeName(edge.target)), document.createTextNode(` · ${rows(edge.reasons).map(safe).join('; ')} · ${edge.reviewed ? 'reviewed' : 'unreviewed'}`));
      rows(edge.claim_ids).forEach(id => {
        const claim = rows(workspace.state.claims).find(item => item.id === id);
        if (!claim) return;
        const button = el('button', 'workspace-link-button', `Inspect evidence · ${id}`); button.type = 'button';
        button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: id } })));
        item.append(button);
      });
        neighborhood.append(item);
      });
    }
    const modelAvailable = !!workspace.state.model?.available; $('#workspace-investigate').disabled = !modelAvailable;
    $('#workspace-investigate').title = modelAvailable ? 'Search one bounded source and extract new claims for review.' : 'Configure a model provider before investigating a gap.';
  }
  function renderBrief(brief) {
    if (!workspace.briefDirty) $('#workspace-brief').value = safe(brief.markdown);
    $('#brief-stale').hidden = !brief.stale;
    $('#brief-status').textContent = brief.stale ? 'Outdated draft · source or review state changed.' : brief.edited ? 'User-edited draft · verify all citations.' : brief.ai_draft ? 'AI-generated interpretation · unverified.' : 'Deterministic discussion draft · verify sources and interpretation.';
    $('#brief-ai').disabled = !workspace.state.model?.available; $('#brief-ai').title = workspace.state.model?.available ? 'Draft cited prose with the configured provider; result remains unverified.' : 'AI brief drafting requires a configured model provider.';
  }
  function renderSourceHit(hit) {
    const item = el('article', 'workspace-result'), title = el('h3'); const source = sourceById(hit.source_id);
    const href = validHref(hit.url || source.url); if (href) { const a = link(safe(hit.title || source.title, 'Untitled source'), href); title.append(a); } else title.textContent = safe(hit.title || source.title, 'Untitled source'); item.append(title);
    item.append(el('p', 'workspace-result-source', `${safe(hit.source_id, 'Unknown source')}${hit.locator ? ` · ${safe(hit.locator)}` : ''}${hit.kind ? ` · ${safe(hit.kind)}` : ''}${hit.review_status ? ` · ${safe(hit.review_status).replaceAll('_', ' ')}` : ''}`));
    item.append(el('p', 'workspace-snippet', safe(hit.text, 'No exact snippet returned.')));
    const actions = el('div', 'workspace-result-actions');
    rows(hit.node_ids).filter(id => nodeById(id)).forEach(id => { const button = el('button', 'workspace-link-button', `Open graph node · ${nodeName(id)}`); button.type = 'button'; button.addEventListener('click', () => { window.dispatchEvent(new CustomEvent('atlas:select-node', { detail: { node_id: id } })); $('#workspace-panel').hidden = true; $('#workspace-toggle').setAttribute('aria-expanded', 'false'); }); actions.append(button); });
    rows(hit.claim_ids).forEach(id => { const claim = rows(workspace.state.claims).find(item => item.id === id); if (claim) { const button = el('button', 'workspace-link-button', `Inspect graph claim · ${claim.id}`); button.type = 'button'; button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: id } }))); actions.append(button); } });
    const use = el('button', 'workspace-button', hit.kind === 'curated_evidence' ? 'Inspect claim' : 'Use passage'); use.type = 'button';
    if (hit.kind === 'curated_evidence') {
      const claimId = rows(hit.claim_ids)[0]; use.disabled = !claimId;
      use.title = 'Curated graph evidence is already represented as a claim and cannot be imported as a new passage.';
      use.addEventListener('click', () => { if (claimId) window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: claimId } })); });
    } else use.addEventListener('click', () => addPassage(hit));
    actions.append(use); item.append(actions); return item;
  }
  $('#literature-search-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!workspace.active || workspace.searching) return;
    const query = $('#literature-query').value.trim(); if (!query) return;
    workspace.searching = true; $('#literature-meta').textContent = 'Searching the loaded corpus…'; $('#literature-search-form button').disabled = true;
    try {
      const result = await request('/api/atlas/search', { method: 'POST', body: { q: query, top_k: 8 } });
      const root = $('#literature-results'); root.replaceChildren(); renderSources();
      const scopeText = rows(result.scopes).map(scope => typeof scope === 'string' ? scope : `${safe(scope.label || scope.id, 'scope')} (${safe(scope.loaded_passages, '—')}/${safe(scope.indexed_passages, '—')} passages)`).join(' · ');
      const meta = $('#literature-meta'); meta.textContent = `${safe(result.provider, 'search')} · ${scopeText || 'loaded sources'} · ${rows(result.hits).length} passages`;
      if (!rows(result.hits).length) root.append(el('div', 'workspace-empty', 'No matching source passages in this search. This says nothing about literature outside the loaded corpus.'));
      rows(result.hits).forEach(hit => root.append(renderSourceHit(hit)));
    } catch (error) { $('#literature-meta').textContent = `Search failed · ${error.message}`; }
    finally { workspace.searching = false; $('#literature-search-form button').disabled = !workspace.active; }
  });
  async function addPassage(hit) {
    try { const data = await mutate('/api/atlas/source', { hit_id: hit.id }, 'Verified passage added as a source snapshot. It is not yet an approved graph claim.'); if (data) { switchTab('literature'); renderSources(); } }
    catch (_) { /* mutate already presents a safe, user-facing status */ }
  }
  async function mutate(path, body, success) {
    if (!workspace.active) return null;
    try {
      const result = await request(path, { method: 'POST', body: { ...body, revision: revision() } });
      if (result?.revision !== undefined && Array.isArray(result.claims)) { workspace.state = result; renderAll(); dispatchUpdated(result); }
      status(success, 'success'); return result;
    } catch (error) {
      if (error.status === 409) { await refresh(); status('The workspace changed. The latest graph and evidence are loaded; check your draft and try again.', 'warning'); }
      else status(error.message, 'error');
      return null;
    }
  }
  $('#workspace-request-form').addEventListener('input', () => { workspace.requestDirty = true; });
  $('#workspace-request-form').addEventListener('change', () => { workspace.requestDirty = true; });
  $('#workspace-request-form').addEventListener('submit', async event => {
    event.preventDefault(); const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    const result = await mutate('/api/research/analyze', { request: { ...workspace.state.request, ...values } }, 'Research question updated; plan gates were reassessed.');
    if (result) { workspace.requestDirty = false; fillRequest(result.request); }
  });
  $('#show-all-claims').addEventListener('change', renderClaims);
  window.addEventListener('atlas:node-select', event => { workspace.selected = event.detail?.node_id ? event.detail : null; if (workspace.active) renderClaims(); });

  async function startJob(path, body, kind) {
    if (!workspace.active) return;
    if (kind === 'explain') workspace.aiDraftVersion = workspace.briefVersion;
    try {
      const job = await request(path, { method: 'POST', body: { ...body, revision: revision() } });
      if (job.status === 'completed') { if (kind === 'explain' && workspace.aiDraftVersion === workspace.briefVersion) workspace.briefDirty = false; workspace.aiDraftVersion = null; await refresh(); return; }
      pollJob(job.id, kind);
    } catch (error) { workspace.aiDraftVersion = null; if (error.status === 409) { await refresh(); status('The workspace changed. Latest evidence loaded; retry this action if still needed.', 'warning'); } else status(error.message, 'error'); }
  }
  async function pollJob(id, kind = null) {
    if (!id || workspace.timers.has(id)) return;
    workspace.pending.set(id, kind);
    const poll = async () => {
      try {
        const job = await request(`/api/research/jobs/${encodeURIComponent(id)}`);
        if (job.status === 'running') { workspace.timers.set(id, setTimeout(poll, 1200)); return; }
        clearTimeout(workspace.timers.get(id)); workspace.timers.delete(id);
        const action = workspace.pending.get(id); workspace.pending.delete(id);
        if (job.status === 'failed') { workspace.aiDraftVersion = null; status(safe(job.message, 'Research task failed.'), 'error'); await refresh(); return; }
        if (action === 'explain' && workspace.aiDraftVersion === workspace.briefVersion) workspace.briefDirty = false;
        workspace.aiDraftVersion = null;
        if (action === 'ask') showAskResult(job.outcome?.answer, job);
        await refresh();
        status(safe(job.message, 'Research task completed. Workspace refreshed.'), 'success');
      } catch (error) { clearTimeout(workspace.timers.get(id)); workspace.timers.delete(id); workspace.pending.delete(id); status(`Could not check task progress: ${error.message}`, 'error'); }
    };
    await poll();
  }
  $('#workspace-investigate').addEventListener('click', () => startJob('/api/research/investigate', {}, 'investigate'));
  $('#brief-regenerate').addEventListener('click', async () => { const result = await mutate('/api/research/brief/reset', {}, 'Brief regenerated from the current evidence snapshot.'); if (result) { workspace.briefDirty = false; renderBrief(result.brief || {}); } });
  $('#brief-ai').addEventListener('click', () => startJob('/api/research/explain', {}, 'explain'));
  $('#workspace-brief').addEventListener('input', () => { workspace.briefDirty = true; workspace.briefVersion++; $('#brief-status').textContent = 'Unsaved user edits · unverified.'; });
  $('#brief-save').addEventListener('click', async () => { const result = await mutate('/api/research/brief', { markdown: $('#workspace-brief').value }, 'Brief saved in this local workspace.'); if (result) { workspace.briefDirty = false; renderBrief(result.brief || {}); } });
  $('#brief-download').addEventListener('click', () => { const markdown = $('#workspace-brief').value; if (!markdown.trim()) { status('There is no brief text to download.', 'warning'); return; } const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' })); const a = el('a'); a.href = url; a.download = 'atlas-research-brief.md'; document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url); });

  async function askLive(question, context) {
    if (!workspace.state?.model?.available) { status('Ask Atlas is unavailable because no live model provider is configured.', 'warning'); return; }
    const box = $('#chat-messages'), input = $('#question'); const reply = el('div', 'chat-message answer');
    box.append(el('div', 'chat-message user', question), reply); reply.append(el('p', '', 'Checking the selected graph context and cited sources…')); box.scrollTop = box.scrollHeight;
    const payload = { revision: revision(), question, ...(context.node_id ? { node_id: context.node_id } : {}), ...(context.claim_ids?.length ? { claim_ids: context.claim_ids.slice(0, 100) } : {}) };
    try {
      const job = await request('/api/atlas/ask', { method: 'POST', body: payload });
      if (job.status === 'completed') { showAskResult(job.outcome?.answer, job, reply); if (input.value === question) input.value = ''; await refresh(); }
      else { workspace.pending.set(job.id, { kind: 'ask', reply, question }); await pollAsk(job.id, reply, question); }
    } catch (error) { reply.replaceChildren(el('p', '', error.message || 'The answer could not be loaded.')); if (!input.value) input.value = question; }
    box.scrollTop = box.scrollHeight;
  }
  async function pollAsk(id, reply, question) {
    workspace.pending.set(id, { kind: 'ask', reply, question });
    while (true) {
      try {
        const job = await request(`/api/research/jobs/${encodeURIComponent(id)}`);
        if (job.status === 'running') { await new Promise(resolve => setTimeout(resolve, 1200)); continue; }
        workspace.pending.delete(id);
        if (job.status === 'failed') {
          reply.replaceChildren(el('p', '', safe(job.message, 'The answer could not be completed.')));
          status(safe(job.message, 'Ask Atlas failed.'), 'error'); await refresh(); return;
        }
        showAskResult(job.outcome?.answer, job, reply); if ($('#question').value === question) $('#question').value = '';
        await refresh(); status(safe(job.message, 'Research answer completed.'), 'success'); return;
      } catch (error) {
        workspace.pending.delete(id);
        reply.replaceChildren(el('p', '', `Could not check answer status: ${error.message}`));
        status(`Could not check answer status: ${error.message}`, 'error'); await refresh(); return;
      }
    }
  }
  function showAskResult(result, job = {}, target = null) {
    const reply = target || el('div', 'chat-message answer'); if (!target) $('#chat-messages').append(reply); reply.replaceChildren();
    const data = result && typeof result === 'object' ? result : {};
    workspace.lastAskClaimIds = rows(data.claim_ids);
    const metadata = data.metadata || job.metadata || {}, retrieval = metadata.retrieval || {};
    const mode = safe(data.mode || (metadata.mode === 'live' ? 'live' : ''), 'response');
    const provider = safe(metadata.provider || data.provider, 'provider unavailable'), retrievalMode = safe(retrieval.provider || retrieval.mode || metadata.retrieval_mode, 'retrieval mode not reported');
    reply.append(el('div', 'answer-label', `Atlas · ${mode} · ${provider} · ${retrievalMode}`));
    reply.append(el('p', '', safe(data.answer, 'The model returned no answer text.')));
    const sources = rows(data.sources); if (!sources.length) reply.append(el('p', 'workspace-muted', 'No passage citations were returned.'));
    sources.forEach(source => {
      const article = el('article', 'chat-source'), href = validHref(source.url); const title = el('strong');
      const citationId = safe(source.citation_id, 'source'), citationLabel = `${citationId.startsWith('[') ? citationId : `[${citationId}]`} ${safe(source.title, 'Untitled source')}`;
      if (href) title.append(link(citationLabel, href)); else title.textContent = citationLabel;
      article.append(title, el('blockquote', '', safe(source.excerpt || source.text, 'No exact excerpt was returned.')));
      if (source.locator) article.append(el('small', '', safe(source.locator)));
      const classification = safe(source.classification || source.evidence_status || source.review_status, 'unreviewed discovery').replaceAll('_', ' '); article.append(el('span', `workspace-classification${classification.includes('reviewed') && !classification.includes('unreviewed') ? ' workspace-classification--reviewed' : ''}`, classification));
      const actions = el('div', 'workspace-evidence-actions'); rows(source.node_ids).filter(id => nodeById(id)).forEach(id => { const button = el('button', 'workspace-link-button', `Graph · ${nodeName(id)}`); button.type = 'button'; button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('atlas:select-node', { detail: { node_id: id } }))); actions.append(button); });
      rows(source.claim_ids).forEach(id => { if (rows(workspace.state.claims).some(claim => claim.id === id)) { const button = el('button', 'workspace-link-button', `Claim · ${id}`); button.type = 'button'; button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: id } }))); actions.append(button); } });
      if (actions.childNodes.length) article.append(actions); reply.append(article);
    });
    const suggestions = rows(data.suggestions); if (suggestions.length) { const line = el('p', 'workspace-muted', `Possible next questions: ${suggestions.map(safe).join(' · ')}`); reply.append(line); }
    const claimIds = rows(data.claim_ids).filter(id => rows(workspace.state?.claims).some(claim => claim.id === id));
    if (claimIds.length) {
      reply.append(el('div', 'answer-label', 'Graph claims referenced'));
      const refs = el('div', 'workspace-evidence-actions');
      claimIds.forEach(id => {
        const claim = rows(workspace.state.claims).find(item => item.id === id);
        const text = `${nodeName(claim.subject)} · ${safe(claim.predicate, 'relation').replaceAll('_', ' ')} · ${nodeName(claim.object)}`;
        const button = el('button', 'workspace-link-button', text); button.type = 'button'; button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: id } }))); refs.append(button);
      });
      reply.append(refs);
    }
    $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
  }
  window.AtlasWorkspace = { get active() { return workspace.active; }, askLive, refresh };
  $('#chat-form').addEventListener('submit', event => { if (!workspace.active) return; event.preventDefault(); event.stopImmediatePropagation(); const question = $('#question').value.trim(); if (!question || workspace.asking) return; workspace.asking = true; $('#send-question').disabled = true; const claimIds = workspace.selected?.node_id ? rows(workspace.state?.claims).filter(claim => claim.subject === workspace.selected.node_id || claim.object === workspace.selected.node_id).map(claim => claim.id) : workspace.lastAskClaimIds; window.AtlasWorkspace.askLive(question, { node_id: workspace.selected?.node_id, claim_ids: claimIds }).finally(() => { workspace.asking = false; $('#send-question').disabled = !workspace.state?.model?.available; }); }, true);
  $('#question').addEventListener('keydown', event => { if (workspace.active && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.stopImmediatePropagation(); $('#chat-form').requestSubmit(); } }, true);
  refresh({ quiet: true });
})();

/* Ask Atlas is the single research interface; the server retains evidence and planning state. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const el = (tag, cls = '', text = null) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== null && text !== undefined) node.textContent = String(text); return node; };
  const safe = (value, fallback = '') => typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
  const rows = value => Array.isArray(value) ? value : [];
  const workspace = { state: null, selected: null, active: false, asking: false, pending: new Map(), observedJobs: new Set(), lastAskClaimIds: [] };
  const nodeById = id => rows(workspace.state?.nodes).find(node => node.id === id);
  const nodeName = id => safe(nodeById(id)?.label || id, 'Unlabelled record');
  const validHref = value => { try { const u = new URL(value, location.href); return ['http:', 'https:'].includes(u.protocol) ? u.href : ''; } catch (_) { return ''; } };
  const link = (label, href) => { const url = validHref(href); if (!url) return el('span', 'workspace-muted', label); const a = el('a', 'workspace-link-button', label); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = label; return a; };
  const revision = () => workspace.state?.revision;
  const status = (message, tone) => { if(tone === 'warning' || tone === 'error') $('#send-question').title = message; };
  async function request(path, { method = 'GET', body } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['X-Atlas-Token'] = safe(workspace.state?.csrf_token); }
    const response = await fetch(path, { method, credentials: 'same-origin', headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(safe(payload?.error?.message, `Request failed (${response.status}).`)); error.status = response.status; error.code = payload?.error?.code; throw error; }
    return payload;
  }
  async function refresh() {
    try {
      const data = await request('/api/research/state');
      workspace.active = true; workspace.state = data;
      document.body.dataset.workspaceReady = 'true';
      $('#send-question').disabled = workspace.asking || !data.model?.available;
      $('#send-question').title = data.model?.available ? 'Send to Atlas' : 'No research model is configured.';
      window.dispatchEvent(new CustomEvent('atlas:workspace-updated', {detail:{state:data}}));
      for(const job of rows(data.jobs)){
        if(job.kind!=='ask'||job.status!=='running'||workspace.observedJobs.has(job.id))continue;
        const reply=el('div','chat-message answer');reply.append(el('p','','Continuing your research question…'));$('#chat-messages').append(reply);
        pollAsk(job.id,reply,'');
      }
      return data;
    } catch(error) {
      workspace.active = false; workspace.state = null;
      document.body.dataset.workspaceReady = 'false';
      if(error.status !== 404) status(error.message, 'error');
      return null;
    }
  }
  window.addEventListener('atlas:node-select', event => { workspace.selected = event.detail?.node_id ? event.detail : null; });
  async function askLive(question, context) {
    if (!workspace.state?.model?.available) { status('Ask Atlas is unavailable because no live model provider is configured.', 'warning'); return; }
    const box = $('#chat-messages'), input = $('#question'); const reply = el('div', 'chat-message answer');
    box.append(el('div', 'chat-message user', question));
    const scopedQuestion = context.harvest_label ? `Selected harvested record: ${context.harvest_label}. This selection is provided as text context only; the configured retrieval corpus may not cover all harvested records. User question: ${question}` : question;
    box.append(reply); reply.append(el('p', '', 'Checking the selected graph context and cited sources…')); box.scrollTop = box.scrollHeight;
    const payload = { revision: revision(), question: scopedQuestion, ...(context.node_id ? { node_id: context.node_id } : {}), ...(context.claim_ids?.length ? { claim_ids: context.claim_ids.slice(0, 100) } : {}) };
    try {
      const job = await request('/api/atlas/ask', { method: 'POST', body: payload });
      if (job.status === 'completed') { showAskResult(job.outcome?.answer, job, reply); if (input.value === question) input.value = ''; await refresh(); }
      else { workspace.pending.set(job.id, { kind: 'ask', reply, question }); await pollAsk(job.id, reply, question); }
    } catch (error) { reply.replaceChildren(el('p', '', error.message || 'The answer could not be loaded.')); if (!input.value) input.value = question; }
    box.scrollTop = box.scrollHeight;
  }
  async function pollAsk(id, reply, question) {
    workspace.observedJobs.add(id);
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
        showAskResult(job.outcome?.answer, job, reply); if (question && $('#question').value === question) $('#question').value = '';
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
    reply.append(el('div', 'answer-label', 'Atlas'));
    reply.append(el('p', '', safe(data.answer, 'The model returned no answer text.')));
    const sources = rows(data.sources); if (!sources.length) reply.append(el('p', 'workspace-muted', 'No passage citations were returned.'));
    sources.forEach(source => {
      const article = el('details', 'chat-source'), href = validHref(source.url); const title = el('summary');
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
  $('#chat-form').addEventListener('submit', event => {
    if (!workspace.active) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const question = $('#question').value.trim(); if (!question || workspace.asking) return;
    workspace.asking = true; $('#send-question').disabled = true;
    const selectedId = workspace.selected?.node_id, inWorkspace = !!selectedId && rows(workspace.state?.nodes).some(node => node.id === selectedId);
    const claimIds = inWorkspace ? rows(workspace.state?.claims).filter(claim => claim.subject === selectedId || claim.object === selectedId).map(claim => claim.id) : selectedId ? [] : workspace.lastAskClaimIds;
    const harvestLabel = selectedId && !inWorkspace ? safe(workspace.selected?.node?.label || selectedId) : null;
    window.AtlasWorkspace.askLive(question, { ...(inWorkspace ? { node_id: selectedId } : {}), claim_ids: claimIds, ...(harvestLabel ? { harvest_label: harvestLabel } : {}) }).finally(() => {
      workspace.asking = false; $('#send-question').disabled = !workspace.state?.model?.available;
    });
  }, true);
  $('#question').addEventListener('keydown', event => { if (workspace.active && event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.stopImmediatePropagation(); $('#chat-form').requestSubmit(); } }, true);
  refresh();
})();

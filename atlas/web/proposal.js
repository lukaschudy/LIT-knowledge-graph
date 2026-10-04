(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const entry = ['chat','search'].includes(params.get('entry')) ? params.get('entry') : 'direct';
  $('query').value = (params.get('q') || '').slice(0,1000);
  if (entry === 'search') $('name').value = $('query').value.slice(0,160);
  const form = $('proposal-form'), status = $('form-status');
  const storageKey = 'atlas:proposal-requests:v1';
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  let requestId = crypto.randomUUID(), submitted = null, pending = false;
  function confirmedReceipt(result, expectedId = null) {
    if (!result || typeof result.id !== 'string' || !uuid.test(result.id) || result.status !== 'pending_review' || (expectedId && result.id !== expectedId)) {
      throw new Error('The server did not confirm this submission. Please retry.');
    }
    return result;
  }
  function showReceipt(result) {
    confirmedReceipt(result);
    $('receipt-id').textContent = 'Reference: ' + result.id;
    const url = '/propose?receipt=' + encodeURIComponent(result.id);
    $('receipt-link').href = url;
    history.replaceState(null, '', url);
    form.hidden = true; $('receipt').hidden = false; $('receipt').focus();
  }
  async function rememberRequest(content) {
    if (submitted !== null && submitted !== content) requestId = crypto.randomUUID();
    submitted = content;
    try {
      // Keep only hashes and request IDs, never proposal text. A tab reload after
      // an uncertain response can safely retry the same draft without duplicates.
      const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(content));
      const fingerprint = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2,'0')).join('');
      const stored = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
      const recent = Array.isArray(stored) ? stored.filter(item => item && typeof item.fingerprint === 'string' && uuid.test(item.requestId)) : [];
      const existing = recent.find(item => item.fingerprint === fingerprint);
      if (existing) requestId = existing.requestId;
      sessionStorage.setItem(storageKey, JSON.stringify([...recent.filter(item => item.fingerprint !== fingerprint).slice(-7), {fingerprint, requestId}]));
    } catch (_) { /* Storage or Web Crypto may be blocked; in-page retry still works. */ }
    return requestId;
  }
  async function loadReceipt(id) {
    form.hidden = true;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      if (!uuid.test(id)) throw new Error('This receipt reference is not valid.');
      const response = await fetch('/api/proposals/' + encodeURIComponent(id), {signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'Unable to load this receipt.');
      showReceipt(confirmedReceipt(result, id));
    } catch (error) {
      form.hidden = false;
      status.textContent = error.name === 'AbortError' ? 'Loading this receipt timed out. Reload to check its status again.' : (error.message || 'Unable to load this receipt. Please reload to try again.');
    } finally { clearTimeout(timeout); }
  }
  if (params.has('receipt')) loadReceipt(params.get('receipt'));
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending || !form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form));
    pending = true;
    const controls = [...form.elements].map(control => [control, control.disabled]);
    controls.forEach(([control]) => { control.disabled = true; });
    form.setAttribute('aria-busy','true');status.textContent = 'Saving your suggestion…';
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const id = await rememberRequest(JSON.stringify({...data, entry}));
      const response = await fetch('/api/proposals', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...data,entry,request_id:id}), signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'The suggestion could not be saved. Please retry.');
      showReceipt(confirmedReceipt(result));
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'Confirmation timed out. Your text is still here; retrying safely checks the same submission.' : (error.message || 'Unable to reach the inbox. Your text is still here; please retry.');
    } finally {
      clearTimeout(timeout);pending = false;form.removeAttribute('aria-busy');
      controls.forEach(([control, disabled]) => { control.disabled = disabled; });
    }
  });
})();

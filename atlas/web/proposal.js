(() => {
  const $ = id => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const entry = ['chat','search'].includes(params.get('entry')) ? params.get('entry') : 'direct';
  $('query').value = (params.get('q') || '').slice(0,1000);
  if (entry === 'search') $('name').value = $('query').value.slice(0,160);
  const form = $('proposal-form'), button = $('submit-proposal'), status = $('form-status');
  let requestId = crypto.randomUUID(), submitted = null, pending = false;
  function showReceipt(result) {
    $('receipt-id').textContent = 'Reference: ' + result.id;
    const url = '/propose?receipt=' + encodeURIComponent(result.id);
    $('receipt-link').href = url;
    history.replaceState(null, '', url);
    form.hidden = true; $('receipt').hidden = false; $('receipt').focus();
  }
  if (params.has('receipt')) {
    form.hidden = true;
    fetch('/api/proposals/' + encodeURIComponent(params.get('receipt'))).then(async response => {
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'Unable to load this receipt.');
      showReceipt(result);
    }).catch(error => {
      form.hidden = false;
      status.textContent = error.message || 'Unable to load this receipt. Please reload to try again.';
    });
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (pending || !form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form));
    const content = JSON.stringify(data);
    if (submitted !== null && submitted !== content) requestId = crypto.randomUUID();
    submitted = content;
    pending = true; button.disabled = true; status.textContent = 'Saving your suggestion…';
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('/api/proposals', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...data,entry,request_id:requestId}), signal:controller.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || 'The suggestion could not be saved. Please retry.');
      if (!result.id || result.status !== 'pending_review') throw new Error('The server did not confirm your submission. Please retry.');
      showReceipt(result);
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'Confirmation timed out. Your text is still here; retrying safely checks the same submission.' : (error.message || 'Unable to reach the inbox. Your text is still here; please retry.');
    } finally {clearTimeout(timeout);pending = false;button.disabled = false;}
  });
})();

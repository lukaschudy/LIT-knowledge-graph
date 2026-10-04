/* Read-only smoke check for the graph-integrated research workspace.
 * Start the local Atlas server, then run with NODE_PATH pointing at Playwright.
 * It does not submit forms, search, review claims, or call a model.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (request.method() !== 'GET' && request.url().includes('/api/')) writes.push(`${request.method()} ${request.url()}`); });

    const response = await page.goto(process.env.ATLAS_URL || 'http://127.0.0.1:8767/research');
    assert.ok(response && response.ok(), 'research route should load or redirect successfully');
    await page.waitForURL(/\/explore(?:\?|$)/);
    await page.locator('#network').waitFor({ state: 'visible' });
    await page.locator('#options-toggle').click();
    await page.locator('#graph-options:not([hidden])').waitFor();
    await page.locator('#harvest-status').waitFor({state:'attached'});
    assert.ok((await page.locator('#harvest-status').innerText()).length > 0, 'harvest coverage state should be explained');
    assert.equal(await page.locator('#graph-scope option').count(), 2, 'resolved and full-harvest scopes should both be available');
    const resolvedAvailable = await page.evaluate(async () => { const r = await fetch('/api/resolved/status'); return r.ok; });
    assert.equal(await page.locator('#graph-scope').inputValue(), resolvedAvailable ? 'resolved' : 'harvest', 'use resolved neuro by default when the route is available');
    await page.locator('#graph-scope').selectOption('harvest');
    await page.locator('#harvest-status').waitFor({state:'visible'});
    assert.equal(await page.locator('#harvest-limit option').count(), 3, 'full-harvest page budgets should be available');
    assert.equal(await page.locator('#harvest-limit').inputValue(), '10000', 'all-harvest view defaults to the dense 10,000-node page');
    const harvestData = await page.evaluate(async () => {
      const [statusResponse, datasetsResponse] = await Promise.all([fetch('/api/harvest/status'), fetch('/api/harvest/datasets')]);
      if (!statusResponse.ok || !datasetsResponse.ok) return null;
      return { status: await statusResponse.json(), datasets: await datasetsResponse.json() };
    });
    if (harvestData) {
      const totalNodes = Number(harvestData.status.total_nodes || 0);
      if (totalNodes) await page.waitForFunction(expected => document.querySelector('#harvest-status').textContent.includes(expected), `${totalNodes.toLocaleString()} nodes`);
      await page.locator('#harvest-browse').click();
      await page.locator('#harvest-datasets-dialog[open]').waitFor();
      await page.waitForFunction(() => document.querySelectorAll('#harvest-dataset-select option').length > 0);
      await page.locator('#harvest-record-status').waitFor();
      const inspect = page.locator('#harvest-record-list .harvest-record-item button').first();
      await inspect.waitFor({state:'visible'});
      if (await inspect.count()) {
        await inspect.click();
        await page.locator('#record-dialog[open]').waitFor();
        await page.locator('#record-content .harvest-record-json').waitFor();
        assert.ok(Object.keys(JSON.parse(await page.locator('#record-content .harvest-record-json').innerText())).length > 0);
        assert.match(await page.locator('#record-content').innerText(), /GENE SYMBOL|recorded source URL|harvested source/i, 'raw harvested record should be inspectable');
        await page.locator('#record-close').click();
      }
      await page.locator('#harvest-datasets-close').click();
      const firstNode = await page.evaluate(async () => {
        const response = await fetch('/api/harvest/graph?limit=1000&offset=0');
        if (!response.ok) return null; const graph = await response.json();
        return { id: graph.nodes?.[0]?.id, label: graph.nodes?.[0]?.label, claim_id: graph.claims?.[0]?.id };
      });
      if (firstNode?.id) {
        if (firstNode.label) {
          await page.locator('#node-search').fill(firstNode.label);
          await page.locator('.harvest-search-heading').waitFor({ timeout: 10000 });
          assert.ok((await page.locator('.harvest-search-heading').innerText()).includes('Harvest index'), 'full harvest search results should be labeled');
        }
        await page.evaluate(id => window.dispatchEvent(new CustomEvent('atlas:select-node', { detail: { node_id: id } })), firstNode.id);
        await page.locator('#inspect-selected').waitFor({ state: 'visible' });
        await page.locator('#inspect-selected').click();
        await page.locator('#record-dialog[open]').waitFor();
        await page.locator('#record-content .harvest-record-json').waitFor();
        assert.ok(Object.keys(JSON.parse(await page.locator('#record-content .harvest-record-json').innerText())).length > 0);
        assert.match(await page.locator('#record-content').innerText(), /raw harvested record|harvested source/i, 'selected graph node should open raw provenance');
        await page.locator('#record-close').click();
      }
      if (firstNode?.claim_id) {
        await page.evaluate(id => window.dispatchEvent(new CustomEvent('atlas:open-claim', { detail: { claim_id: id } })), firstNode.claim_id);
        await page.locator('#record-dialog[open]').waitFor();
        await page.locator('#record-content .harvest-record-json').waitFor();
        assert.ok(Object.keys(JSON.parse(await page.locator('#record-content .harvest-record-json').innerText())).length > 0);
        assert.match(await page.locator('#record-content').innerText(), /raw harvested record|harvested source|harvested relationship/i, 'harvested edge should open source provenance');
        await page.locator('#record-close').click();
      }
    }
    if (resolvedAvailable) {
      await page.locator('#options-toggle').click();
      await page.locator('#graph-options:not([hidden])').waitFor();
      await page.locator('#graph-scope').selectOption('resolved');
      await page.locator('#resolved-status').waitFor({state:'visible'});
      await page.waitForFunction(() => document.querySelectorAll('#nodes .net-node').length > 0);
      assert.equal(await page.locator('#harvest-limit').inputValue(), '120', 'resolved neuro defaults to a focused page');
      const resolved = await page.evaluate(async () => { const r = await fetch('/api/resolved/graph?limit=120'); return r.ok ? r.json() : null; });
      assert.ok(resolved?.nodes?.length, 'resolved overview should return graph nodes');
      await page.evaluate(id => window.dispatchEvent(new CustomEvent('atlas:select-node', {detail:{node_id:id}})), resolved.nodes[0].id);
      await page.locator('#inspect-selected').waitFor({state:'visible'});
      await page.locator('#inspect-selected').click();
      await page.locator('#record-dialog[open]').waitFor();
      await page.getByRole('heading', {name:'Identity members'}).waitFor();
      assert.ok((await page.locator('#record-content').innerText()).length > 40, 'resolved node inspector should show identity/provenance details');
      const originalRecord = page.locator('#record-content .workspace-link-button').filter({hasText:'Open original record'}).first();
      await originalRecord.waitFor({state:'visible'});
      await originalRecord.click();
      await page.locator('#record-content .harvest-record-json').waitFor();
      assert.ok(Object.keys(JSON.parse(await page.locator('#record-content .harvest-record-json').innerText())).length > 0, 'resolved identity member should open its original source row');
      await page.locator('#record-close').click();
      const resolvedClaim = resolved.claims?.find(claim => String(claim.id).startsWith('claim:extracted:'));
      if (resolvedClaim) {
        const claimDetails = await page.evaluate(async id => { const r = await fetch(`/api/resolved/claim?id=${encodeURIComponent(id)}`); return r.ok ? r.json() : null; }, resolvedClaim.id);
        assert.ok(claimDetails?.support?.[0]?.excerpt, 'an extracted model claim should have a source-grounded excerpt');
        await page.evaluate(id => window.dispatchEvent(new CustomEvent('atlas:open-claim', {detail:{claim_id:id}})), resolvedClaim.id);
        await page.locator('#record-dialog[open]').waitFor();
        const quote = page.locator('#record-content blockquote').first();
        await quote.waitFor({state:'visible'});
        assert.equal(await quote.innerText(), claimDetails.support[0].excerpt, 'model claim inspector must display the exact source quote');
        assert.match(await page.locator('#record-content').innerText(), /not calibrated|not approved/i, 'machine confidence must not be presented as scientific certainty');
        await page.locator('#record-close').click();
      }
    }
    await page.locator('#options-toggle').click();
    await page.locator('#workspace-toggle').click();
    await page.locator('#workspace-panel:not([hidden])').waitFor();
    await page.getByRole('tab', { name: 'Literature' }).waitFor();
    await page.getByRole('tab', { name: 'Evidence / review' }).click();
    await page.locator('#workspace-claims').waitFor();
    await page.getByRole('tab', { name: 'Plan' }).click();
    await page.locator('#workspace-request-form').waitFor();
    await page.getByRole('tab', { name: 'Brief' }).click();
    const brief = page.locator('#workspace-brief');
    await brief.waitFor();
    assert.ok((await brief.inputValue()).length > 0, 'brief should be populated');

    await page.getByRole('tab', { name: 'Evidence / review' }).click();
    const cite = page.locator('#workspace-claims .workspace-link-button').first();
    if (await cite.count()) {
      await cite.click();
      await page.locator('#record-dialog[open]').waitFor();
      assert.ok((await page.locator('#record-content').innerText()).length > 0, 'source dialog should show evidence details');
      await page.locator('#record-close').click();
    }

    await page.screenshot({ path: '/tmp/atlas-integrated-desktop.png', fullPage: true });
    const widths = {};
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      widths[width] = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
      assert.ok(widths[width].document <= width, `document overflows at ${width}px: ${JSON.stringify(widths[width])}`);
      assert.ok(widths[width].body <= width, `body overflows at ${width}px: ${JSON.stringify(widths[width])}`);
      await page.locator('#chat-toggle').click();
      assert.equal(await page.locator('#workspace-panel').isVisible(), false, 'chat closes the research drawer');
      const sendIsUncovered = await page.locator('#send-question').evaluate(button => {
        const box = button.getBoundingClientRect();
        return !!document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)?.closest('#send-question');
      });
      assert.equal(sendIsUncovered, true, `Send button is obscured at ${width}px`);
      await page.locator('#chat-close').click();
      await page.locator('#workspace-toggle').click();
    }
    assert.deepEqual(writes, [], 'QA must not submit any API writes');
    assert.deepEqual(errors, [], 'no JavaScript runtime errors');
    console.log(JSON.stringify({ pass: true, route: page.url(), widths, runtimeErrors: errors, writes }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

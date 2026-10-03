/* Optional read-only browser smoke check. Install playwright separately, start
 * `python3 -m atlas research`, then run with NODE_PATH pointing to its node_modules.
 * ATLAS_URL may select another local research server. No model calls or reviews.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.ATLAS_URL || 'http://127.0.0.1:8767/research');
    await page.locator('#app').waitFor({ state: 'visible' });
    await page.locator('.claim-card').first().waitFor();
    assert.ok((await page.locator('#brief-editor').inputValue()).length);
    await page.locator('.citation-link').first().click();
    await page.locator('#evidence-dialog').waitFor({ state: 'visible' });
    assert.match(await page.locator('#evidence-detail').innerText(), /Claim review status/);
    await page.locator('#close-evidence').click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      const overflow = await page.evaluate(() => document.body.scrollWidth > innerWidth);
      assert.equal(overflow, false, `Horizontal overflow at width ${width}`);
    }
    assert.deepEqual(errors, []);
    console.log('PASS: research render, source dialog, populated brief, desktop/mobile widths; no mutations or model calls.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

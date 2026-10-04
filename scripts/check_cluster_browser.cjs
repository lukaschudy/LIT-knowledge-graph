/* Offline reviewed-evidence dialog regressions; all routes are intercepted. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const buildDir = process.env.ATLAS_CLUSTER_BUILD_DIR;
  const html = await fs.readFile(process.env.ATLAS_CLUSTER_HTML || (buildDir ? path.join(buildDir, 'cluster.html') : path.join(root, 'atlas/cluster_web.html')), 'utf8');
  const cluster = JSON.parse(await fs.readFile(path.join(root, 'data/curated/grin_cluster_demo_v2.json'), 'utf8'));
  const records = [...cluster.observations, ...cluster.claims];
  const browser = await chromium.launch({headless:true});
  const passed = [], failures = [];
  async function fixture(name, run) {
    const page = await browser.newPage(), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {window.__cspViolations=[];document.addEventListener('securitypolicyviolation',event=>window.__cspViolations.push(event.violatedDirective));});
    let responder = async (route, id) => route.fulfill({json:{record:records.find(record => record.id === id), spans:[{locator:id, quote:'Offline fixture ' + id}]}});
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/cluster') return route.fulfill({json:cluster});
      if (url.pathname === '/api/evidence') return responder(route, url.searchParams.get('id'));
      if (buildDir && ['/cluster.js','/cluster.css'].includes(url.pathname)) return route.fulfill({contentType:url.pathname.endsWith('.js')?'text/javascript':'text/css',body:await fs.readFile(path.join(buildDir,url.pathname.slice(1)),'utf8')});
      return route.fulfill({contentType:'text/html',body:html,headers:buildDir?{'Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}:{}});
    });
    try {
      await page.goto('http://atlas.test/cluster');
      await page.locator('#rows button').first().waitFor();
      await run(page, fn => { responder = fn; });
      assert.deepEqual(errors, []);
      assert.deepEqual(await page.evaluate(()=>window.__cspViolations), []);
      passed.push(name); console.log('PASS ' + name);
    } catch (error) { failures.push({name,error:error.message.slice(0,1000)}); console.error('FAIL ' + name + ': ' + error.message.slice(0,1000)); }
    finally { await page.close(); }
  }
  try {
    await fixture('closed evidence response cannot replace the latest source', async (page, respond) => {
      let release, arrived; const gate = new Promise(resolve => {release = resolve;}); const requested = new Promise(resolve => {arrived = resolve;}); const calls = [];
      respond(async (route, id) => {calls.push(id); if (calls.length === 1) {arrived(); await gate;} await route.fulfill({json:{record:records.find(record => record.id === id),spans:[{locator:id}]}}).catch(() => {});});
      await page.locator('#rows button').nth(0).click(); await requested; await page.locator('#close').click();
      await page.locator('#rows button').nth(1).click(); await page.locator('#evidenceBody .locator').waitFor();
      assert.equal(await page.locator('#evidenceBody .locator').innerText(), calls[1]);
      release(); await delay(150);
      assert.equal(await page.locator('#evidenceBody .locator').innerText(), calls[1]);
    });
    await fixture('source timeout remains recoverable by reopening', async (page, respond) => {
      let calls = 0;
      await page.evaluate(() => {const original = setTimeout; window.setTimeout = (fn, ms, ...args) => original(fn, ms === 20000 ? 50 : ms, ...args);});
      respond(async (route, id) => {if (++calls === 1) await delay(200); await route.fulfill({json:{record:records.find(record => record.id === id),spans:[{locator:id}]}}).catch(() => {});});
      await page.locator('#rows button').first().click();
      await page.waitForFunction(() => document.querySelector('#evidenceBody').textContent.includes('timed out'), null, {timeout:1000});
      await page.locator('#close').click(); await page.locator('#rows button').first().click();
      await page.locator('#evidenceBody .locator').waitFor(); assert.equal(calls, 2);
    });
    await fixture('mismatched evidence identity is not displayed', async (page, respond) => {
      respond((route,id) => route.fulfill({json:{record:records.find(record => record.id !== id),spans:[{locator:'WRONG SOURCE'}]}}));
      await page.locator('#rows button').first().click();
      await page.waitForFunction(() => document.querySelector('#evidenceBody').textContent.includes('incomplete'), null, {timeout:1000});
      assert.equal(await page.locator('#evidenceBody .locator').count(), 0);
    });
  } finally { await browser.close(); }
  console.log(JSON.stringify({passed,failures},null,2)); if (failures.length) process.exitCode = 1;
})().catch(error => {console.error(error);process.exitCode = 1;});

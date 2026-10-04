/* Dense renderer regression check; test hooks are injected only into this tab.
 * Reads the running local server. Does not modify data or invoke models.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/graph.js', async route => {
      const response = await route.fetch();
      const code = (await response.text()).replace('  init();', `
        window.__graphTest = {
          snapshot:()=>({nodes:nodes.map(n=>({id:n.id,label:n.label,x:n.screenX,y:n.screenY,r:n.screenR,hidden:n.hidden,mounted:!!n.el})),hovered,selected}),
          edge:()=>({id:edges[0].claim.id,subject:edges[0].a.id}),
          pick:(x,y,touch=false)=>nodeAt({clientX:x,clientY:y,pointerType:touch?'touch':'mouse'})
        };
        init();`);
      await route.fulfill({response,body:code});
    });
    await page.goto(process.env.ATLAS_URL || 'http://127.0.0.1:8767/explore');
    await page.waitForFunction(()=>Number(document.querySelector('#network').dataset.nodeCount)>=10000);
    await page.waitForFunction(()=>document.body.dataset.workspaceReady==='true');
    await page.waitForTimeout(400);
    const originalCount = Number(await page.locator('#network').getAttribute('data-node-count'));
    assert.ok(await page.locator('#nodes .net-node').count() <= 40, 'dense overview must not create thousands of DOM targets');
    const target = await page.evaluate(()=>window.__graphTest.snapshot().nodes.find(n=>!n.mounted && n.x>300 && n.x<1000 && n.y>200 && n.y<650));
    assert.ok(target, 'test a node that has no DOM control');
    await page.locator('#node-search').fill(target.label);
    await page.locator('#node-search').press('Enter');
    await page.waitForFunction(id=>window.__graphTest.snapshot().selected===id,target.id);
    assert.equal(await page.locator('#selection-name').innerText(), target.label);
    assert.ok(await page.locator('#nodes .net-node').count() < 150);
    assert.equal(await page.locator('#nodes .selected').getAttribute('data-node'),target.id);
    await page.locator('#clear-selection').click();
    await page.mouse.move(1300,700);await page.mouse.down();
    await page.mouse.move(1120,620,{steps:12});await page.mouse.up();
    await page.mouse.wheel(0,-180);await page.waitForTimeout(350);
    // Compare the spatial index with the original exhaustive nearest-point rule.
    const picks = await page.evaluate(()=>{
      const {nodes,hovered}=window.__graphTest.snapshot();
      const results=[];
      for(const touch of [false,true])for(let x=20;x<innerWidth;x+=47)for(let y=100;y<innerHeight-80;y+=43){
        const current=nodes.find(n=>n.id===hovered);let expected=null,distance=touch?20:10;
        if(current&&!current.hidden&&Math.hypot(x-current.x,y-current.y)<Math.max(12,current.r+7))expected=current.id;
        else for(const n of nodes){if(n.hidden)continue;const d=Math.hypot(x-n.x,y-n.y);if(d<distance){expected=n.id;distance=d;}}
        const actual=window.__graphTest.pick(x,y,touch);
        if(actual!==expected)results.push({x,y,touch,expected,actual});
      }
      return results;
    });
    assert.deepEqual(picks, [], 'screen-space index must preserve mouse and touch picking after orbit/zoom');
    const click = await page.evaluate(()=>{
      const {nodes}=window.__graphTest.snapshot();
      const n=nodes.find(n=>!n.mounted&&!n.hidden&&n.x>300&&n.x<1000&&n.y>200&&n.y<650);
      return {x:n.x,y:n.y,id:window.__graphTest.pick(n.x,n.y)};
    });
    await page.mouse.click(click.x,click.y);
    await page.waitForFunction(id=>window.__graphTest.snapshot().selected===id,click.id);
    assert.equal(Number(await page.locator('#network').getAttribute('data-node-count')),originalCount,'interactions retain every node');
    const edge=await page.evaluate(()=>window.__graphTest.edge());
    await page.evaluate(id=>window.dispatchEvent(new CustomEvent('atlas:select-node',{detail:{node_id:id}})),edge.subject);
    const edgeTarget=page.locator('#links .edge-group').filter({has:page.locator('path')});
    assert.ok(await edgeTarget.count()>0,'selected relationships expose evidence controls');
    await edgeTarget.first().press('Enter');
    await page.locator('#record-dialog[open]').waitFor();
    await page.locator('#record-content .harvest-record-json').waitFor();
    await page.locator('#record-close').click();
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({pass:true,nodes:originalCount,targets:await page.locator('#nodes .net-node').count(),pickingMismatches:picks.length,errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});

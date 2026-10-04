/* Dense renderer regression check; test hooks are injected only into this tab.
 * Reads the running local server. Does not modify data or invoke models.
 */
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({headless:true,args:process.env.ATLAS_DISABLE_WEBGL?['--disable-webgl']:[]});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/graph.js', async route => {
      const response = await route.fetch();
      const code = (await response.text()).replace('  init();', `
        window.__graphTest = {
          snapshot:()=>({view:{...view},wheeling:!!wheelZoom,nodes:nodes.map(n=>({id:n.id,label:n.label,x:n.screenX,y:n.screenY,r:n.screenR,hidden:n.hidden,mounted:!!n.el})),hovered,selected}),
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
    const renderer=await page.locator('#graph-paint').getAttribute('data-renderer');
    assert.ok(['webgl','canvas'].includes(renderer));
    if(renderer==='webgl')assert.equal(await page.evaluate(()=>document.querySelector('#graph-paint').getContext('webgl').getError()),0,'GPU shaders and buffers must render without errors');
    // A physical wheel zooms around its cursor and returns to the same view.
    await page.mouse.move(1100,600);
    const start=await page.evaluate(()=>window.__graphTest.snapshot().view);
    await page.mouse.wheel(0,-400);
    await page.waitForFunction(k=>!window.__graphTest.snapshot().wheeling&&window.__graphTest.snapshot().view.k>k,start.k);
    const zoomed=await page.evaluate(()=>window.__graphTest.snapshot().view);
    assert.ok(zoomed.k>start.k*1.8,'wheel up must visibly zoom in');
    assert.ok(Math.abs((1100-start.x)/start.k-(1100-zoomed.x)/zoomed.k)<.01,'keep the point under the mouse anchored');
    await page.mouse.wheel(0,400);
    await page.waitForFunction(()=>!window.__graphTest.snapshot().wheeling);
    await page.waitForTimeout(250);
    const restored=await page.evaluate(()=>window.__graphTest.snapshot().view);
    assert.ok(Math.abs(restored.k-start.k)<.001,'wheel down must reverse wheel up');
    // Browsers report wheel deltas in pixels, lines, or pages.
    for(const mode of [1,2]){
      const before=await page.evaluate(()=>window.__graphTest.snapshot().view.k);
      await page.locator('#network').dispatchEvent('wheel',{deltaY:mode===1?-6:-.2,deltaMode:mode,clientX:1100,clientY:600});
      await page.waitForFunction(k=>!window.__graphTest.snapshot().wheeling&&window.__graphTest.snapshot().view.k>k,before);
      assert.ok((await page.evaluate(()=>window.__graphTest.snapshot().view.k))>before*1.1,'normalize line/page wheel deltas');
    }
    for(const [delta,limit] of [[1000,.015],[-1000,12]]){
      await page.evaluate(delta=>{for(let i=0;i<24;i++)document.querySelector('#network').dispatchEvent(new WheelEvent('wheel',{deltaY:delta,clientX:1100,clientY:600,cancelable:true}));},delta);
      await page.waitForFunction(k=>!window.__graphTest.snapshot().wheeling&&Math.abs(window.__graphTest.snapshot().view.k-k)<.0001,limit);
    }
    await page.locator('#network').press('0');
    await page.waitForTimeout(250);

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
    if(renderer==='webgl'){
      await page.evaluate(()=>document.querySelector('#graph-paint').getContext('webgl').getExtension('WEBGL_lose_context').loseContext());
      await page.waitForFunction(()=>document.querySelector('#graph-paint').dataset.renderer==='canvas');
      await page.mouse.move(1000,600);await page.mouse.wheel(0,-200);await page.waitForTimeout(350);
      assert.equal(Number(await page.locator('#network').getAttribute('data-node-count')),originalCount,'context loss preserves the graph and zoom');
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({pass:true,renderer,wheelModes:['pixels','lines','pages'],zoomRange:[.015,12],nodes:originalCount,targets:await page.locator('#nodes .net-node').count(),pickingMismatches:picks.length,errors},null,2));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});

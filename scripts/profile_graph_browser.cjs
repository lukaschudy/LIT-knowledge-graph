/* Local development benchmark. Instruments renderer timings only in this test tab. */
const {chromium}=require('playwright');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:Number(process.env.DPR||1)});
 const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
 await page.route('**/graph.js',async route=>{
  const response=await route.fetch();let code=process.env.GRAPH_SCRIPT ? fs.readFileSync(process.env.GRAPH_SCRIPT,'utf8') : await response.text();
  code=code.replace('  init();',`  window.__profile={timings:{},frames:[],counts:[]};
  const measure=(name,original)=>function(...args){const start=performance.now();try{return original(...args);}finally{(window.__profile.timings[name]??=[]).push(performance.now()-start);}};
  drawGraph=measure('drawGraph',drawGraph);syncOverlay=measure('syncOverlay',syncOverlay);highlight=measure('highlight',highlight);nodeAt=measure('nodeAt',nodeAt);render=measure('render',render);
  window.__profile.startIdle=()=>{document.activeElement?.blur();idleAfter=0;};
  window.addEventListener('atlas:graph-updated',e=>window.__profile.counts.push(e.detail));
  let previous=0;function sample(t){if(previous)window.__profile.frames.push(t-previous);previous=t;requestAnimationFrame(sample);}requestAnimationFrame(sample);
  init();`);
  await route.fulfill({response,body:code});
 });
 const started=Date.now();await page.goto(process.env.ATLAS_URL||'http://127.0.0.1:8767/explore');
 await page.waitForFunction(()=>window.__profile?.counts.some(x=>x.nodes>=10000));
 await page.waitForFunction(()=>document.body.dataset.workspaceReady==='true');
 const startupMs=Date.now()-started;
 await page.waitForTimeout(2000);
 await page.evaluate(()=>{window.__profile.timings={};window.__profile.frames=[];window.__profile.startIdle();});
 await page.waitForTimeout(2500);
 const idle=await page.evaluate(()=>({timings:window.__profile.timings,frames:window.__profile.frames,counts:window.__profile.counts}));
 await page.evaluate(()=>{window.__profile.timings={};window.__profile.frames=[];});
 await page.mouse.move(1300,700);await page.mouse.down();
 for(let i=0;i<40;i++)await page.mouse.move(1300-i*12,700-i*4);
 await page.mouse.up();
 await page.mouse.wheel(0,-160);await page.waitForTimeout(600);
 const interaction=await page.evaluate(()=>({timings:window.__profile.timings,frames:window.__profile.frames,counts:window.__profile.counts}));
 const dom=await page.evaluate(()=>({elements:document.querySelectorAll('*').length,nodeTargets:document.querySelectorAll('#nodes .net-node').length,edgeTargets:document.querySelectorAll('#links .edge-group').length}));
 function summary(samples){const sorted=[...samples].sort((a,b)=>a-b);return {samples:sorted.length,medianMs:+(sorted[Math.floor(sorted.length*.5)]||0).toFixed(2),p95Ms:+(sorted[Math.floor(sorted.length*.95)]||0).toFixed(2),maxMs:+(sorted.at(-1)||0).toFixed(2)};}
 const summarize=section=>({frames:summary(section.frames),timings:Object.fromEntries(Object.entries(section.timings).map(([k,v])=>[k,summary(v)]))});
 const renderer=await page.locator('#graph-paint').getAttribute('data-renderer');
 const result={startupMs,renderer,graph:interaction.counts.at(-1),dom,idle:summarize(idle),interaction:summarize(interaction),errors};
 if(process.env.OUTPUT)fs.writeFileSync(process.env.OUTPUT,JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result,null,2));if(errors.length)process.exitCode=1;
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

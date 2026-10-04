/* Real browser MediaRecorder with a fake microphone; transcription is stubbed.
 * No physical microphone, model calls, or production writes. */
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const html=`<!doctype html><form id="chat-form"><section id="chat-panel"><textarea id="question" maxlength="1000">Demo comparison question</textarea><button id="voice-button" type="button">Mic</button><span id="voice-status"></span><button id="cancel-recording" type="button" hidden>Cancel</button><button type="submit">Send</button></section></form><script src="/voice.js"></script>`;
(async()=>{
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/voice.js'?'text/javascript':'text/html');res.end(req.url==='/voice.js'?fs.readFileSync(path.join(root,'atlas/web/voice.js')):html);});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream']});
 const results=[];
 try{
  const context=await browser.newContext({permissions:['microphone']});
  const page=await context.newPage();let submits=0,localState=0,uploads=0,mode='success',pending,release;
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(()=>{
   const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
   window.tracks=[];navigator.mediaDevices.getUserMedia=async opts=>{if(window.denyMic)throw new DOMException('Denied','NotAllowedError');const stream=await original(opts);window.tracks.push(...stream.getTracks());return stream;};
   window.addEventListener('DOMContentLoaded',()=>document.querySelector('#chat-form').addEventListener('submit',e=>{e.preventDefault();window.submitted=(window.submitted||0)+1;}));
  });
  await page.route('**/api/voice/status',route=>route.fulfill({json:{available:true,requires_token:false,provider:'cloudflare_workers_ai',message:'Dictation via Cloudflare'}}));
  await page.route('**/api/research/state',route=>{localState++;return route.fulfill({status:404,json:{}});});
  await page.route('**/api/voice/transcribe',async route=>{
   uploads++;assert.ok(route.request().postDataBuffer().length>0);assert.match(route.request().headers()['content-type'],/^audio\//);assert.equal(route.request().headers()['x-atlas-token'],undefined);
   if(mode==='late'){pending();await new Promise(resolve=>release=resolve);}
   await route.fulfill(mode==='failure'?{status:503,json:{error:{message:'Service unavailable. Try again.'}}}:{json:{text:mode==='silence'?'':'What is known about GRIN2B?'}}).catch(()=>{});
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const state=phase=>page.waitForFunction(p=>document.querySelector('#voice-button').dataset.state===p,phase);
  const start=async()=>{await page.locator('#voice-button').click();await state('recording');await page.waitForTimeout(350);};
  const stop=async()=>{await page.locator('#voice-button').click();await state('idle');};
  const released=async()=>assert.ok(await page.evaluate(()=>window.tracks.every(t=>t.readyState==='ended')));
  await page.waitForFunction(()=>!document.querySelector('#voice-button').disabled);
  await start();await page.locator('#question').press('Enter');await state('idle');
  assert.equal(await page.locator('#question').inputValue(),'What is known about GRIN2B?');
  assert.equal(await page.evaluate(()=>window.submitted||0),0);assert.equal(localState,0);await released();results.push('hosted capture replaces untouched prefill; Enter stops without submitting');
  await page.locator('#question').fill('My own draft.');await start();await stop();assert.equal(await page.locator('#question').inputValue(),'My own draft. What is known about GRIN2B?');results.push('user draft preserved');
  await page.locator('#question').fill('Keep this.');await start();await page.locator('#cancel-recording').click();await state('idle');await released();assert.equal(await page.locator('#question').inputValue(),'Keep this.');results.push('cancel releases microphone');
  await start();await page.evaluate(()=>document.querySelector('#chat-panel').hidden=true);await state('idle');await released();await page.evaluate(()=>document.querySelector('#chat-panel').hidden=false);results.push('closing chat cancels capture');
  mode='late';let arrived=new Promise(resolve=>pending=resolve);await start();await page.locator('#voice-button').click();await arrived;await page.locator('#cancel-recording').click();release();await page.waitForTimeout(100);assert.equal(await page.locator('#question').inputValue(),'Keep this.');results.push('cancel discards late transcript');
  mode='silence';await start();await stop();assert.match(await page.locator('#voice-status').innerText(),/No speech/);assert.equal(await page.locator('#question').inputValue(),'Keep this.');results.push('silence preserves draft');
  mode='failure';await start();await stop();assert.match(await page.locator('#voice-status').innerText(),/unavailable/);assert.equal(await page.locator('#voice-button').isDisabled(),false);results.push('service failure permits retry');
  await page.evaluate(()=>window.denyMic=true);await page.locator('#voice-button').click();await page.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('denied'));assert.equal(await page.locator('#voice-button').isDisabled(),false);results.push('permission denial permits retry');
  await page.evaluate(()=>window.denyMic=false);mode='late';arrived=new Promise(resolve=>pending=resolve);await start();await page.locator('#voice-button').click();await arrived;await page.locator('#question').fill('Edited while waiting.');release();await state('idle');assert.equal(await page.locator('#question').inputValue(),'Edited while waiting. What is known about GRIN2B?');results.push('edits during transcription retained');
  await released();assert.deepEqual(errors,[]);assert.ok(uploads>=6);console.log(JSON.stringify({passed:results.length,results,errors},null,2));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

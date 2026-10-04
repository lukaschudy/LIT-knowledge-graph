/* Real MediaRecorder + local transcription, using synthetic WAV microphone input.
 * ATLAS_TEST_AUDIO is required. Ask Atlas's model response is stubbed: no model
 * calls or workspace writes. Denied permission and cancellation are also checked.
 */
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
  assert.ok(process.env.ATLAS_TEST_AUDIO,'Set ATLAS_TEST_AUDIO to a WAV saying a short research question.');
  const browser=await chromium.launch({headless:true,args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${process.env.ATLAS_TEST_AUDIO}`]});
  try{
    const context=await browser.newContext({permissions:['microphone'],viewport:{width:1440,height:900}});
    const page=await context.newPage(),errors=[],asks=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(()=>{
      const get=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      window.testTracks=[];
      navigator.mediaDevices.getUserMedia=async constraints=>{const stream=await get(constraints);window.testTracks.push(...stream.getTracks());return stream;};
    });
    await page.route('**/api/atlas/ask',async route=>{
      asks.push(route.request().postDataJSON());
      await route.fulfill({json:{id:'voice-test',status:'completed',outcome:{answer:{answer:'Voice question received by Ask Atlas.',metadata:{provider:'test',mode:'mock'},sources:[{citation_id:'1',title:'Research source',excerpt:'Exact source excerpt for the test.',classification:'unreviewed_discovery'}]}}}});
    });
    await page.goto(process.env.ATLAS_URL||'http://127.0.0.1:8767/explore');
    await page.locator('#chat-toggle').click();
    await page.waitForFunction(()=>!document.querySelector('#voice-button').disabled);
    await page.locator('#voice-button').click();
    await page.waitForFunction(()=>document.querySelector('#voice-button').dataset.state==='recording');
    await page.waitForTimeout(3700);
    // Enter finishes recording without submitting a partial/previous draft.
    await page.locator('#question').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#voice-button').dataset.state==='idle'&&document.querySelector('#question').value,{},{timeout:120000});
    const transcript=await page.locator('#question').inputValue();
    assert.match(transcript,/evidence/i);
    assert.match(transcript,/neurodevelopmental/i);
    assert.equal(asks.length,0,'speech remains a draft until explicitly submitted');
    assert.ok(await page.evaluate(()=>window.testTracks.every(t=>t.readyState==='ended')),'microphone released after recording');
    await page.locator('#send-question').click();
    await page.getByText('Voice question received by Ask Atlas.',{exact:true}).waitFor();
    assert.equal(asks.length,1);assert.equal(asks[0].question,transcript);
    assert.equal(await page.locator('.chat-source blockquote').isVisible(),false,'source excerpts stay collapsed until requested');
    await page.locator('.chat-source summary').press('Enter');
    assert.equal(await page.locator('.chat-source blockquote').innerText(),'Exact source excerpt for the test.');
    assert.equal(await page.locator('.chat-source blockquote').isVisible(),true);
    assert.equal(await page.locator('#workspace-toggle').count(),0,'research answers live in Ask Atlas');
    await page.locator('#question').fill('Keep this draft.');
    await page.locator('#voice-button').click();
    await page.waitForFunction(()=>document.querySelector('#voice-button').dataset.state==='recording');
    await page.locator('#cancel-recording').click();
    assert.equal(await page.locator('#question').inputValue(),'Keep this draft.');
    assert.ok(await page.evaluate(()=>window.testTracks.every(t=>t.readyState==='ended')));
    await page.locator('#voice-button').click();
    await page.waitForFunction(()=>document.querySelector('#voice-button').dataset.state==='recording');
    await page.locator('#chat-close').click();
    await page.waitForFunction(()=>window.testTracks.every(t=>t.readyState==='ended'));
    assert.equal(await page.locator('#question').inputValue(),'Keep this draft.');
    // Delay a response, cancel transcription, then ensure it cannot mutate a draft.
    await page.locator('#chat-toggle').click();
    let release,arrived;
    const pending=new Promise(resolve=>arrived=resolve),gate=new Promise(resolve=>release=resolve);
    await page.route('**/api/voice/transcribe',async route=>{arrived();await gate;await route.fulfill({json:{text:'Late transcript must not appear.'}}).catch(()=>{});});
    await page.locator('#voice-button').click();
    await page.waitForFunction(()=>document.querySelector('#voice-button').dataset.state==='recording');
    await page.waitForTimeout(400);await page.locator('#voice-button').click();await pending;
    await page.locator('#cancel-recording').click();release();await page.waitForTimeout(200);
    assert.equal(await page.locator('#question').inputValue(),'Keep this draft.');
    const denied=await context.newPage();
    await denied.addInitScript(()=>{navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Denied','NotAllowedError');};});
    await denied.goto(process.env.ATLAS_URL||'http://127.0.0.1:8767/explore');
    await denied.locator('#chat-toggle').click();await denied.waitForFunction(()=>!document.querySelector('#voice-button').disabled);
    await denied.locator('#voice-button').click();
    await denied.waitForFunction(()=>document.querySelector('#voice-status').textContent.includes('denied'));
    assert.equal(await denied.locator('#voice-button').isDisabled(),false,'permission denial permits retry');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({pass:true,transcript,askRequests:asks.length,permissionDenial:true,cancellation:true,lateTranscriptDiscarded:true,microphoneReleased:true,errors},null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

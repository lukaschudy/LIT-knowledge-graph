/* Microphone -> local transcription -> editable Ask Atlas draft. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const button=$('voice-button'),status=$('voice-status'),cancel=$('cancel-recording'),input=$('question');
  let token='',phase='idle',generation=0,stream=null,recorder=null,controller=null,timer=null,tick=null;
  let available=false;
  const types=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4','audio/webm'];
  window.addEventListener('atlas:workspace-updated',e=>{token=e.detail?.state?.csrf_token||'';});
  function state(next,message){
    phase=next;button.dataset.state=next;
    button.disabled=!available||['requesting','transcribing'].includes(next);
    button.classList.toggle('listening',next==='recording');
    button.setAttribute('aria-label',next==='recording'?'Stop dictation':'Dictate a question');
    button.setAttribute('aria-pressed',String(next==='recording'));
    cancel.hidden=next==='idle';status.textContent=message;
  }
  function release(){
    clearTimeout(timer);clearInterval(tick);timer=tick=null;
    stream?.getTracks().forEach(track=>track.stop());stream=null;
  }
  function cancelVoice(message=''){
    generation++;controller?.abort();controller=null;
    if(recorder?.state==='recording')recorder.stop();recorder=null;
    release();state('idle',message);
  }
  async function transcribe(blob,id){
    if(id!==generation)return;
    release();state('transcribing','Transcribing on this computer…');
    const requestController=new AbortController();controller=requestController;
    const timeout=setTimeout(()=>requestController.abort(),120000);
    try{
      if(!blob.size)throw new Error('No audio was recorded. Please try again.');
      const response=await fetch('/api/voice/transcribe',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':blob.type,'X-Atlas-Token':token},body:blob,signal:requestController.signal});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error?.message||'Transcription failed. Try again.');
      if(id!==generation)return;
      const words=typeof result.text==='string'?result.text.trim():'';
      if(!words){state('idle','No speech detected. Try again closer to the microphone.');return;}
      const draft=input.value.trimEnd(),combined=draft+(draft?' ':'')+words;
      input.value=combined.slice(0,input.maxLength>0?input.maxLength:1000);
      input.dispatchEvent(new Event('input',{bubbles:true}));
      state('idle',combined.length>input.value.length?'Draft limit reached. Review your question before sending.':'Review your words, then send to Atlas.');
      input.focus();
    }catch(error){
      if(id===generation)state('idle',error.name==='AbortError'?'Transcription timed out. Please try again.':error.message);
    }finally{clearTimeout(timeout);if(id===generation)controller=null;}
  }
  function stop(){
    if(phase!=='recording')return;
    clearTimeout(timer);clearInterval(tick);
    state('transcribing','Finishing recording…');recorder.stop();
    release();
  }
  async function start(){
    if(phase!=='idle'||!available)return;
    const id=++generation;state('requesting','Allow microphone access to dictate.');
    try{
      if(!token){const response=await fetch('/api/research/state');if(!response.ok)throw new Error('Reload Atlas to reconnect voice.');token=(await response.json()).csrf_token;}
      if(id!==generation)return;
      const capture=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});
      if(id!==generation){capture.getTracks().forEach(track=>track.stop());return;}
      stream=capture;
      const mime=types.find(type=>MediaRecorder.isTypeSupported(type));
      if(!mime)throw new Error('This browser cannot record a supported audio format.');
      const active=new MediaRecorder(stream,{mimeType:mime,audioBitsPerSecond:64000});recorder=active;
      const chunks=[];let bytes=0;
      active.ondataavailable=e=>{
        if(id!==generation)return;
        if(e.data.size){chunks.push(e.data);bytes+=e.data.size;}
        if(bytes>4*1024*1024)cancelVoice('Recording too large. Please record a shorter question.');
      };
      active.onerror=()=>{if(id===generation)cancelVoice('Recording failed. Check your microphone and try again.');};
      active.onstop=()=>{if(id===generation){recorder=null;transcribe(new Blob(chunks,{type:mime}),id);}};
      active.start(250);state('recording','Listening · 0:00 / 1:00 · tap mic to stop');
      const began=Date.now();tick=setInterval(()=>{if(phase==='recording')status.textContent=`Listening · 0:${String(Math.min(60,Math.floor((Date.now()-began)/1000))).padStart(2,'0')} / 1:00 · tap mic to stop`;},1000);
      timer=setTimeout(stop,60000);
      stream.getAudioTracks().forEach(track=>track.addEventListener('ended',()=>{if(id===generation&&phase==='recording')stop();}));
    }catch(error){
      if(id!==generation)return;
      release();state('idle',({NotAllowedError:'Microphone access was denied. Allow it in browser permissions and try again.',NotFoundError:'No microphone found. Connect one and try again.',NotReadableError:'The microphone is busy or unavailable. Close other recording apps and retry.'})[error.name]||error.message||'Microphone could not start.');
    }
  }
  button.onclick=()=>phase==='recording'?stop():start();
  cancel.onclick=()=>cancelVoice('Dictation cancelled. Your draft is unchanged.');
  window.addEventListener('atlas:voice-cancel',()=>cancelVoice());
  window.addEventListener('pagehide',()=>cancelVoice());
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&phase==='recording')stop();});
  new MutationObserver(()=>{if($('chat-panel').hidden&&phase!=='idle')cancelVoice();}).observe($('chat-panel'),{attributes:true,attributeFilter:['hidden']});
  // Capture before both chat implementations: sending during dictation first
  // finishes the recording; the user reviews the transcript before submitting.
  function guard(event){
    if(phase==='idle')return;
    event.preventDefault();event.stopImmediatePropagation();
    if(phase==='recording')stop();
  }
  document.addEventListener('submit',e=>{if(e.target===$('chat-form'))guard(e);},true);
  document.addEventListener('keydown',e=>{if(e.target===input&&e.key==='Enter'&&!e.shiftKey)guard(e);},true);
  state('idle','Checking microphone support…');
  (async()=>{
    if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){state('idle','Voice needs a browser with microphone recording support.');return;}
    try{
      const response=await fetch('/api/voice/status');const data=await response.json();
      available=response.ok&&data.available;
      state('idle',available?'Tap to dictate':data.message||'Voice is unavailable on this server.');
      button.title=available?'Record up to 60 seconds, then review the transcript.':status.textContent;
    }catch(_){state('idle','Voice could not connect. Reload Atlas to retry.');}
  })();
})();

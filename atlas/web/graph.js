(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const svg = $('network'), camera = $('camera'), canvas = $('graph-paint');
  const ctx = canvas.getContext('2d', {alpha:true});
  // One palette serves the canvas, labels, and the tucked-away legend.
  const paletteStyle=getComputedStyle(document.body);
  const graphPaper=paletteStyle.getPropertyValue('--graph-paper').trim();
  const colors=Object.fromEntries(['disease','variant','gene','biology','research'].map(key=>[key,paletteStyle.getPropertyValue(`--graph-${key}`).trim()]));
  const glows=Object.fromEntries(Object.entries(colors).map(([key,color])=>{
    const sprite=document.createElement('canvas');sprite.width=64;sprite.height=64;
    const brush=sprite.getContext('2d'),glow=brush.createRadialGradient(32,32,1,32,32,32);
    glow.addColorStop(0,color+'66');glow.addColorStop(.32,color+'28');glow.addColorStop(1,color+'00');
    brush.fillStyle=glow;brush.fillRect(0,0,64,64);return [key,sprite];
  }));
  const NS = 'http://www.w3.org/2000/svg';
  const make = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; };
  const shape = (tag, attrs = {}) => { const el = document.createElementNS(NS, tag); for (const [k,v] of Object.entries(attrs)) el.setAttribute(k,v); return el; };
  const label = n => n.label.replace(/ \(fictional\)$/,'');
  const short = s => s.length > 31 ? s.slice(0,29) + '…' : s;
  const families = {
    Disease:'disease', Variant:'variant', Gene:'gene', Mechanism:'biology', Phenotype:'biology',
  };
  const family = n => families[n.type] || 'research';
  let bundle, nodes = [], edges = [], byId = new Map(), selected = null, hovered = null;
  let workspaceState = null, pendingWorkspaceState = null, animationLoopStarted = false;
  let view = { x:0,y:0,k:1 }, width = innerWidth, height = innerHeight, busy = false, claimRequest = 0;
  let recognition = null, listening = false;
  let lastAnswer = null, searchTerm = '', searchMatches = new Set(), searchLead = null;
  let needsProjection = true, needsPaint = true, overlayDirty = true, labelScale = 0;
  let depthOrder = [], edgeBatches = [], pixelRatio = 1, lastOverlay = 0;
  let hoverTimer = 0, hoverCandidate = null, sceneTransition = null, cameraTransition = null;
  function setHover(id) {
    clearTimeout(hoverTimer);hoverCandidate=id;
    if(hovered===id)return;
    hovered=id;highlight();
  }
  function queueHover(id) {
    if(hoverCandidate===id)return;
    clearTimeout(hoverTimer);hoverCandidate=id;
    if(hovered===id)return;
    hoverTimer=setTimeout(()=>setHover(id),id?130:100);
  }
  function nodeAt(e) {
    const rect=svg.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;
    const current=byId.get(hovered);
    // The same point stays under hover and click, even where SVG hit circles overlap.
    if(current&&!current.hidden&&Math.hypot(x-current.screenX,y-current.screenY)<Math.max(12,current.screenR+7))return current.id;
    let nearest=null,distance=e.pointerType==='touch'?20:10;
    for(const n of nodes){
      if(n.hidden)continue;
      const d=Math.hypot(x-n.screenX,y-n.screenY);
      if(d<distance){nearest=n.id;distance=d;}
    }
    return nearest;
  }
  function hoverAt(e) {
    if(e.pointerType==='touch'||gesture)return;
    queueHover(nodeAt(e));
  }
  function transitionScene() {
    const focused=!!(selected||searchTerm);
    for(const n of nodes){
      const active=(n.id===selected||n.id===hovered)&&!n.dimmed,matched=searchMatches.has(n.id);
      n.fromWeight=n.weight??1;n.toWeight=n.hidden?0:n.dimmed?.16:1;
      n.fromRing=n.ring??0;n.toRing=!n.hidden&&(active||matched)?1:0;
    }
    for(const e of edges){
      e.fromWeight=e.weight??1;e.toWeight=e.hidden||focused&&!e.linked||!$('show-connections').checked&&!e.linked?0:1;
      e.fromEmphasis=e.emphasis??0;e.toEmphasis=focused&&e.linked?1:0;
    }
    sceneTransition={start:performance.now()};
  }
  function advanceTransitions(time) {
    if(sceneTransition){
      const t=reducedMotion.matches?1:Math.min(1,(time-sceneTransition.start)/240),ease=1-Math.pow(1-t,3);
      for(const n of nodes){n.weight=n.fromWeight+(n.toWeight-n.fromWeight)*ease;n.ring=n.fromRing+(n.toRing-n.fromRing)*ease;}
      for(const e of edges){e.weight=e.fromWeight+(e.toWeight-e.fromWeight)*ease;e.emphasis=e.fromEmphasis+(e.toEmphasis-e.fromEmphasis)*ease;}
      needsPaint=true;if(t===1)sceneTransition=null;
    }
    if(cameraTransition){
      const c=cameraTransition,t=reducedMotion.matches?1:Math.min(1,(time-c.start)/320),ease=t*t*(3-2*t);
      view.x=c.x+(c.toX-c.x)*ease;view.y=c.y+(c.toY-c.y)*ease;applyCamera();
      if(t===1)cameraTransition=null;
    }
  }
  const nodeLayer = $('nodes');
  function sizeCanvas() {
    pixelRatio=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(width*pixelRatio);canvas.height=Math.round(height*pixelRatio);
  }
  sizeCanvas();
  const pointers = new Map(); let gesture = null, pinchDistance = 0;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let yaw = -.24, pitch = .12, idleAfter = 0, previousFrame = 0, lastPaint = 0;
  const pauseMotion = () => { idleAfter = performance.now() + 7000; };
  $('ambient-motion').checked = !reducedMotion.matches;
  reducedMotion.addEventListener('change', e => { $('ambient-motion').checked = !e.matches; });
  for (const event of ['pointerdown','pointermove','wheel','keydown','focusin']) document.addEventListener(event,pauseMotion,{passive:true});

  function project(n) {
    const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
    const x=n.wx*cy+n.wz*sy, z=-n.wx*sy+n.wz*cy;
    n.depth=n.wy*sp+z*cp;
    n.perspective=1100/(1100+n.depth);
    n.x=x*n.perspective; n.y=(n.wy*cp-z*sp)*n.perspective;
  }
  function moveNode(n,dx,dy) {
    const x=dx/view.k/n.perspective, y=dy/view.k/n.perspective;
    // Inverse camera rotation, keeping the point on its current screen-depth plane.
    n.wx+=x*Math.cos(yaw)+y*Math.sin(pitch)*Math.sin(yaw);
    n.wy+=y*Math.cos(pitch);
    n.wz+=x*Math.sin(yaw)-y*Math.sin(pitch)*Math.cos(yaw);
  }
  function animate(time) {
    const elapsed=Math.min(50,time-(previousFrame||time));previousFrame=time;
    advanceTransitions(time);
    const editing=['INPUT','TEXTAREA'].includes(document.activeElement?.tagName);
    const idle=!document.hidden&&time>idleAfter&&$('ambient-motion').checked&&!gesture&&!cameraTransition&&!sceneTransition&&!selected&&!hovered&&!searchTerm&&!editing&&$('chat-panel').hidden&&$('graph-options').hidden&&!document.querySelector('dialog[open]');
    if(idle){yaw+=elapsed*.000023;needsProjection=true;}
    if(!document.hidden&&(needsPaint||needsProjection)&&(!idle||time-lastPaint>32)){
      if(needsProjection){
        const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
        nodes.forEach(n=>{
          const x=n.wx*cy+n.wz*sy,z=-n.wx*sy+n.wz*cy;
          n.depth=n.wy*sp+z*cp;n.perspective=1100/(1100+n.depth);
          n.x=x*n.perspective;n.y=(n.wy*cp-z*sp)*n.perspective;
        });
        depthOrder=[...nodes].sort((a,b)=>b.depth-a.depth);
        overlayDirty=true;needsProjection=false;
      }
      drawGraph();
      // During an orbit the canvas handles every frame; hit areas catch up on release.
      if(!gesture?.moved&&overlayDirty&&(!idle||time-lastOverlay>120)){syncOverlay();lastOverlay=time;}
      needsPaint=false;lastPaint=time;
    }
    requestAnimationFrame(animate);
  }
  function drawGraph() {
    ctx.setTransform(pixelRatio,0,0,pixelRatio,0,0);ctx.clearRect(0,0,width,height);
    const sqrtZoom=Math.sqrt(view.k);
    nodes.forEach(n=>{n.screenX=view.x+n.x*view.k;n.screenY=view.y+n.y*view.k;n.screenR=Math.max(1.5,n.radius*n.perspective*sqrtZoom);});
    // Quantized opacity keeps fading edges batched instead of stroking each one.
    for(const batch of edgeBatches){
      const buckets=new Map();
      for(const e of batch.edges){
        const front=e.a.depth+e.b.depth<0,base=front?.23:.115;
        const alpha=Math.round((e.weight??1)*(base+(.68-base)*(e.emphasis??0))*48)/48;
        if(alpha<=0)continue;
        const lineWidth=(front?.8:.65)+(1.2-(front?.8:.65))*(e.emphasis??0);
        const key=`${alpha}:${Math.round(lineWidth*10)}`;
        if(!buckets.has(key))buckets.set(key,{alpha,lineWidth,edges:[]});
        buckets.get(key).edges.push(e);
      }
      ctx.strokeStyle=batch.color;
      ctx.setLineDash(batch.kind==='inferred'?[4,5]:batch.kind==='contested'?[2,5]:[]);
      for(const bucket of buckets.values()){
        ctx.beginPath();
        for(const e of bucket.edges){ctx.moveTo(e.a.screenX,e.a.screenY);ctx.lineTo(e.b.screenX,e.b.screenY);}
        ctx.globalAlpha=bucket.alpha;ctx.lineWidth=bucket.lineWidth;ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    // Cached colour sprites keep the soft halos cheap while rotating or dragging.
    for(const n of depthOrder){
      if(n.weight<.01||(!n.ring&&n.degree<6))continue;
      const r=n.screenR,extent=r*(2.8+n.ring);
      ctx.globalAlpha=(.3+n.ring*.35)*n.weight;
      ctx.drawImage(glows[family(n)],n.screenX-extent,n.screenY-extent,extent*2,extent*2);
    }
    for(const n of depthOrder){
      if(n.weight<.01)continue;
      const r=n.screenR,x=n.screenX,y=n.screenY;
      const color=colors[family(n)],depthAlpha=Math.max(.66,Math.min(1,.9-n.depth/1000));
      if(n.ring>.01){
        ctx.globalAlpha=n.ring;ctx.strokeStyle=graphPaper;ctx.lineWidth=3;
        ctx.beginPath();ctx.arc(x,y,r+3,0,Math.PI*2);ctx.stroke();
        ctx.strokeStyle=color;ctx.lineWidth=1.5;
        ctx.beginPath();ctx.arc(x,y,r+4,0,Math.PI*2);ctx.stroke();
      }
      ctx.globalAlpha=n.weight*(depthAlpha+(1-depthAlpha)*n.ring);
      ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
      // A fine paper rim separates overlapping foreground points.
      if(r>2.3){ctx.strokeStyle=graphPaper;ctx.lineWidth=.65;ctx.stroke();}
    }
    ctx.globalAlpha=1;
  }
  function syncOverlay() {
    camera.setAttribute('transform',`translate(${view.x} ${view.y}) scale(${view.k})`);
    const scaled=labelScale!==view.k;labelScale=view.k;
    nodes.forEach(n=>{
      n.el.setAttribute('transform',`translate(${n.x.toFixed(2)} ${n.y.toFixed(2)})`);
      n.drawnRadius=n.screenR/view.k;
      if(scaled){n.hit.setAttribute('r',9/view.k);n.text.setAttribute('font-size',12/view.k);}
    });
    // Only highlighted edges need a pointer target. The faint overview lives on canvas.
    edges.forEach(e=>{if(e.linked&&!e.hidden)e.hit.setAttribute('d',`M${e.a.x} ${e.a.y}L${e.b.x} ${e.b.y}`);});
    placeLabels();overlayDirty=false;
  }

  function layout() {
    // Seed real 3D coordinates by neighborhood, then relax recorded relationships.
    // Coordinates describe the graph layout, never biomedical similarity.
    // Stable irregular seeds avoid repeating radial rosettes on every visit.
    const randomFor=id=>{
      let seed=2166136261;
      for(const c of String(id)){seed^=c.charCodeAt(0);seed=Math.imul(seed,16777619);}
      return ()=>{seed+=0x6D2B79F5;let t=seed;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return ((t^t>>>14)>>>0)/4294967296;};
    };
    const normal=random=>Math.sqrt(-2*Math.log(Math.max(.0001,random())))*Math.cos(2*Math.PI*random());
    const groups=[...new Set(nodes.map(n=>n.properties?.demo_community ?? 'original'))];
    const centers=new Map(),extent=Math.pow(nodes.length/471,.25);
    for(const id of groups){
      const random=randomFor(`community:${id}`);let c;
      for(let attempt=0;attempt<40;attempt++){
        c={x:normal(random)*290*extent,y:normal(random)*150*extent,z:normal(random)*85};
        if([...centers.values()].every(o=>Math.hypot(c.x-o.x,c.y-o.y,c.z-o.z)>115*extent))break;
      }
      c.angle=random()*Math.PI*2;c.stretch=.55+random()*1.2;c.spread=28+random()*48;
      c.scale=(.65+random()*1.15)*extent;
      centers.set(id,c);
    }
    nodes.forEach(n=>{n.degree=0;});
    edges.forEach(e=>{e.a.degree++;e.b.degree++;});
    nodes.forEach(n=>{
      const c=centers.get(n.properties?.demo_community ?? 'original'),random=randomFor(n.id);
      n.communityCenter=c;
      const spread=c.spread/(1+Math.sqrt(n.degree)*.12);
      const x=normal(random)*spread*c.stretch,y=normal(random)*spread/c.stretch;
      n.wx=c.x+x*Math.cos(c.angle)-y*Math.sin(c.angle);
      n.wy=c.y+x*Math.sin(c.angle)+y*Math.cos(c.angle);
      n.wz=c.z+normal(random)*spread*.65;
      n.vx=0;n.vy=0;n.vz=0;
    });
    edges.forEach(e=>{
      const random=randomFor(e.claim.id);
      const local=e.a.communityCenter===e.b.communityCenter;
      e.restLength=(24+random()*65)*(local?e.a.communityCenter.scale:1.5);
      e.spring=(.006+random()*.008)*(local?1:.3);
    });
    for(let step=0;step<160;step++){
      // Local spatial buckets avoid an all-pairs pass on the larger atlas.
      const cells=new Map(),cellSize=120;
      nodes.forEach((n,i)=>{
        n.cellX=Math.floor(n.wx/cellSize);n.cellY=Math.floor(n.wy/cellSize);n.cellZ=Math.floor(n.wz/cellSize);n.layoutIndex=i;
        const key=`${n.cellX},${n.cellY},${n.cellZ}`;
        if(!cells.has(key))cells.set(key,[]);cells.get(key).push(n);
      });
      for(const a of nodes)for(let cx=-1;cx<=1;cx++)for(let cy=-1;cy<=1;cy++)for(let cz=-1;cz<=1;cz++){
        const nearby=cells.get(`${a.cellX+cx},${a.cellY+cy},${a.cellZ+cz}`);
        if(!nearby)continue;
        for(const b of nearby){
          if(b.layoutIndex<=a.layoutIndex)continue;
          const dx=b.wx-a.wx,dy=b.wy-a.wy,dz=b.wz-a.wz,d2=dx*dx+dy*dy+dz*dz;
          if(d2>cellSize*cellSize)continue;
          const d=Math.max(1,Math.sqrt(d2)),f=Math.min(7,520/(d*d))*(1-d2/(cellSize*cellSize));
          a.vx-=dx/d*f;a.vy-=dy/d*f;a.vz-=dz/d*f;
          b.vx+=dx/d*f;b.vy+=dy/d*f;b.vz+=dz/d*f;
        }
      }
      edges.forEach(e=>{
        const dx=e.b.wx-e.a.wx,dy=e.b.wy-e.a.wy,dz=e.b.wz-e.a.wz,d=Math.max(1,Math.hypot(dx,dy,dz));
        const f=(d-e.restLength)*e.spring;
        e.a.vx+=dx/d*f;e.a.vy+=dy/d*f;e.a.vz+=dz/d*f;
        e.b.vx-=dx/d*f;e.b.vy-=dy/d*f;e.b.vz-=dz/d*f;
      });
      const cooling=1-step/205;
      nodes.forEach(n=>{
        // A gentle neighborhood pull preserves loose islands and unequal gaps.
        const c=n.communityCenter;
        n.vx=(n.vx+(c.x-n.wx)*.002)*.68;
        n.vy=(n.vy+(c.y-n.wy)*.002)*.68;
        n.vz=(n.vz+(c.z-n.wz)*.002)*.68;
        n.wx+=n.vx*cooling;n.wy+=n.vy*cooling;n.wz+=n.vz*cooling;
      });
    }
    // Give the overview a broad, slightly tilted silhouette instead of a ball.
    nodes.forEach(n=>{
      const x=n.wx,y=n.wy;
      n.wx=x*1.25+y*.22;n.wy=y*.9-x*.08;
      project(n);
    });
  }
  function paintPositions() { needsProjection=true;needsPaint=true; }
  function applyCamera() { overlayDirty=true;needsPaint=true; }
  function placeLabels() {
    const occupied=[];
    const priority=n=>n.id===selected?0:n.type==='Disease'?1:n.type==='Mechanism'?2:3;
    nodes.filter(n=>svg.classList.contains('all-labels')||n.id===selected||n.id===hovered||n.id===searchLead).sort((a,b)=>priority(a)-priority(b)).forEach(n=>{
      if(!n.text||n.el.getAttribute('display')==='none')return;
      const visible=svg.classList.contains('all-labels')||n.id===selected||n.id===hovered||n.id===searchLead;
      if(!visible)return;
      const k=view.k,r=n.drawnRadius||n.radius,pad=5/k;
      const placements=[[0,r+17/k,'middle'],[0,-r-10/k,'middle'],[r+10/k,4/k,'start'],[-r-10/k,4/k,'end'],[0,r+32/k,'middle']];
      let box;
      for(const [x,y,anchor] of placements){
        n.text.setAttribute('x',x);n.text.setAttribute('y',y);n.text.setAttribute('text-anchor',anchor);
        const b=n.text.getBBox();box={x:n.x+b.x-pad,y:n.y+b.y-pad,w:b.width+pad*2,h:b.height+pad*2};
        if(!occupied.some(o=>box.x<o.x+o.w&&box.x+box.w>o.x&&box.y<o.y+o.h&&box.y+box.h>o.y))break;
      }
      occupied.push(box);
    });
  }
  function fit() {
    cameraTransition=null;
    if (!nodes.length) return;
    const minX=Math.min(...nodes.map(n=>n.x)),maxX=Math.max(...nodes.map(n=>n.x));
    const minY=Math.min(...nodes.map(n=>n.y)),maxY=Math.max(...nodes.map(n=>n.y));
    const padX=width<650?24:48, top=90, bottom=75;
    view.k=Math.max(.15,Math.min(3,(width-padX*2)/Math.max(100,maxX-minX),(height-top-bottom)/Math.max(100,maxY-minY)));
    view.x=width/2-(minX+maxX)/2*view.k;
    view.y=top+(height-top-bottom)/2-(minY+maxY)/2*view.k;
    applyCamera();
  }
  function zoom(factor,x=width/2,y=height/2) {
    cameraTransition=null;
    const next=Math.max(.12,Math.min(4,view.k*factor)), ratio=next/view.k;
    view.x=x-(x-view.x)*ratio; view.y=y-(y-view.y)*ratio; view.k=next; applyCamera();
  }
  function highlight() {
    const searching=!!searchTerm;
    // Hover reveals a label and ring; only selection/search changes the whole scene.
    const id=selected, neighbors=new Set(id?[id]:[]);
    edges.forEach(e=>{if(e.a.id===id)neighbors.add(e.b.id);if(e.b.id===id)neighbors.add(e.a.id);});
    svg.classList.toggle('has-focus',!!id);svg.classList.toggle('is-searching',searching);
    nodes.forEach(n=>{
      n.dimmed=searching?!searchMatches.has(n.id):!!id&&!neighbors.has(n.id);
      n.hidden=!searching&&$('local-view').checked&&selected&&!neighbors.has(n.id);
      n.el.classList.toggle('selected',n.id===selected);
      n.el.classList.toggle('hovered',n.id===hovered);
      n.el.classList.toggle('neighbor',neighbors.has(n.id));
      n.el.classList.toggle('dimmed',n.dimmed);
      n.el.classList.toggle('search-match',searchMatches.has(n.id));
      n.el.classList.toggle('search-lead',n.id===searchLead);
      n.el.setAttribute('aria-pressed',String(n.id===selected));
      n.el.setAttribute('display',n.hidden?'none':'');
    });
    edges.forEach(e=>{
      e.linked=searching?searchMatches.has(e.a.id)&&searchMatches.has(e.b.id):e.a.id===id||e.b.id===id;
      e.hidden=!searching&&$('local-view').checked&&selected&&!e.linked;
      e.el.classList.toggle('highlight',e.linked);e.el.classList.toggle('dimmed',!!id&&!e.linked);
      e.el.setAttribute('tabindex',e.linked?'0':'-1');e.el.setAttribute('display',e.hidden?'none':'');
    });
    transitionScene();overlayDirty=true;needsPaint=true;
  }
  function select(id,center=false) {
    clearTimeout(hoverTimer);hoverCandidate=null;
    cameraTransition=null;
    selected=id; hovered=null; lastAnswer=null;searchTerm='';searchMatches.clear();searchLead=null;$('node-search').value='';
    const node=byId.get(id);
    $('selection').hidden=!node;
    if (node) {
      $('selection-name').textContent=label(node); $('selection-type').textContent=node.type;
      if (center) { cameraTransition={start:performance.now(),x:view.x,y:view.y,toX:width/2-node.x*view.k,toY:height/2-node.y*view.k}; }
    }
    highlight(); hideResults();
    window.dispatchEvent(new CustomEvent('atlas:node-select',{detail:{node_id:id,node:node?{id:node.id,label:label(node),type:node.type}:null}}));
  }
  function render() {
    $('links').replaceChildren();nodeLayer.replaceChildren();
    const contestedClaims=new Set(bundle.evidence.filter(r=>r.stance==='contradicts').map(r=>r.claim_id));
    edges=bundle.claims.filter(c=>byId.has(c.subject)&&byId.has(c.object)).map(c=>({claim:c,a:byId.get(c.subject),b:byId.get(c.object)}));
    layout();
    edges.forEach(e=>{
      const contested=e.claim.context?.negated===true||contestedClaims.has(e.claim.id);
      e.kind=contested?'contested':e.claim.assertion_type==='inferred'?'inferred':'normal';
      e.el=shape('g',{class:'edge-group',role:'button','aria-label':`${label(e.a)} ${e.claim.predicate.toLowerCase().replaceAll('_',' ')} ${label(e.b)}. Inspect evidence.`,tabindex:-1,'data-claim':e.claim.id});
      e.hit=shape('path',{class:'edge-target'});
      const title=shape('title');title.textContent=`${label(e.a)} → ${label(e.b)} · ${e.claim.predicate.replaceAll('_',' ').toLowerCase()}`;
      e.el.append(title,e.hit);$('links').append(e.el);
    });
    nodes.forEach(n=>{
      n.radius=2+Math.min(3.3,Math.sqrt(n.degree)*.66);
      n.el=shape('g',{class:'net-node',role:'button',tabindex:0,'data-node':n.id,'data-kind':n.type,'data-family':family(n),'aria-label':`${n.label}, ${n.type}`,'aria-pressed':'false'});
      const hit=shape('circle',{r:Math.max(18,n.radius+6),fill:'transparent'});
      n.hit=hit;
      n.text=shape('text',{class:'node-label','text-anchor':'middle'});n.text.textContent=short(label(n));
      const title=shape('title');title.textContent=`${n.label} · ${n.type}`;
      n.el.append(title,hit,n.text);nodeLayer.append(n.el);
      n.el.addEventListener('focus',()=>setHover(n.id));
      n.el.addEventListener('blur',()=>setHover(null));
    });
    const batches=new Map();
    edges.forEach(e=>{
      const key=`${e.kind}:${family(e.a)}`;
      if(!batches.has(key))batches.set(key,{kind:e.kind,color:e.kind==='contested'?'#b55b3b':colors[family(e.a)],edges:[]});
      batches.get(key).edges.push(e);
    });
    edgeBatches=[...batches.values()];
    svg.classList.toggle('show-connections',$('show-connections').checked);svg.classList.toggle('all-labels',$('all-labels').checked);
    paintPositions();fit();highlight();
    if(!animationLoopStarted){animationLoopStarted=true;requestAnimationFrame(animate);}
    window.dispatchEvent(new CustomEvent('atlas:graph-updated',{detail:{nodes:nodes.length,claims:edges.length}}));
  }
  function setWorkspaceState(data) {
    if(!data||!Array.isArray(data.nodes)||!Array.isArray(data.claims))return;
    workspaceState=data;
    const previous=new Map(nodes.map(node=>[node.id,node]));
    const nextNodes=data.nodes.map(node=>({...node}));
    const nodeIds=new Set(nextNodes.map(node=>node.id));
    const activeClaims=data.claims.filter(claim=>claim.review_status!=='rejected'&&nodeIds.has(claim.subject)&&nodeIds.has(claim.object));
    const previousSources=new Map((bundle?.sources||[]).map(source=>[source.id,source]));
    for(const source of data.sources||[])previousSources.set(source.id||source.source_id,source);
    for(const doc of data.documents||[])if(!previousSources.has(doc.source_id))previousSources.set(doc.source_id,{id:doc.source_id,title:doc.title,url:doc.url,version:doc.version,license:doc.license});
    bundle={...bundle,dataset:data.dataset||bundle.dataset,nodes:nextNodes,claims:activeClaims,
      evidence:activeClaims.flatMap(claim=>(claim.evidence||[]).map(evidence=>({...evidence,claim_id:claim.id}))),
      sources:[...previousSources.values()]};
    nodes=nextNodes;byId=new Map(nodes.map(node=>[node.id,node]));
    nodes.forEach(node=>{const old=previous.get(node.id);if(old){for(const key of ['wx','wy','wz'])if(Number.isFinite(old[key]))node[key]=old[key];}});
    if(selected&&!byId.has(selected))selected=null;
    searchMatches.clear();searchLead=null;searchTerm='';$('node-search').value='';
    const previousView={...view};render();view=previousView;applyCamera();paintPositions();highlight();
    if(selected)select(selected);
  }
  window.addEventListener('atlas:workspace-updated',event=>{
    const incoming=event.detail?.state;
    if(!incoming)return;
    if(!bundle){pendingWorkspaceState=incoming;return;}
    setWorkspaceState(incoming);
  });
  window.addEventListener('atlas:select-node',event=>{
    const id=event.detail?.node_id;
    if(!id||!byId.has(id))return;
    select(id,true);byId.get(id)?.el.focus({preventScroll:true});
  });
  window.addEventListener('atlas:open-claim',event=>{const id=event.detail?.claim_id;if(id)openClaim(id);});
  function hideResults() { $('node-results').hidden=true;$('node-search').setAttribute('aria-expanded','false'); }
  function searchNodes() {
    searchTerm=$('node-search').value.toLowerCase().trim();
    const results=$('node-results');results.replaceChildren();
    const matches=searchTerm?nodes.filter(n=>[label(n),n.id,...(n.aliases||[])].some(t=>t.toLowerCase().includes(searchTerm))):[];
    const exact=n=>[label(n),n.id,...(n.aliases||[])].some(t=>t.toLowerCase()===searchTerm);
    matches.sort((a,b)=>Number(exact(b))-Number(exact(a)));
    searchMatches=new Set(matches.map(n=>n.id));searchLead=matches[0]?.id||null;highlight();
    if(!searchTerm){hideResults();return;}
    matches.slice(0,12).forEach(n=>{
      const b=make('button','',label(n));b.type='button';b.append(make('small','',n.type));
      b.addEventListener('click',()=>{select(n.id,true);n.el.focus();});
      b.addEventListener('focus',()=>{searchLead=n.id;highlight();});results.append(b);
    });
    if(!matches.length)results.append(make('p','','No matching nodes.'));
    results.hidden=false;$('node-search').setAttribute('aria-expanded','true');
  }
  $('node-search').addEventListener('input',searchNodes);
  $('node-search').addEventListener('keydown',e=>{
    if(e.key==='Escape'){$('node-search').value='';searchNodes();}
    if(e.key==='ArrowDown'){e.preventDefault();$('node-results').querySelector('button')?.focus();}
    if(e.key==='Enter'&&searchLead){e.preventDefault();const id=searchLead;select(id,true);byId.get(id)?.el.focus();}
  });
  $('node-results').addEventListener('keydown',e=>{const items=[...$('node-results').querySelectorAll('button')],i=items.indexOf(document.activeElement);if(e.key==='ArrowDown'){e.preventDefault();items[(i+1)%items.length]?.focus();}if(e.key==='ArrowUp'){e.preventDefault();items[(i-1+items.length)%items.length]?.focus();}if(e.key==='Escape'){$('node-search').focus();hideResults();}});

  svg.addEventListener('pointerdown',e=>{
    if(e.button!==0)return;
    const id=nodeAt(e);
    e.preventDefault();svg.classList.add('pointer-focus');svg.focus({preventScroll:true});
    cameraTransition=null;setHover(null);
    pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});svg.setPointerCapture(e.pointerId);
    if(pointers.size===2){const p=[...pointers.values()];pinchDistance=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);if(gesture)gesture.moved=true;return;}
    svg.classList.add('interacting');
    gesture={id,claim:e.target.closest('[data-claim]')?.dataset.claim,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey,moved:false};
  });
  svg.addEventListener('pointermove',e=>{
    if(!pointers.has(e.pointerId)||!gesture){hoverAt(e);return;}
    pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pointers.size===2){const p=[...pointers.values()],d=Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y);if(pinchDistance)zoom(d/pinchDistance,(p[0].x+p[1].x)/2,(p[0].y+p[1].y)/2);pinchDistance=d;return;}
    const dx=e.clientX-gesture.x,dy=e.clientY-gesture.y;
    if(Math.hypot(e.clientX-gesture.startX,e.clientY-gesture.startY)>(e.pointerType==='touch'?9:6))gesture.moved=true;
    if(gesture.moved){const node=byId.get(gesture.id);if(node){moveNode(node,dx,dy);paintPositions();}else if(gesture.pan){view.x+=dx;view.y+=dy;applyCamera();}else{yaw+=dx*.005;pitch=Math.max(-1.2,Math.min(1.2,pitch+dy*.005));paintPositions();}}
    gesture.x=e.clientX;gesture.y=e.clientY;
  });
  svg.addEventListener('pointerleave',()=>queueHover(null));
  function release(e,cancel=false){
    pointers.delete(e.pointerId);
    if(!pointers.size&&gesture){const g=gesture;gesture=null;svg.classList.remove('interacting');overlayDirty=true;needsPaint=true;pinchDistance=0;if(!g.moved&&!cancel){if(g.id)select(g.id);else if(g.claim)openClaim(g.claim);else select(null);}highlight();}
    else if(gesture){gesture.moved=true;const p=[...pointers.values()][0];gesture.x=p.x;gesture.y=p.y;}
  }
  svg.addEventListener('pointerup',e=>release(e));svg.addEventListener('pointercancel',e=>release(e,true));
  svg.addEventListener('click',e=>{
    // Assistive-technology activation can issue a click without pointer events.
    if(e.detail!==0)return;
    const node=e.target.closest('[data-node]')?.dataset.node,claim=e.target.closest('[data-claim]')?.dataset.claim;
    if(node)select(node);else if(claim)openClaim(claim);
  });
  svg.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.0012),e.clientX,e.clientY);},{passive:false});
  svg.addEventListener('keydown',e=>{
    svg.classList.remove('pointer-focus');
    const node=e.target.closest('[data-node]')?.dataset.node;
    const claim=e.target.closest('[data-claim]')?.dataset.claim;
    if(claim&&['Enter',' '].includes(e.key)){e.preventDefault();openClaim(claim);return;}
    if(node&&['Enter',' '].includes(e.key)){e.preventDefault();select(node);return;}
    if(['+','=','-','0','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();cameraTransition=null;}
    if(['+','='].includes(e.key))zoom(1.2);if(e.key==='-')zoom(1/1.2);if(e.key==='0')fit();
    const step=e.shiftKey?.2:.08;if(e.key==='ArrowLeft')yaw-=step;if(e.key==='ArrowRight')yaw+=step;if(e.key==='ArrowUp')pitch-=step;if(e.key==='ArrowDown')pitch+=step;pitch=Math.max(-1.2,Math.min(1.2,pitch));paintPositions();
    if(e.key==='Escape')select(null);
  });
  $('clear-selection').onclick=()=>select(null);
  $('all-labels').onchange=e=>{svg.classList.toggle('all-labels',e.target.checked);applyCamera();};
  $('local-view').onchange=highlight;
  $('show-connections').onchange=e=>{svg.classList.toggle('show-connections',e.target.checked);highlight();};
  $('options-toggle').onclick=()=>{const open=$('graph-options').hidden;$('graph-options').hidden=!open;$('options-toggle').setAttribute('aria-expanded',String(open));};
  $('help-button').onclick=()=>{$('graph-options').hidden=true;$('options-toggle').setAttribute('aria-expanded','false');$('graph-help').showModal();};
  $('help-close').onclick=()=>$('graph-help').close();
  window.addEventListener('resize',()=>{width=innerWidth;height=innerHeight;sizeCanvas();fit();});

  async function openClaim(id) {
    const workspaceClaim=workspaceState?.claims?.find(claim=>claim.id===id);
    if(workspaceClaim){openWorkspaceClaim(workspaceClaim);return;}
    const request=++claimRequest;const dialog=$('record-dialog');
    $('record-kind').textContent='Recorded assertion';$('record-title').textContent='Evidence';$('record-content').replaceChildren(make('p','','Loading the source records…'));if(!dialog.open)dialog.showModal();
    try {
      const response=await fetch(`/api/claim?id=${encodeURIComponent(id)}`);if(!response.ok)throw new Error('This evidence could not be loaded.');const data=await response.json();if(request!==claimRequest)return;
      const c=data.claim,a=byId.get(c.subject),b=byId.get(c.object);
      $('record-title').textContent=`${a?label(a):c.subject} → ${b?label(b):c.object}`;
      $('record-kind').textContent=`${c.predicate.replaceAll('_',' ').toLowerCase()} · ${c.assertion_type}`;
      const content=$('record-content');content.replaceChildren();
      const context=Object.entries(c.context||{}).map(([k,v])=>`${k.replaceAll('_',' ')}: ${String(v).replaceAll('_',' ')}`).join(' · ');
      if(context)content.append(make('p','',context));
      const rows=[...(data.support||[]),...(data.contradictions||[])];
      if(!rows.length)content.append(make('p','','No supporting excerpt is attached to this assertion.'));
      rows.forEach(r=>{
        const source=data.sources.find(s=>s.id===r.source_id),article=make('article',r.stance==='contradicts'?'counter':'');
        article.append(make('strong','',r.stance==='contradicts'?'Counter-evidence':'Supporting record'),make('blockquote','',r.excerpt),make('p','',source?.title||r.source_id),make('small','',`${r.locator} · ${r.review_status.replaceAll('_',' ')}`));
        if(source){article.append(make('p','',`Retrieved ${source.retrieved_at || 'date not recorded'} · ${source.license || 'reuse terms not recorded'}`));try{const url=new URL(source.url);if(['http:','https:'].includes(url.protocol)){const link=make('a','','Open source ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';article.append(link);}}catch(_){}}
        content.append(article);
      });
      content.append(make('p','','Recorded evidence is a research starting point, not a clinical conclusion.'));
    }catch(error){if(request===claimRequest)$('record-content').replaceChildren(make('p','',error.message));}
  }
  function openWorkspaceClaim(claim) {
    claimRequest++;const dialog=$('record-dialog');$('record-kind').textContent=`${String(claim.predicate||'assertion').replaceAll('_',' ').toLowerCase()} · ${claim.assertion_type||'source claim'}`;
    $('record-title').textContent=`${byId.get(claim.subject)?label(byId.get(claim.subject)):claim.subject} → ${byId.get(claim.object)?label(byId.get(claim.object)):claim.object}`;
    const content=$('record-content');content.replaceChildren();
    const context=Object.entries(claim.context||{}).map(([key,value])=>`${key.replaceAll('_',' ')}: ${String(value).replaceAll('_',' ')}`).join(' · ');
    if(context)content.append(make('p','',context));
    const sources=workspaceState.sources||[],documents=workspaceState.documents||[];
    const rows=claim.evidence||[];
    if(!rows.length)content.append(make('p','','No source-attached evidence is available for this claim.'));
    rows.forEach(row=>{
      const source=sources.find(item=>(item.id||item.source_id)===row.source_id)||documents.find(item=>item.source_id===row.source_id),article=make('article',row.stance==='contradicts'?'counter':'');
      article.append(make('strong','',row.stance==='contradicts'?'Counter-evidence':'Source excerpt'),make('blockquote','',row.excerpt||'No exact excerpt supplied.'),make('p','',source?.title||row.source_id),make('small','',`${row.locator||'Locator unavailable'} · ${String(row.review_status||claim.review_status||'unreviewed').replaceAll('_',' ')}`));
      if(source){article.append(make('p','',`${source.retrieved_at?`Retrieved ${source.retrieved_at}`:''}${source.license?`${source.retrieved_at?' · ':''}${source.license}`:''}`));try{const url=new URL(source.url);if(['http:','https:'].includes(url.protocol)){const link=make('a','','Open source ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';article.append(link);}}catch(_){}}
      content.append(article);
    });
    content.append(make('p','','Recorded evidence is a research starting point, not a clinical conclusion.'));
    if(!dialog.open)dialog.showModal();
  }
  $('record-close').onclick=()=>$('record-dialog').close();

  function openChat(){ $('workspace-panel').hidden=true;$('workspace-toggle').setAttribute('aria-expanded','false');$('chat-panel').hidden=false;$('chat-toggle').setAttribute('aria-expanded','true');$('question').focus(); }
  function closeChat(){ $('chat-panel').hidden=true;$('chat-toggle').setAttribute('aria-expanded','false');$('voice-consent').hidden=true;recognition?.abort();$('chat-toggle').focus(); }
  $('chat-toggle').onclick=()=>$('chat-panel').hidden?openChat():closeChat();$('chat-close').onclick=closeChat;
  $('ask-selected').onclick=()=>{openChat();$('question').value=selected?`What is connected to ${label(byId.get(selected))}?`:'';};
  $('chat-panel').addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();closeChat();}});
  $('chat-form').onsubmit=e=>{e.preventDefault();ask();};
  $('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}};
  async function ask() {
    const question=$('question').value.trim();if(!question||busy)return;
    busy=true;$('send-question').disabled=true;recognition?.abort();
    const box=$('chat-messages');
    box.append(make('div','chat-message user',question));$('question').value='';
    const reply=make('div','chat-message answer');reply.append(make('p','','Looking through the graph…'));box.append(reply);box.scrollTop=box.scrollHeight;
    try{
      const params=new URLSearchParams({q:question});if(selected)params.set('node',selected);
      if(lastAnswer?.claim_ids?.length&&/\b(this|that|these|those)\b/i.test(question)&&/\b(evidence|sources?|support|proof|papers?)\b/i.test(question))lastAnswer.claim_ids.slice(0,100).forEach(id=>params.append('claim',id));
      const response=await fetch(`/api/ask?${params}`),data=await response.json();if(!response.ok)throw new Error(data.error?.message||'The graph could not answer just now.');
      lastAnswer=data;
      reply.replaceChildren(make('div','answer-label',data.synthetic?'Atlas · fictional demo records':'Atlas · graph records'),make('p','',data.answer));
      if(data.claim_ids?.length){const refs=make('div','chat-citations');data.claim_ids.forEach((id,i)=>{const claim=bundle.claims.find(c=>c.id===id);if(!claim)return;const b=make('button','',`[${i+1}] ${claim.predicate.replaceAll('_',' ').toLowerCase()}`);b.type='button';b.title=`${byId.get(claim.subject)?.label} → ${byId.get(claim.object)?.label}`;b.onclick=()=>openClaim(id);refs.append(b);});reply.append(refs);}
    }catch(error){reply.replaceChildren(make('p','',error.message||'The answer could not be loaded. Try again.'));}
    finally{busy=false;$('send-question').disabled=false;box.scrollTop=box.scrollHeight;}
  }

  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  $('voice-button').onclick=()=>{
    if(listening){recognition?.stop();return;}
    if(!Recognition){$('voice-status').textContent='Voice unavailable in this browser. Please type.';return;}
    $('voice-consent').hidden=false;
  };
  $('cancel-voice').onclick=()=>{$('voice-consent').hidden=true;$('question').focus();};
  $('start-voice').onclick=()=>{
    $('voice-consent').hidden=true;
    recognition=new Recognition();recognition.lang='en-GB';recognition.continuous=false;recognition.interimResults=true;
    const draft=$('question').value;
    recognition.onstart=()=>{listening=true;$('voice-button').classList.add('listening');$('voice-button').setAttribute('aria-label','Stop dictation');$('voice-status').textContent='Listening… tap to stop';};
    recognition.onresult=e=>{const transcript=Array.from(e.results).map(r=>r[0].transcript).join(' ');$('question').value=(draft+(draft?' ':'')+transcript).slice(0,1000);};
    recognition.onerror=e=>{$('voice-status').textContent=e.error==='not-allowed'?'Microphone access was not granted.':'Voice could not connect. Please type your question.';};
    recognition.onend=()=>{listening=false;$('voice-button').classList.remove('listening');$('voice-button').setAttribute('aria-label','Dictate a question');if($('voice-status').textContent.startsWith('Listening'))$('voice-status').textContent='Review your words, then send.';};
    try{recognition.start();}catch(_){$('voice-status').textContent='Voice unavailable. Please type your question.';}
  };
  window.addEventListener('pagehide',()=>recognition?.abort());
  document.addEventListener('click',e=>{if(!e.target.closest('.graph-search'))hideResults();if(!e.target.closest('#graph-options')&&!e.target.closest('#options-toggle')){$('graph-options').hidden=true;$('options-toggle').setAttribute('aria-expanded','false');}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('graph-options').hidden=true;$('options-toggle').setAttribute('aria-expanded','false');hideResults();}});

  async function init() {
    try{
      const response=await fetch('/api/graph');if(!response.ok)throw new Error('The graph could not be loaded. Refresh to try again.');bundle=await response.json();
      nodes=bundle.nodes.map(n=>({...n}));byId=new Map(nodes.map(n=>[n.id,n]));
      if(pendingWorkspaceState){const pending=pendingWorkspaceState;pendingWorkspaceState=null;setWorkspaceState(pending);}else render();document.fonts.ready.then(placeLabels);
      $('graph-status').hidden=!!nodes.length;if(!nodes.length)$('graph-status').textContent='No entities have been added yet.';
    }catch(error){$('graph-status').textContent=error.message;$('chat-toggle').disabled=true;$('node-search').disabled=true;}
    finally{window.dispatchEvent(new Event('atlas:ready'));}
  }
  init();
})();

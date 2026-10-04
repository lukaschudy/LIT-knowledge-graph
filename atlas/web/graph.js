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
    Disease:'disease', Variant:'variant', Gene:'gene', Protein:'gene', Mechanism:'biology', Phenotype:'biology', Pathway:'biology', OntologyTerm:'biology',
    SearchQuery:'research', DataRecord:'research', Dataset:'research',
  };
  const family = n => families[n.type] || 'research';
  let bundle, nodes = [], edges = [], byId = new Map(), selected = null, hovered = null;
  let workspaceState = null, pendingWorkspaceState = null, animationLoopStarted = false, workspaceGraphSignature = '';
  let harvestBase = null, resolvedBase = null, dataMode = 'harvest', harvestCoverage = null, harvestRequest = 0, searchRequest = 0, searchTimer = 0;
  let harvestLimit = 10000, resolvedLimit = 120, harvestOffset = 0, harvestLoading = false, harvestError = '', resolvedError = '', nextHarvestOffset = null, resolvedNextOffset = null, scopeGeneration=0;
  let expandedFocusId = null, expandedFocusNextOffset = 0, expandedFocusDone = false;
  let harvestDatasets = [], selectedDatasetId = '', recordPage = 0, recordRequest = 0;
  let view = { x:0,y:0,k:1 }, width = innerWidth, height = innerHeight, busy = false, claimRequest = 0;
  let lastAnswer = null, searchTerm = '', searchMatches = new Set(), searchLead = null;
  let needsProjection = true, needsPaint = true, overlayDirty = true, labelScale = 0;
  let depthOrder = [], edgeBatches = [], pixelRatio = 1, lastOverlay = 0;
  const DENSE_GRAPH_THRESHOLD=1200, HIT_CELL=32;
  let overlayNodes=[],overlayEdges=[],overlayAnchors=[],hitGrid=new Map();
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
    const col=Math.floor(x/HIT_CELL),row=Math.floor(y/HIT_CELL);
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
      for(const n of hitGrid.get(`${col+dx}:${row+dy}`)||[]){
        if(n.hidden)continue;
        const d=Math.hypot(x-n.screenX,y-n.screenY);
        if(d<distance){nearest=n.id;distance=d;}
      }
    }
    return nearest;
  }
  function hoverAt(e) {
    if(e.pointerType==='touch'||gesture)return;
    queueHover(nodeAt(e));
  }
  function transitionScene() {
    const focused=!!(selected||searchTerm),showConnections=$('show-connections').checked;
    for(const n of nodes){
      const active=(n.id===selected||n.id===hovered)&&!n.dimmed,matched=searchMatches.has(n.id);
      n.fromWeight=n.weight??1;n.toWeight=n.hidden?0:n.dimmed?.16:1;
      n.fromRing=n.ring??0;n.toRing=!n.hidden&&(active||matched)?1:0;
    }
    for(const e of edges){
      e.fromWeight=e.weight??1;e.toWeight=e.hidden||focused&&!e.linked||!showConnections&&!e.linked?0:1;
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
    const idle=!document.hidden&&time>idleAfter&&$('ambient-motion').checked&&!gesture&&!cameraTransition&&!sceneTransition&&!selected&&!hovered&&!searchTerm&&!editing&&$('chat-panel').hidden&&$('workspace-panel').hidden&&$('graph-options').hidden&&!document.querySelector('dialog[open]');
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
    hitGrid.clear();
    nodes.forEach(n=>{
      n.screenX=view.x+n.x*view.k;n.screenY=view.y+n.y*view.k;n.screenR=Math.max(1.5,n.radius*n.perspective*sqrtZoom);
      n.inViewport=n.screenX>-32&&n.screenX<width+32&&n.screenY>-32&&n.screenY<height+32;
      if(n.inViewport&&!n.hidden){const key=`${Math.floor(n.screenX/HIT_CELL)}:${Math.floor(n.screenY/HIT_CELL)}`;if(!hitGrid.has(key))hitGrid.set(key,[]);hitGrid.get(key).push(n);}
    });
    // Quantized opacity keeps fading edges batched instead of stroking each one.
    for(const batch of edgeBatches){
      const buckets=new Map();
      for(const e of batch.edges){
        if((e.a.screenX<0&&e.b.screenX<0)||(e.a.screenX>width&&e.b.screenX>width)||(e.a.screenY<0&&e.b.screenY<0)||(e.a.screenY>height&&e.b.screenY>height))continue;
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
      if(!n.inViewport||n.weight<.01||(!n.ring&&n.degree<6))continue;
      const r=n.screenR,extent=r*(2.8+n.ring);
      ctx.globalAlpha=(.3+n.ring*.35)*n.weight;
      ctx.drawImage(glows[family(n)],n.screenX-extent,n.screenY-extent,extent*2,extent*2);
    }
    for(const n of depthOrder){
      if(!n.inViewport||n.weight<.01)continue;
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
    overlayNodes.forEach(n=>{
      n.el.setAttribute('transform',`translate(${n.x.toFixed(2)} ${n.y.toFixed(2)})`);
      n.drawnRadius=n.screenR/view.k;
      if(scaled){n.hit.setAttribute('r',9/view.k);n.text.setAttribute('font-size',12/view.k);}
    });
    // Only highlighted edges need a pointer target. The faint overview lives on canvas.
    overlayEdges.forEach(e=>{if(e.linked&&!e.hidden)e.hit.setAttribute('d',`M${e.a.x} ${e.a.y}L${e.b.x} ${e.b.y}`);});
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
    if(nodes.length>1200){
      // Dense harvested slices use a stable seeded scatter instead of 160 force
      // iterations. Positions remain a display layout, never a similarity score.
      const groupOf=n=>n.properties?.harvest_dataset||n.properties?.dataset||n.type||'records';
      const groups=[...new Set(nodes.map(groupOf))],counts=new Map();
      nodes.forEach(n=>counts.set(groupOf(n),(counts.get(groupOf(n))||0)+1));
      const centers=new Map(),golden=Math.PI*(3-Math.sqrt(5));
      groups.forEach((id,index)=>{const radius=35*Math.sqrt(index),angle=index*golden;centers.set(id,{x:Math.cos(angle)*radius,y:Math.sin(angle)*radius,z:0});});
      nodes.forEach(n=>{
        const random=randomFor(n.id),center=centers.get(groupOf(n)),spread=24+Math.sqrt(counts.get(groupOf(n)))*9;
        const angle=random()*Math.PI*2,radius=Math.sqrt(random())*spread;
        n.wx=center.x+Math.cos(angle)*radius;n.wy=center.y+Math.sin(angle)*radius;n.wz=normal(random)*spread*.18;
        n.vx=0;n.vy=0;n.vz=0;
      });
      nodes.forEach(n=>{n.degree=0;});edges.forEach(e=>{e.a.degree++;e.b.degree++;});
      nodes.forEach(n=>project(n));
      return;
    }
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
    overlayNodes.filter(n=>svg.classList.contains('all-labels')||n.id===selected||n.id===hovered||n.id===searchLead).sort((a,b)=>priority(a)-priority(b)).forEach(n=>{
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
    view.k=Math.max(dataMode==='harvest'?.15:.04,Math.min(3,(width-padX*2)/Math.max(100,maxX-minX),(height-top-bottom)/Math.max(100,maxY-minY)));
    view.x=width/2-(minX+maxX)/2*view.k;
    view.y=top+(height-top-bottom)/2-(minY+maxY)/2*view.k;
    applyCamera();
  }
  function zoom(factor,x=width/2,y=height/2) {
    cameraTransition=null;
    const next=Math.max(dataMode==='harvest'?.12:.04,Math.min(4,view.k*factor)), ratio=next/view.k;
    view.x=x-(x-view.x)*ratio; view.y=y-(y-view.y)*ratio; view.k=next; applyCamera();
  }
  function highlight() {
    const searching=!!searchTerm,localView=$('local-view').checked;
    // Hover reveals a label and ring; only selection/search changes the whole scene.
    const id=selected, neighbors=new Set(id?[id]:[]);
    edges.forEach(e=>{if(e.a.id===id)neighbors.add(e.b.id);if(e.b.id===id)neighbors.add(e.a.id);});
    svg.classList.toggle('has-focus',!!id);svg.classList.toggle('is-searching',searching);
    nodes.forEach(n=>{
      n.dimmed=searching?!searchMatches.has(n.id):!!id&&!neighbors.has(n.id);
      n.hidden=!searching&&localView&&selected&&!neighbors.has(n.id);
    });
    edges.forEach(e=>{
      e.linked=searching?searchMatches.has(e.a.id)&&searchMatches.has(e.b.id):e.a.id===id||e.b.id===id;
      e.hidden=!searching&&localView&&selected&&!e.linked;
    });
    updateOverlayTargets(neighbors);
    transitionScene();overlayDirty=true;needsPaint=true;
  }
  function select(id,center=false) {
    clearTimeout(hoverTimer);hoverCandidate=null;
    cameraTransition=null;
    selected=id; hovered=null; lastAnswer=null;searchTerm='';searchMatches.clear();searchLead=null;$('node-search').value='';
    const node=byId.get(id);
    $('selection').hidden=!node;
    $('inspect-selected').hidden=!(isHarvestNode(node)||isResolvedNode(node));
    $('inspect-selected').textContent=isResolvedNode(node)?'Inspect identity and sources':'Inspect harvested record';
    $('harvest-expand').disabled=harvestLoading||!(isHarvestNode(node)||isResolvedNode(node))||(expandedFocusId===id&&expandedFocusDone);
    if (node) {
      $('selection-name').textContent=label(node); $('selection-type').textContent=node.type;
      if (center) { cameraTransition={start:performance.now(),x:view.x,y:view.y,toX:width/2-node.x*view.k,toY:height/2-node.y*view.k}; }
    }
    highlight(); hideResults();
    const workspaceId=workspaceNodeId(id);
    window.dispatchEvent(new CustomEvent('atlas:node-select',{detail:{node_id:workspaceId,graph_node_id:id,node:node?{id:workspaceId,graph_id:id,label:label(node),type:node.type}:null}}));
  }
  function createNodeTarget(n) {
    n.el=shape('g',{class:'net-node',role:'button',tabindex:0,'data-node':n.id,'data-kind':n.type,'data-family':family(n),'aria-label':`${n.label}, ${n.type}`,'aria-pressed':'false'});
    n.hit=shape('circle',{r:9/view.k,fill:'transparent'});
    n.text=shape('text',{class:'node-label','text-anchor':'middle','font-size':12/view.k});n.text.textContent=short(label(n));
    const title=shape('title');title.textContent=`${n.label} · ${n.type}`;
    n.el.append(title,n.hit,n.text);nodeLayer.append(n.el);
    n.el.addEventListener('focus',()=>setHover(n.id));
    n.el.addEventListener('blur',()=>setHover(null));
  }
  function updateOverlayTargets(neighbors) {
    // Dense graphs keep every point on canvas. Search, pointer picking and
    // selection expose the corresponding accessible controls on demand.
    const wanted=nodes.length>DENSE_GRAPH_THRESHOLD?new Set(overlayAnchors):new Set(nodes);
    for(const id of [selected,hovered,searchLead,document.activeElement?.closest('[data-node]')?.dataset.node,...[...searchMatches].slice(0,12),...[...neighbors].slice(0,64)]){
      const n=byId.get(id);if(n)wanted.add(n);
    }
    for(const n of overlayNodes)if(!wanted.has(n)){n.el.remove();n.el=n.hit=n.text=null;}
    overlayNodes=[...wanted];
    for(const n of overlayNodes){
      if(!n.el)createNodeTarget(n);
      n.el.classList.toggle('selected',n.id===selected);n.el.classList.toggle('hovered',n.id===hovered);
      n.el.classList.toggle('neighbor',neighbors.has(n.id));n.el.classList.toggle('dimmed',n.dimmed);
      n.el.classList.toggle('search-match',searchMatches.has(n.id));n.el.classList.toggle('search-lead',n.id===searchLead);
      n.el.setAttribute('aria-pressed',String(n.id===selected));n.el.setAttribute('display',n.hidden?'none':'');
    }
    const wantedEdges=new Set(edges.filter(e=>e.linked&&!e.hidden&&(selected||searchMatches.size<=12)));
    for(const e of overlayEdges)if(!wantedEdges.has(e)){e.el.remove();e.el=e.hit=null;}
    overlayEdges=[...wantedEdges];
    for(const e of overlayEdges){
      if(!e.el){
        e.el=shape('g',{class:'edge-group highlight',role:'button','aria-label':`${label(e.a)} ${e.claim.predicate.toLowerCase().replaceAll('_',' ')} ${label(e.b)}. Inspect evidence.`,tabindex:0,'data-claim':e.claim.id});
        e.hit=shape('path',{class:'edge-target'});const title=shape('title');title.textContent=`${label(e.a)} → ${label(e.b)} · ${e.claim.predicate.replaceAll('_',' ').toLowerCase()}`;
        e.el.append(title,e.hit);$('links').append(e.el);
      }
    }
  }
  function render() {
    $('links').replaceChildren();nodeLayer.replaceChildren();
    const contestedClaims=new Set(bundle.evidence.filter(r=>r.stance==='contradicts').map(r=>r.claim_id));
    edges=bundle.claims.filter(c=>byId.has(c.subject)&&byId.has(c.object)).map(c=>({claim:c,a:byId.get(c.subject),b:byId.get(c.object)}));
    layout();
    overlayNodes=[];overlayEdges=[];hitGrid.clear();
    edges.forEach(e=>{const contested=e.claim.context?.negated===true||contestedClaims.has(e.claim.id);e.kind=contested?'contested':e.claim.assertion_type==='inferred'?'inferred':'normal';});
    nodes.forEach(n=>{n.radius=2+Math.min(3.3,Math.sqrt(n.degree)*.66);n.el=n.hit=n.text=null;});
    overlayAnchors=[...nodes].sort((a,b)=>b.degree-a.degree||a.id.localeCompare(b.id)).slice(0,32);
    svg.dataset.nodeCount=String(nodes.length);svg.dataset.claimCount=String(edges.length);
    svg.setAttribute('aria-label',`Atlas knowledge graph: ${nodes.length.toLocaleString()} nodes. Drag to rotate; scroll to zoom. Shift-drag to pan. Search to select any entity and inspect its connections.`);
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
    if(workspaceState&&workspaceState.revision===data.revision&&bundle)return;
    const signature=JSON.stringify([
      data.nodes.map(node=>[node.id,node.label,node.type]),
      data.claims.map(claim=>[claim.id,claim.review_status,(claim.evidence||[]).map(evidence=>[evidence.source_id,evidence.excerpt,evidence.source_version])]),
      (data.sources||[]).map(source=>[source.id||source.source_id,source.title,source.url]),
      (data.documents||[]).map(document=>[document.source_id,document.version])
    ]);
    if(signature===workspaceGraphSignature){workspaceState=data;return;}
    workspaceGraphSignature=signature;
    workspaceState=data;
    composeGraph();
  }
  function composeGraph(preserveCamera=true){
    const base=currentBase()||bundle;if(!base)return;
    const previous=new Map(nodes.map(node=>[node.id,node]));
    const aliases=base.resolution?.alias_map||{};
    const canonical=id=>aliases[id]||id;
    const nodesById=new Map((base.nodes||[]).map(node=>[node.id,{...node}]));
    if(workspaceState)for(const node of workspaceState.nodes){
      const id=canonical(node.id),existing=nodesById.get(id);
      if(dataMode==='resolved'&&!existing)continue;
      const merged=existing?{...existing,...node,id,label:existing.label||node.label,aliases:[...new Set([...(existing.aliases||[]),...(node.aliases||[]),node.id])],properties:{...node.properties,...existing.properties}}:{...node,id,aliases:[...(node.aliases||[]),...(id!==node.id?[node.id]:[])]};
      nodesById.set(id,merged);
    }
    const claimsById=new Map((base.claims||[]).map(claim=>[claim.id,claim]));
    if(workspaceState)for(const claim of workspaceState.claims){if(claim.review_status==='rejected')claimsById.delete(claim.id);else claimsById.set(claim.id,{...claim,subject:canonical(claim.subject),object:canonical(claim.object)});}
    const allNodes=[...nodesById.values()],nodeIds=new Set(allNodes.map(node=>node.id));
    const allClaims=[...claimsById.values()].filter(claim=>nodeIds.has(claim.subject)&&nodeIds.has(claim.object));
    const evidenceByKey=new Map();
    for(const evidence of base.evidence||[])evidenceByKey.set(`${evidence.claim_id}:${evidence.id||evidence.source_id||evidence.locator}`,evidence);
    if(workspaceState)for(const claim of workspaceState.claims)for(const evidence of claim.evidence||[])evidenceByKey.set(`${claim.id}:${evidence.id||evidence.source_id||evidence.locator}`,{...evidence,claim_id:claim.id});
    const sourcesById=new Map();
    for(const source of [...(base.sources||[]),...(workspaceState?.sources||[])])sourcesById.set(source.id||source.source_id,source);
    for(const doc of workspaceState?.documents||[])if(!sourcesById.has(doc.source_id))sourcesById.set(doc.source_id,{id:doc.source_id,title:doc.title,url:doc.url,version:doc.version,license:doc.license});
    const hadGraph=nodes.length>0,previousView={...view};
    bundle={...base,dataset:base.dataset||workspaceState?.dataset,nodes:allNodes,claims:allClaims,evidence:[...evidenceByKey.values()],sources:[...sourcesById.values()]};
    nodes=allNodes;byId=new Map(nodes.map(node=>[node.id,node]));
    nodes.forEach(node=>{const old=previous.get(node.id);if(old){for(const key of ['wx','wy','wz'])if(Number.isFinite(old[key]))node[key]=old[key];}});
    if(selected&&!byId.has(selected))selected=null;
    const currentSearch=$('node-search').value;searchMatches.clear();searchLead=null;searchTerm='';
    const keepSelection=selected;
    render();
    if(hadGraph&&preserveCamera){view=previousView;applyCamera();paintPositions();}
    highlight();
    if(keepSelection){selected=keepSelection;highlight();}
    if(currentSearch)$('node-search').value=currentSearch;
  }
  function currentBase(){return dataMode==='resolved'?resolvedBase:harvestBase;}
  function canonicalNodeId(id){return (currentBase()?.resolution?.alias_map||{})[id]||id;}
  function isHarvestNode(node){return dataMode==='harvest'&&!!(node?.properties?.harvest||node?.properties?.harvest_dataset||String(node?.id||'').startsWith('record:'));}
  function isResolvedNode(node){return dataMode==='resolved'&&!!node&&(!!node.properties?.resolved||!!node.identity||!!node.properties?.identity_resolution||!!currentBase()?.resolution||String(node.id||'').startsWith('resolved:'));}
  function workspaceNodeId(id){
    const aliases=currentBase()?.resolution?.alias_map||{};
    if(workspaceState?.nodes?.some(node=>node.id===id))return id;
    const member=Object.keys(aliases).find(key=>aliases[key]===id&&workspaceState?.nodes?.some(node=>node.id===key));
    return member||aliases[id]||id;
  }
  function updateHarvestControls(message=''){
    const status=$('harvest-status'),meta=harvestBase?.harvest||{},total=harvestCoverage||{};
    if(message||harvestError){status.textContent=message||harvestError;}
    else {
    const metaTotals=meta.totals||{};
    const shownNodes=Number(harvestBase?.nodes?.length??meta.shown_nodes??0),shownEdges=Number(harvestBase?.claims?.length??meta.shown_edges??0);
    const totalNodes=Number(total.total_nodes??metaTotals.total_nodes??shownNodes),totalEdges=Number(total.total_edges??metaTotals.total_edges??shownEdges),records=Number(total.total_records??metaTotals.total_records??0);
    const datasetCount=Number(total.total_datasets??total.dataset_count??metaTotals.total_datasets??(Array.isArray(total.datasets)?total.datasets.length:0));
    const processed=Number(total.processed_records||0),build=String(total.build_status||'');
    status.textContent=`${shownNodes.toLocaleString()} of ${totalNodes.toLocaleString()} nodes · ${shownEdges.toLocaleString()} of ${totalEdges.toLocaleString()} relations · ${records.toLocaleString()} source rows across ${datasetCount.toLocaleString()} datasets${processed?` · ${processed.toLocaleString()} processed`:''}${build?` · ${build}`:''}.${nextHarvestOffset!==null?' This is a bounded graph view.':''}`;
    }
    $('harvest-status').hidden=dataMode!=='harvest';
    const active=dataMode==='resolved'?resolvedBase:harvestBase,metaActive=active?.harvest||{};
    const cursor=dataMode==='resolved'?resolvedNextOffset:nextHarvestOffset;
    const shown=Number(active?.nodes?.length??metaActive.shown_nodes??0),totalVisible=Number(metaActive.total_nodes??shown);
    const resolution=resolvedBase?.resolution,stats=resolution?.stats||{};
    const rawNodes=Number(harvestCoverage?.total_nodes||0),rawRecords=Number(harvestCoverage?.total_records||0),rawDatasets=Number(harvestCoverage?.total_datasets||0);
    $('resolved-status').textContent=resolvedError||`Resolved neuro graph · ${shown.toLocaleString()} shown of ${totalVisible.toLocaleString()} resolved nodes · ${Number(stats.identity_merges||0).toLocaleString()} identity merges · ${Number(stats.conflicts||0).toLocaleString()} conflicts kept visible. Full harvest remains available separately: ${rawNodes.toLocaleString()} nodes, ${rawRecords.toLocaleString()} source rows across ${rawDatasets.toLocaleString()} datasets.`;
    $('resolved-status').hidden=dataMode!=='resolved';
    $('harvest-next').disabled=harvestLoading||cursor==null;
    $('harvest-expand').disabled=harvestLoading||!(isHarvestNode(byId.get(selected))||isResolvedNode(byId.get(selected)))||(expandedFocusId===selected&&expandedFocusDone);
    $('harvest-reload').disabled=harvestLoading;$('harvest-limit').disabled=harvestLoading;
    $('harvest-limit').innerHTML=dataMode==='resolved'?'<option value="120">120 nodes</option><option value="300">300 nodes</option><option value="1000">1,000 nodes</option>':'<option value="1000">1,000 nodes</option><option value="3000">3,000 nodes</option><option value="10000">10,000 nodes</option>';
    $('harvest-limit').value=String(dataMode==='resolved'?resolvedLimit:harvestLimit);
    $('harvest-browse').hidden=dataMode!=='harvest';
    $('harvest-next').textContent=dataMode==='resolved'?'Load more resolved records':'Browse next page';
  }
  function restorePageState(base,mode){
    const meta=base?.harvest||{},focus=meta.focus||null,cursor=meta.next_offset??null;
    if(mode==='resolved')resolvedNextOffset=cursor;else nextHarvestOffset=cursor;
    expandedFocusId=focus;expandedFocusNextOffset=focus?cursor:null;expandedFocusDone=!!focus&&cursor==null;
  }
  async function loadHarvestStatus(){
    try{const response=await fetch('/api/harvest/status');if(!response.ok)throw new Error('Harvest coverage is unavailable.');harvestCoverage=await response.json();updateHarvestControls();}
    catch(_){updateHarvestControls('Harvest coverage is not available on this server. The currently loaded graph may be a curated subset.');}
  }
  async function loadResolvedGraph({offset=0,focus=null,append=false,limit=resolvedLimit}={}){
    const requestId=++harvestRequest;harvestLoading=true;resolvedError='';updateHarvestControls(focus?'Loading the selected neuro neighborhood…':'Loading the resolved neuro overview…');
    try{
      const params=new URLSearchParams({limit:String(limit),offset:String(offset)});if(focus)params.set('focus',focus);
      const response=await fetch(`/api/resolved/graph?${params}`);if(!response.ok)throw new Error(`Resolved neuro graph unavailable (${response.status}).`);
      const incoming=await response.json();if(requestId!==harvestRequest)return false;
      if(!Array.isArray(incoming.nodes)||!Array.isArray(incoming.claims))throw new Error('Resolved graph returned an unexpected shape.');
      if(append&&resolvedBase){resolvedBase={...resolvedBase,...incoming,nodes:unionRows(resolvedBase.nodes,incoming.nodes,'id'),claims:unionRows(resolvedBase.claims,incoming.claims,'id'),evidence:unionRows(resolvedBase.evidence,incoming.evidence,'id'),sources:unionRows(resolvedBase.sources,incoming.sources,'id'),resolution:incoming.resolution||resolvedBase.resolution};}
      else resolvedBase=incoming;
      const meta=incoming.harvest||{};resolvedNextOffset=meta.next_offset??null;
      if(focus){expandedFocusId=focus;expandedFocusNextOffset=meta.next_offset??null;expandedFocusDone=meta.next_offset==null;}else if(offset===0){expandedFocusId=null;expandedFocusNextOffset=null;expandedFocusDone=false;}
      resolvedLimit=limit;dataMode='resolved';$('graph-scope').value='resolved';composeGraph(append);updateHarvestControls();
      $('all-labels').disabled=nodes.length>1200;if(nodes.length>1200)$('all-labels').checked=false;
      $('all-labels').title=nodes.length>1200?'Showing every label is disabled for a dense graph view. Search or select a node to reveal its label.':'';
      $('graph-status').hidden=!!nodes.length;return true;
    }catch(error){if(requestId===harvestRequest){resolvedError=error.message;updateHarvestControls();}return false;}
    finally{if(requestId===harvestRequest){harvestLoading=false;updateHarvestControls();}}
  }
  async function loadResolvedStatus(){
    try{const response=await fetch('/api/resolved/status');if(!response.ok)throw new Error();const data=await response.json();resolvedError=data.available===false?'Resolved neuro view is not available yet.': '';if(data.resolution)resolvedBase={...(resolvedBase||{}),resolution:data.resolution};else if(data.alias_map||data.stats)resolvedBase={...(resolvedBase||{}),resolution:{scope:data.scope||'neuro',alias_map:data.alias_map||{},stats:data.stats||{},default_focus:data.default_focus}};updateHarvestControls();return data;}
    catch(_){resolvedError='Resolved neuro view is not available on this server yet.';updateHarvestControls();return null;}
  }
  function unionRows(oldRows,newRows,key){const rowKey=row=>row[key]??row.evidence_id??(row.claim_id?`${row.claim_id}:${row.source_id}:${row.locator}`:JSON.stringify(row));const map=new Map((oldRows||[]).map(row=>[rowKey(row),row]));for(const row of newRows||[])map.set(rowKey(row),row);return [...map.values()];}
  async function loadHarvestGraph({offset=0,focus=null,append=false,limit=harvestLimit}={}){
    const requestId=++harvestRequest;
    harvestLoading=true;harvestError='';updateHarvestControls(focus?'Expanding the selected neighborhood…':'Loading a bounded graph view…');
    try{
      const params=new URLSearchParams({limit:String(limit),offset:String(offset)});if(focus)params.set('focus',focus);
      const response=await fetch(`/api/harvest/graph?${params}`);if(!response.ok)throw new Error(`Harvest graph request failed (${response.status}).`);
      const incoming=await response.json();
      if(requestId!==harvestRequest)return false;
      if(!Array.isArray(incoming.nodes)||!Array.isArray(incoming.claims))throw new Error('The harvest graph returned an unexpected shape.');
      if(append&&harvestBase){
        harvestBase={...harvestBase,...incoming,
          nodes:unionRows(harvestBase.nodes,incoming.nodes,'id'),claims:unionRows(harvestBase.claims,incoming.claims,'id'),
          evidence:unionRows(harvestBase.evidence,incoming.evidence,'id'),sources:unionRows(harvestBase.sources,incoming.sources,'id')};
      }else harvestBase=incoming;
      const meta=incoming.harvest||{};
      if(focus){expandedFocusId=focus;expandedFocusNextOffset=meta.next_offset??null;expandedFocusDone=meta.next_offset==null;}
      else {nextHarvestOffset=meta.next_offset??null;if(offset===0){expandedFocusId=null;expandedFocusNextOffset=null;expandedFocusDone=false;}}
      harvestLimit=limit;harvestOffset=offset;
      dataMode='harvest';$('graph-scope').value='harvest';composeGraph(append);updateHarvestControls();
      $('all-labels').disabled=nodes.length>1200;
      if(nodes.length>1200)$('all-labels').checked=false;
      $('all-labels').title=nodes.length>1200?'Showing every label is disabled for a dense graph view. Search or select a node to reveal its label.':'';
      $('graph-status').hidden=!!nodes.length;
      return true;
    }catch(error){if(requestId===harvestRequest){harvestError=error.message;updateHarvestControls(error.message);}return false;}
    finally{if(requestId===harvestRequest){harvestLoading=false;updateHarvestControls();}}
  }
  async function switchDataMode(mode){
    const generation=++scopeGeneration;
    ++harvestRequest;harvestLoading=false;
    dataMode=mode;$('graph-scope').value=mode;harvestError='';resolvedError='';updateHarvestControls();
    if(mode==='resolved'){
      if(resolvedBase?.nodes?.length){restorePageState(resolvedBase,'resolved');composeGraph(false);updateHarvestControls();return;}
      const ok=await loadResolvedGraph({offset:0,limit:resolvedLimit});
      if(generation!==scopeGeneration)return;
      if(!ok){dataMode='harvest';$('graph-scope').value='harvest';if(!harvestBase)await loadHarvestGraph({limit:harvestLimit,offset:0});harvestError='Resolved neuro view is unavailable; showing harvested graph data.';updateHarvestControls();}
    }else{
      if(harvestBase){restorePageState(harvestBase,'harvest');composeGraph(false);updateHarvestControls();}else await loadHarvestGraph({limit:harvestLimit,offset:0});
    }
  }
  $('graph-scope').addEventListener('change',()=>switchDataMode($('graph-scope').value));
  $('harvest-reload').addEventListener('click',()=>{
    if(dataMode==='resolved'){resolvedBase=null;resolvedNextOffset=null;loadResolvedGraph({limit:Number($('harvest-limit').value)||120});}
    else{harvestBase=null;harvestOffset=0;nextHarvestOffset=null;loadHarvestGraph({limit:Number($('harvest-limit').value)||10000});}
  });
  $('harvest-limit').addEventListener('change',()=>{
    if(dataMode==='resolved'){resolvedBase=null;resolvedNextOffset=null;resolvedLimit=Number($('harvest-limit').value)||120;loadResolvedGraph({limit:resolvedLimit});}
    else{harvestBase=null;harvestOffset=0;nextHarvestOffset=null;harvestLimit=Number($('harvest-limit').value)||10000;loadHarvestGraph({limit:harvestLimit});}
  });
  $('harvest-next').addEventListener('click',()=>{
    if(dataMode==='resolved'){
      const cursor=expandedFocusId?expandedFocusNextOffset:resolvedNextOffset;
      if(cursor!==null)loadResolvedGraph({focus:expandedFocusId||null,offset:cursor,append:true,limit:resolvedLimit});
    }else if(nextHarvestOffset!==null)loadHarvestGraph({offset:nextHarvestOffset,append:true,limit:harvestLimit});
  });
  $('harvest-expand').addEventListener('click',()=>{
    if(!selected||!(isHarvestNode(byId.get(selected))||isResolvedNode(byId.get(selected))))return;
    if(dataMode==='resolved'){
      const same=expandedFocusId===selected,offset=same?expandedFocusNextOffset:0;
      if(!same)resolvedBase=null;
      loadResolvedGraph({focus:selected,offset,append:same,limit:resolvedLimit});return;
    }
    if(expandedFocusId===selected&&expandedFocusDone)return;
    const offset=expandedFocusId===selected?expandedFocusNextOffset:0;
    loadHarvestGraph({focus:selected,offset,append:true,limit:harvestLimit});
  });
  $('harvest-browse').addEventListener('click',async()=>{
    const dialog=$('harvest-datasets-dialog');if(!dialog.open)dialog.showModal();
    if(!harvestDatasets.length)await loadHarvestDatasets();
    else if(selectedDatasetId)loadHarvestRecords();
  });
  $('harvest-datasets-close').addEventListener('click',()=>$('harvest-datasets-dialog').close());
  $('harvest-dataset-select').addEventListener('change',()=>{selectedDatasetId=$('harvest-dataset-select').value;recordPage=0;loadHarvestRecords();});
  $('harvest-dataset-filter').addEventListener('input',renderDatasetOptions);
  $('harvest-record-previous').addEventListener('click',()=>{if(recordPage>0){recordPage--;loadHarvestRecords();}});
  $('harvest-record-next').addEventListener('click',()=>{recordPage++;loadHarvestRecords();});
  function datasetId(dataset){const raw=dataset.dataset_id??dataset.id??'';const match=String(raw).match(/(\d+)$/);return match?.[1]||String(raw);}
  function datasetLabel(dataset){return dataset.label||dataset.key||dataset.path||`Dataset ${datasetId(dataset)}`;}
  function renderDatasetOptions(){
    const select=$('harvest-dataset-select'),query=$('harvest-dataset-filter').value.trim().toLowerCase(),current=selectedDatasetId;
    const filtered=harvestDatasets.filter(dataset=>`${datasetLabel(dataset)} ${dataset.key||''} ${dataset.path||''} ${datasetId(dataset)}`.toLowerCase().includes(query));
    select.replaceChildren();filtered.forEach(dataset=>{
      const count=Number(dataset.processed_rows??dataset.expected_rows??0),option=new Option(`${datasetLabel(dataset)} · ${count.toLocaleString()} rows`,datasetId(dataset));select.add(option);
    });
    selectedDatasetId=filtered.some(dataset=>datasetId(dataset)===current)?current:(filtered[0]?datasetId(filtered[0]):'');select.value=selectedDatasetId;
    if(selectedDatasetId)loadHarvestRecords();else{$('harvest-record-list').replaceChildren();$('harvest-record-status').textContent='No dataset matches this filter.';}
  }
  async function loadHarvestDatasets(){
    $('harvest-record-status').textContent='Loading dataset catalog…';
    try{
      const response=await fetch('/api/harvest/datasets');if(!response.ok)throw new Error('Dataset catalog is unavailable.');const payload=await response.json();
      harvestDatasets=Array.isArray(payload)?payload:Array.isArray(payload.datasets)?payload.datasets:[];
      renderDatasetOptions();
    }catch(error){$('harvest-record-status').textContent=error.message;$('harvest-record-list').replaceChildren();}
  }
  async function loadHarvestRecords(){
    if(!selectedDatasetId)return;const requestId=++recordRequest;
    $('harvest-record-status').textContent='Loading source records…';$('harvest-record-next').disabled=true;
    try{
      const params=new URLSearchParams({dataset:selectedDatasetId,page:String(recordPage),limit:'50'}),response=await fetch(`/api/harvest/records?${params}`);
      if(!response.ok)throw new Error('This dataset page could not be loaded.');const data=await response.json();if(requestId!==recordRequest)return;
      recordPage=Number(data.page||0);const records=Array.isArray(data.records)?data.records:[],total=Number(data.total||0),pages=Math.max(1,Math.ceil(total/Number(data.limit||50)));
      $('harvest-record-status').textContent=`${datasetLabel(harvestDatasets.find(dataset=>datasetId(dataset)===selectedDatasetId)||{})} · page ${recordPage+1} of ${pages} · ${total.toLocaleString()} total rows`;
      const list=$('harvest-record-list');list.replaceChildren();
      if(!records.length)list.append(make('p','','No records are available on this page.'));
      records.forEach(pointer=>{
        const row=make('article','harvest-record-item'),details=make('p');
        const rowNumber=pointer.row??pointer.one_based_row??'unknown',path=pointer.path||pointer.dataset_key||'';
        details.textContent=`Row ${rowNumber}${path?` · ${path}`:''}${pointer.sha256?` · SHA-256 ${pointer.sha256}`:''}`;
        const button=make('button','workspace-button','Inspect record');button.type='button';
        const id=pointer.id||pointer.record_id||`record:${selectedDatasetId}:${rowNumber}`;
        button.addEventListener('click',()=>openHarvestNode(id));
        row.append(details,button);list.append(row);
      });
      $('harvest-record-previous').disabled=recordPage<=0;$('harvest-record-next').disabled=(recordPage+1)*Number(data.limit||50)>=total;
    }catch(error){if(requestId===recordRequest){$('harvest-record-status').textContent=error.message;$('harvest-record-list').replaceChildren();}}
  }
  async function fetchHarvestNode(id){
    const response=await fetch(`/api/harvest/node?${new URLSearchParams({id})}`);if(!response.ok)throw new Error('The harvested record could not be loaded.');
    const payload=await response.json();if(payload.node===null)return null;
    const node=payload.node||payload;
    if(!payload.record&&node.properties?.record){
      const pointer=node.properties.record,pointerId=typeof pointer==='string'?pointer:pointer.id||pointer.record_id||`record:${pointer.dataset_id}:${pointer.row}`;
      const record=await fetchHarvestRecord(pointerId);if(record)return {...payload,...record,node};
    }
    return {...payload,node};
  }
  async function fetchHarvestRecord(id){
    const response=await fetch(`/api/harvest/record?${new URLSearchParams({id})}`);if(!response.ok)return null;return response.json();
  }
  function appendHarvestNode(node){
    if(!harvestBase)harvestBase={nodes:[],claims:[],evidence:[],sources:[],dataset:{title:'Harvested graph'}};
    harvestBase.nodes=unionRows(harvestBase.nodes,[node],'id');composeGraph();
  }
  function renderHarvestRecordDetails(data,titleFallback='Harvested source record'){
    const dialog=$('record-dialog'),content=$('record-content'),node=data.node||data,record=data.record||node.record||{},raw=record.data??data.data??null;
    const provenance=record.provenance||data.provenance||node.provenance||{};
    $('record-kind').textContent='Harvested source · unreviewed';
    $('record-title').textContent=node.label||node.title||data.label||titleFallback;
    content.replaceChildren();
    content.append(make('p','harvest-record-warning','This is a raw harvested record or provenance pointer. It has not been machine-checked as a graph assertion or scientifically reviewed.'));
    const meta=[];
    if(provenance.dataset||data.dataset||node.properties?.harvest_dataset)meta.push(`Dataset · ${provenance.dataset||data.dataset||node.properties.harvest_dataset}`);
    if(provenance.path||data.path)meta.push(`File · ${provenance.path||data.path}`);
    if(provenance.row||data.row)meta.push(`Row · ${provenance.row||data.row}`);
    if(provenance.sha256||data.sha256)meta.push(`SHA-256 · ${provenance.sha256||data.sha256}`);
    if(meta.length)content.append(make('p','',meta.join(' · ')));
    const urls=[...(Array.isArray(provenance.source_urls)?provenance.source_urls:[]),...(Array.isArray(record.source_urls)?record.source_urls:[])];
    [...new Set(urls)].forEach(url=>{try{const parsed=new URL(url);if(['http:','https:'].includes(parsed.protocol))content.append(linkForHarvestSource(parsed.href));}catch(_){}});
    const licenses=provenance.licenses||record.licenses||[];if(licenses.length)content.append(make('p','',`License metadata · ${Array.isArray(licenses)?licenses.join(' · '):String(licenses)}`));
    const json=make('pre','harvest-record-json',raw===null?JSON.stringify(data,null,2):typeof raw==='string'?raw:JSON.stringify(raw,null,2));content.append(json);
    if(!dialog.open)dialog.showModal();
  }
  function linkForHarvestSource(url){const link=make('a','','Open recorded source URL ↗');link.href=url;link.target='_blank';link.rel='noopener noreferrer';return link;}
  async function openHarvestNode(id){
    const request=++claimRequest,dialog=$('record-dialog');$('record-content').replaceChildren(make('p','','Loading harvested source details…'));$('record-kind').textContent='Harvested source';$('record-title').textContent=label(byId.get(id)||{label:id});if(!dialog.open)dialog.showModal();
    try{const data=String(id).startsWith('record:')?await fetchHarvestRecord(id):await fetchHarvestNode(id);if(request!==claimRequest)return;if(!data)throw new Error('No harvested record was returned for this node.');renderHarvestRecordDetails({...data,node:data.node||byId.get(id)||{label:id}},label(byId.get(id)||{label:id}));}
    catch(error){if(request===claimRequest)$('record-content').replaceChildren(make('p','',error.message));}
  }
  function addSafeSourceLink(container,url,labelText='Open source ↗'){
    try{const target=new URL(url);if(!['http:','https:'].includes(target.protocol))return;const a=make('a','',labelText);a.href=target.href;a.target='_blank';a.rel='noopener noreferrer';container.append(a);}catch(_){}
  }
  async function openResolvedNode(id){
    const request=++claimRequest,node=byId.get(id),dialog=$('record-dialog');
    $('record-kind').textContent='Resolved neuro entity · machine-checked identity';$('record-title').textContent=label(node||{label:id});$('record-content').replaceChildren(make('p','','Loading identity and source provenance…'));if(!dialog.open)dialog.showModal();
    try{
      const response=await fetch(`/api/resolved/node?${new URLSearchParams({id})}`);if(!response.ok)throw new Error('Resolved identity details could not be loaded.');const data=await response.json();if(request!==claimRequest)return;
      const content=$('record-content');content.replaceChildren();
      content.append(make('p','harvest-record-warning','Identity resolution is machine-checked, not scientific review. Source conflicts and unresolved mentions remain distinct from accepted identity decisions.'));
      const identity=data.identity||{},members=Array.isArray(identity.members)?identity.members:[],decisions=Array.isArray(identity.decisions)?identity.decisions:[],conflicts=Array.isArray(identity.conflicts)?identity.conflicts:[];
      content.append(make('h3','','Identity members'));
      if(members.length){const list=make('ul','resolved-member-list');members.forEach(member=>list.append(make('li','',typeof member==='string'?member:[member.id||member.member_id,member.label,member.type].filter(Boolean).join(' · '))));content.append(list);}else content.append(make('p','','No identity members were returned.'));
      const pointers=new Map();
      const addPointer=value=>{if(!value)return;const row=typeof value==='string'?{id:value}:value,id=row.id||row.record_id||(row.dataset_id&&row.row?`record:${row.dataset_id}:${row.row}`:null);if(id&&String(id).startsWith('record:'))pointers.set(id,row);};
      const provenance=data.provenance||{},identityProvenance=identity.provenance||{};
      for(const member of [...(provenance.original_nodes||[]),...(identityProvenance.original_nodes||[])])addPointer(member.provenance?.record||member.provenance);
      for(const edge of [...(provenance.identity_links||[]),...(identityProvenance.identity_links||[]),...decisions])addPointer(edge.provenance?.record||edge.link?.provenance?.record||edge.link?.provenance);
      for(const pointer of [node?.provenance,node?.properties?.record])addPointer(pointer?.record||pointer);
      if(pointers.size){content.append(make('h3','','Original source records'));pointers.forEach((pointer,recordId)=>{const button=make('button','workspace-link-button',`Open original record · ${pointer.dataset_key||pointer.dataset||'source'} · row ${pointer.row??'?'}`);button.type='button';button.addEventListener('click',()=>openHarvestNode(recordId));content.append(button);});}
      content.append(make('h3','','Accepted identity decisions'));
      if(decisions.length){decisions.forEach(decision=>{const card=make('article','resolved-proof'),link=decision.link||{},prov=decision.provenance||link.provenance||{},record=prov.record||{};card.append(make('strong','',String(decision.decision||decision.status||'accepted identity decision').replaceAll('_',' ')),make('p','',decision.rationale||decision.reason||decision.note||`${link.subject||''} ${link.rule||''} ${link.object||''}`.trim()||'Recorded machine identity mapping.'));if(record.id)card.append(make('small','',`${record.dataset_key||record.dataset||'Source record'} · row ${record.row??'unknown'}${record.sha256?` · SHA-256 ${record.sha256}`:''}`));const urls=[...(Array.isArray(record.source_urls)?record.source_urls:[]),...(decision.source_url?[decision.source_url]:[])];[...new Set(urls)].forEach(url=>addSafeSourceLink(card,url));content.append(card);});}else content.append(make('p','','No accepted identity decision detail was returned.'));
      content.append(make('h3','','Conflicts and unresolved source mentions'));
      if(conflicts.length){conflicts.forEach(conflict=>{const card=make('article','resolved-conflict'),prov=conflict.provenance||conflict.link?.provenance||{},record=prov.record||{};card.append(make('strong','',conflict.label||conflict.kind||'Source conflict'),make('p','',conflict.message||conflict.reason||conflict.excerpt||JSON.stringify(conflict)));if(record.id)card.append(make('small','',`${record.dataset_key||record.dataset||'Source record'} · row ${record.row??'unknown'}${record.sha256?` · SHA-256 ${record.sha256}`:''}`));const urls=[...(Array.isArray(record.source_urls)?record.source_urls:[]),...(conflict.source_url?[conflict.source_url]:[])];[...new Set(urls)].forEach(url=>addSafeSourceLink(card,url));content.append(card);});}else content.append(make('p','','No conflicts were recorded for this resolved entity.'));
      const sourceProvenance=data.provenance||data.properties?.provenance||{};
      const mention=identity.mention||data.mention||sourceProvenance.mention;
      if(mention){
        content.append(make('h3','','Unresolved source mention'));
        if(mention.mention)content.append(make('p','',`Mention · ${mention.mention}`));
        if(mention.excerpt||mention.text)content.append(make('blockquote','',mention.excerpt||mention.text));
        if(mention.source_id)content.append(make('small','',`${mention.source_id}${mention.source_version?` · ${mention.source_version}`:''}${mention.locator?` · ${mention.locator}`:''}${mention.mention_locator?` · ${mention.mention_locator}`:''}`));
        if(mention.title)content.append(make('p','',mention.title));
        const source=[...(workspaceState?.documents||[]),...(workspaceState?.sources||[])].find(row=>(row.source_id||row.id)===mention.source_id);
        addSafeSourceLink(content,mention.url||source?.url,'Open mention source ↗');
        if(mention.metadata_status)content.append(make('small','',`Metadata status · ${mention.metadata_status}`));
      }
      const metadataStatus=data.metadata_status||node?.properties?.metadata_status||sourceProvenance.metadata_status;
      if(metadataStatus)content.append(make('p','',`Source metadata status · ${metadataStatus}`));
      const provenanceRows=Array.isArray(sourceProvenance.original_nodes)?sourceProvenance.original_nodes:[];
      provenanceRows.forEach(row=>{const source=row.provenance||{};if(source.url)addSafeSourceLink(content,source.url,`Open source page · ${row.node_id||'original node'} ↗`);for(const url of source.source_urls||[])addSafeSourceLink(content,url,`Open recorded source URL ↗`);});
      if(sourceProvenance.url)addSafeSourceLink(content,sourceProvenance.url,'Open source page ↗');
      if(sourceProvenance){content.append(make('h3','','Source provenance'));content.append(make('pre','harvest-record-json',JSON.stringify(sourceProvenance,null,2)));}
      content.append(make('p','','Relationships remain evidence scoped; identity resolution does not approve the biological claims attached to an entity.'));
    }catch(error){if(request===claimRequest)$('record-content').replaceChildren(make('p','',error.message));}
  }
  async function openHarvestClaim(id){
    const request=++claimRequest,dialog=$('record-dialog');$('record-content').replaceChildren(make('p','','Loading harvested relationship provenance…'));$('record-kind').textContent='Harvested relationship · unreviewed';$('record-title').textContent='Harvested graph relation';if(!dialog.open)dialog.showModal();
    try{
      const response=await fetch(`/api/harvest/claim?${new URLSearchParams({id})}`);if(!response.ok)throw new Error('This harvested relationship could not be loaded.');
      const data=await response.json(),claim=data.claim||data,subject=byId.get(claim.subject)?.label||claim.subject||'Record',object=byId.get(claim.object)?.label||claim.object||'Record';
      if(request!==claimRequest)return;
      const pointer=claim.context?.record||data.record_pointer||data.provenance?.record||null;
      let record=data.record?data:null;
      if(!record&&pointer){const pointerId=typeof pointer==='string'?pointer:pointer.id||pointer.record_id||`record:${pointer.dataset_id}:${pointer.row}`;record=await fetchHarvestRecord(pointerId);}
      if(request!==claimRequest)return;
      renderHarvestRecordDetails(record||{node:{label:`${subject} → ${object}`},record:{data:claim},provenance:data.provenance||{}},`${subject} → ${object}`);
      const content=$('record-content'),relation=make('p','harvest-relation',`${subject} · ${String(claim.predicate||'related to').replaceAll('_',' ')} · ${object}`);content.prepend(relation);
      const status=make('p','harvest-record-warning','This harvested relation is unreviewed raw-source context. It is not an approved scientific assertion.');content.insertBefore(status,relation.nextSibling);
    }catch(error){if(request===claimRequest)$('record-content').replaceChildren(make('p','',error.message));}
  }
  $('inspect-selected').addEventListener('click',()=>{if(!selected)return;const node=byId.get(selected);if(isResolvedNode(node))openResolvedNode(selected);else if(isHarvestNode(node))openHarvestNode(selected);});
  window.addEventListener('atlas:workspace-updated',event=>{
    const incoming=event.detail?.state;
    if(!incoming)return;
    if(!bundle){pendingWorkspaceState=incoming;return;}
    setWorkspaceState(incoming);
  });
  window.addEventListener('atlas:select-node',event=>{
    const id=canonicalNodeId(event.detail?.node_id||'');
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
      const b=make('button','',label(n));b.type='button';b.dataset.nodeId=n.id;b.append(make('small','',n.type));
      b.addEventListener('click',()=>{select(n.id,true);n.el.focus();});
      b.addEventListener('focus',()=>{searchLead=n.id;highlight();});results.append(b);
    });
    if(!matches.length)results.append(make('p','',dataMode==='resolved'?'Searching the loaded resolved neuro graph…':'Searching the loaded graph and full harvest index…'));
    results.hidden=false;$('node-search').setAttribute('aria-expanded','true');
    clearTimeout(searchTimer);const requestId=++searchRequest;
    if(searchTerm)searchTimer=setTimeout(()=>searchHarvest(searchTerm,requestId),220);
  }
  async function searchHarvest(query,requestId){
    const resultsElement=$('node-results');
    try{
      const resolved=dataMode==='resolved',endpoint=resolved?'/api/resolved/search':'/api/harvest/search';
      const response=await fetch(`${endpoint}?${new URLSearchParams({q:query,limit:'40'})}`);if(!response.ok)throw new Error('');
      const data=await response.json();if(requestId!==searchRequest||query!==$('node-search').value.toLowerCase().trim())return;
      const results=resultsElement,matches=Array.isArray(data.results)?data.results:Array.isArray(data.nodes)?data.nodes:[];
      const existing=new Set([...results.querySelectorAll('[data-node-id]')].map(button=>button.dataset.nodeId));
      if(matches.length){const pending=results.querySelector('p');if(pending)pending.remove();}
      if(matches.length)results.append(make('p','harvest-search-heading',`${resolved?'Resolved neuro index':'Harvest index'} · ${Number(data.total||matches.length).toLocaleString()} matches`));
      matches.forEach(result=>{
        const node=result.node||result,id=node.id||result.node_id;if(!id||existing.has(id))return;existing.add(id);
        if(!searchLead)searchLead=id;
        const button=make('button','harvest-search-result',node.label||result.label||id);button.type='button';button.dataset.harvestResult='true';button.dataset.nodeId=id;
        button.append(make('small','',`${node.type||result.type||'Harvest record'}${node.properties?.harvest_dataset?` · ${node.properties.harvest_dataset}`:''}`));
        button.addEventListener('click',async()=>{
          hideResults();$('node-search').blur();
          if(byId.has(id)){select(id,true);byId.get(id)?.el.focus({preventScroll:true});return;}
          if(dataMode==='resolved')await loadResolvedGraph({focus:id,offset:0,append:false,limit:resolvedLimit});
          else await loadHarvestGraph({focus:id,append:true,limit:harvestLimit});
          if(byId.has(id)){select(id,true);byId.get(id)?.el.focus({preventScroll:true});}
          else if(dataMode==='harvest'){const raw=await fetchHarvestNode(id);if(raw?.node){appendHarvestNode(raw.node);select(id,true);}}
        });
        results.append(button);
      });
      if(!matches.length&&!results.querySelector('button'))results.replaceChildren(make('p','','No match in the loaded graph or harvest index.'));
    }catch(_){if(requestId===searchRequest&&!resultsElement.querySelector('button'))resultsElement.replaceChildren(make('p','','The harvest search index is unavailable; try a broader loaded-graph search.'));}
  }
  $('node-search').addEventListener('input',searchNodes);
  $('node-search').addEventListener('keydown',e=>{
    if(e.key==='Escape'){$('node-search').value='';searchNodes();}
    if(e.key==='ArrowDown'){e.preventDefault();$('node-results').querySelector('button')?.focus();}
    if(e.key==='Enter'&&searchLead){e.preventDefault();const id=searchLead;if(byId.has(id)){select(id,true);byId.get(id)?.el.focus();}else $('node-results').querySelector(`[data-node-id="${CSS.escape(id)}"]`)?.click();}
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

  async function openResolvedClaim(id){
    const request=++claimRequest,dialog=$('record-dialog');$('record-kind').textContent='Resolved graph assertion · source review status';$('record-title').textContent='Loading assertion…';$('record-content').replaceChildren(make('p','','Loading source-scoped claim details…'));if(!dialog.open)dialog.showModal();
    try{
      const response=await fetch(`/api/resolved/claim?${new URLSearchParams({id})}`);if(!response.ok)throw new Error('Resolved claim details could not be loaded.');const data=await response.json();if(request!==claimRequest)return;
      const claim=data.claim||data,subject=byId.get(claim.subject),object=byId.get(claim.object);$('record-title').textContent=`${subject?label(subject):claim.subject||'Entity'} → ${object?label(object):claim.object||'Entity'}`;
      $('record-kind').textContent=`${String(claim.predicate||'assertion').replaceAll('_',' ').toLowerCase()} · ${String(claim.review_status||'unreviewed').replaceAll('_',' ')}`;
      const content=$('record-content');content.replaceChildren();
      content.append(make('p','harvest-record-warning','Resolved entities do not make their attached biological relationships approved. Evidence below is source-scoped; confidence or extraction scores are not calibrated scientific probabilities.'));
      const context=Object.entries(claim.context||{}).map(([key,value])=>`${key.replaceAll('_',' ')}: ${String(value).replaceAll('_',' ')}`).join(' · ');if(context)content.append(make('p','',context));
      if(claim.extraction_confidence!==undefined)content.append(make('small','',`Machine extraction score · ${claim.extraction_confidence} (${claim.confidence_calibration||'uncalibrated'}); this is not a scientific confidence estimate.`));
      const sources=Array.isArray(data.sources)?data.sources:[],support=Array.isArray(data.support)?data.support:[],contradictions=Array.isArray(data.contradictions)?data.contradictions:[];
      const evidence=[...support.map(row=>({...row,stance:row.stance||'supports'})),...contradictions.map(row=>({...row,stance:'contradicts'}))];
      if(!evidence.length)content.append(make('p','','No source excerpt is attached to this resolved relationship.'));
      evidence.forEach(row=>{
        const source=sources.find(item=>(item.id||item.source_id)===row.source_id),card=make('article',row.stance==='contradicts'?'counter':'resolved-proof');
        card.append(make('strong','',row.stance==='contradicts'?'Counter-evidence':'Supporting source excerpt'),make('blockquote','',row.excerpt||'Exact source text was not returned.'),make('p','',source?.title||row.source_id||'Source metadata unavailable'),make('small','',`${row.locator||'Locator unavailable'} · ${String(row.review_status||claim.review_status||'unreviewed').replaceAll('_',' ')}${row.source_version?` · ${row.source_version}`:''}${row.confidence!==undefined?` · machine score ${row.confidence} (not calibrated)`:''}`));
        if(source){
          const authors=Array.isArray(source.authors)?source.authors.join(', '):source.authors;
          const metadata=[authors,source.year,source.pmid?`PMID ${source.pmid}`:'',source.doi?`DOI ${source.doi}`:''].filter(Boolean).join(' · ');
          if(metadata)card.append(make('p','',metadata));
          card.append(make('p','',`${source.version||source.retrieved_at||'Version not recorded'} · ${source.license||'reuse terms not recorded'}`));
          if(source.metadata_status)card.append(make('small','',`Source metadata status · ${source.metadata_status}`));
          addSafeSourceLink(card,source.url||source.provenance?.url);
        }
        content.append(card);
      });
      content.append(make('p','','A graph relation is a source-backed candidate assertion, not a treatment recommendation or clinical conclusion.'));
    }catch(error){if(request===claimRequest)$('record-content').replaceChildren(make('p','',error.message));}
  }
  async function openClaim(id) {
    if(String(id).startsWith('harvest:edge:')){openHarvestClaim(id);return;}
    const workspaceClaim=workspaceState?.claims?.find(claim=>claim.id===id);
    if(workspaceClaim){openWorkspaceClaim(workspaceClaim);return;}
    if(dataMode==='resolved'&&(String(id).startsWith('resolved:')||resolvedBase?.claims?.some(claim=>claim.id===id))){openResolvedClaim(id);return;}
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
  $('record-close').onclick=()=>{claimRequest++;$('record-dialog').close();};
  $('record-dialog').addEventListener('cancel',()=>{claimRequest++;});

  function openChat(){ $('workspace-panel').hidden=true;$('workspace-toggle').setAttribute('aria-expanded','false');$('chat-panel').hidden=false;$('chat-toggle').setAttribute('aria-expanded','true');$('question').focus(); }
  function closeChat(){ $('chat-panel').hidden=true;$('chat-toggle').setAttribute('aria-expanded','false');window.dispatchEvent(new Event('atlas:voice-cancel'));$('chat-toggle').focus(); }
  $('chat-toggle').onclick=()=>$('chat-panel').hidden?openChat():closeChat();$('chat-close').onclick=closeChat;
  $('ask-selected').onclick=()=>{openChat();$('question').value=selected?`What is connected to ${label(byId.get(selected))}?`:'';};
  $('chat-panel').addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();closeChat();}});
  $('chat-form').onsubmit=e=>{e.preventDefault();ask();};
  $('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask();}};
  async function ask() {
    const question=$('question').value.trim();if(!question||busy)return;
    const selectedNode=byId.get(selected),selectedHarvest=isHarvestNode(selectedNode),workspaceId=workspaceNodeId(selected),selectedInWorkspace=!!workspaceId&&workspaceState?.nodes?.some(node=>node.id===workspaceId);
    const selectedContext=(selectedHarvest||isResolvedNode(selectedNode)&&!selectedInWorkspace)?`Selected ${selectedHarvest?'harvest':'resolved neuro'} graph entity: ${label(selectedNode)}. The cited-source assistant searches its configured source corpus, which is narrower than the full graph. User question: ${question}`:question;
    busy=true;$('send-question').disabled=true;window.dispatchEvent(new Event('atlas:voice-cancel'));
    const box=$('chat-messages');
    box.append(make('div','chat-message user',question));$('question').value='';
    if(selectedHarvest||isResolvedNode(selectedNode)&&!selectedInWorkspace)box.append(make('p','harvest-ask-scope',`Selected ${selectedHarvest?'harvest':'resolved neuro'} entity: ${label(selectedNode)}. The question is sent as text context; the configured cited-source search does not cover the full graph.`));
    const reply=make('div','chat-message answer');reply.append(make('p','','Looking through the graph…'));box.append(reply);box.scrollTop=box.scrollHeight;
    try{
      const params=new URLSearchParams({q:selectedContext});if(selectedInWorkspace&&!selectedHarvest)params.set('node',workspaceId);
      if(!selectedHarvest&&lastAnswer?.claim_ids?.length&&/\b(this|that|these|those)\b/i.test(question)&&/\b(evidence|sources?|support|proof|papers?)\b/i.test(question))lastAnswer.claim_ids.slice(0,100).forEach(id=>params.append('claim',id));
      const response=await fetch(`/api/ask?${params}`),data=await response.json();if(!response.ok)throw new Error(data.error?.message||'The graph could not answer just now.');
      lastAnswer=data;
      reply.replaceChildren(make('div','answer-label',data.synthetic?'Atlas · fictional demo records':'Atlas · graph records'),make('p','',data.answer));
      if(data.claim_ids?.length){const refs=make('div','chat-citations');data.claim_ids.forEach((id,i)=>{const claim=bundle.claims.find(c=>c.id===id);if(!claim)return;const b=make('button','',`[${i+1}] ${claim.predicate.replaceAll('_',' ').toLowerCase()}`);b.type='button';b.title=`${byId.get(claim.subject)?.label} → ${byId.get(claim.object)?.label}`;b.onclick=()=>openClaim(id);refs.append(b);});reply.append(refs);}
    }catch(error){reply.replaceChildren(make('p','',error.message||'The answer could not be loaded. Try again.'));}
    finally{busy=false;$('send-question').disabled=false;box.scrollTop=box.scrollHeight;}
  }

  document.addEventListener('click',e=>{if(!e.target.closest('.graph-search'))hideResults();if(!e.target.closest('#graph-options')&&!e.target.closest('#options-toggle')){$('graph-options').hidden=true;$('options-toggle').setAttribute('aria-expanded','false');}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('graph-options').hidden=true;$('options-toggle').setAttribute('aria-expanded','false');hideResults();}});

  async function init() {
    const initialScopeGeneration=scopeGeneration;
    try{
      const statusRequest=Promise.all([loadHarvestStatus(),loadResolvedStatus()]);
      const loaded=await loadHarvestGraph({limit:harvestLimit,offset:0});
      if(!loaded&&scopeGeneration===initialScopeGeneration){
        const fallback=await loadResolvedGraph({limit:resolvedLimit,offset:0});
        if(!fallback&&scopeGeneration===initialScopeGeneration){
          const response=await fetch('/api/graph');if(!response.ok)throw new Error('The graph could not be loaded. Refresh to try again.');
          dataMode='harvest';$('graph-scope').value='harvest';harvestBase=null;harvestError='The harvest projection is unavailable. Showing the smaller curated graph view.';
          bundle=await response.json();nodes=bundle.nodes.map(node=>({...node}));byId=new Map(nodes.map(node=>[node.id,node]));render();updateHarvestControls();
        }
      }
      await statusRequest;
      if(pendingWorkspaceState){const pending=pendingWorkspaceState;pendingWorkspaceState=null;setWorkspaceState(pending);}
      document.fonts.ready.then(placeLabels);
      $('graph-status').hidden=!!nodes.length;if(!nodes.length)$('graph-status').textContent='No entities have been added yet.';
    }catch(error){$('graph-status').textContent=error.message;$('chat-toggle').disabled=true;$('node-search').disabled=true;}
    finally{window.dispatchEvent(new Event('atlas:ready'));}
  }
  init();
})();

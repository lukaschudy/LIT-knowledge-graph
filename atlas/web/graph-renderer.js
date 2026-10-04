/* Batched GPU rendering; graph.js keeps the accessible overlay and Canvas fallback. */
(() => {
  'use strict';
  window.createAtlasGraphRenderer = canvas => {
    const gl=canvas.getContext('webgl',{alpha:true,antialias:false,premultipliedAlpha:true,depth:false,stencil:false});
    if(!gl)return null;
    const shaders=[],programs=[],buffers=[];
    function program(vertex,fragment){
      const p=gl.createProgram();programs.push(p);
      for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]){
        const s=gl.createShader(type);shaders.push(s);gl.shaderSource(s,source);gl.compileShader(s);
        if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));
        gl.attachShader(p,s);
      }
      gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));
      return p;
    }
    try {
      const edgeProgram=program(`
        attribute vec2 position; attribute vec4 color; attribute vec2 dash;
        uniform vec2 viewport; varying vec4 tint; varying vec2 pattern;
        void main(){gl_Position=vec4(position/viewport*vec2(2.,-2.)+vec2(-1.,1.),0.,1.);tint=color;pattern=dash;}
      `,`
        precision mediump float; varying vec4 tint; varying vec2 pattern;
        void main(){if(pattern.y>0. && mod(pattern.x,pattern.y+5.)>pattern.y)discard;
          gl_FragColor=vec4(tint.rgb*tint.a,tint.a);}
      `);
      const nodeProgram=program(`
        attribute vec2 position; attribute float radius; attribute vec4 color; attribute vec2 effects;
        uniform vec2 viewport; uniform float pixelRatio; uniform float maxSize;
        varying vec4 tint; varying vec3 sphere;
        void main(){
          gl_Position=vec4(position/viewport*vec2(2.,-2.)+vec2(-1.,1.),0.,1.);
          gl_PointSize=min(maxSize,max(radius*5.6,(radius+6.)*2.*step(.01,effects.x))*pixelRatio);
          tint=color;sphere=vec3(radius,effects);
        }
      `,`
        precision mediump float; varying vec4 tint; varying vec3 sphere;
        void main(){
          float extent=max(sphere.x*2.8,(sphere.x+6.)*step(.01,sphere.y));
          vec2 p=(gl_PointCoord-.5)*2.*extent;float d=length(p);float r=sphere.x;
          float core=1.-smoothstep(r-.6,r+.4,d);
          float light=1.-smoothstep(0.,1.4,length(p/max(r,.65)+vec2(.35,.4)));
          vec3 color=mix(tint.rgb*.72,tint.rgb,light);
          color=mix(color,vec3(.93,1.,1.),pow(light,6.)*.8);
          float halo=exp(-d*d/max(1.,r*r*2.))*sphere.z*.22;
          float ring=(1.-smoothstep(.6,1.5,abs(d-r-4.)))*sphere.y;
          float alpha=max(core*tint.a,max(halo*tint.a,ring));
          if(alpha<.003)discard;
          color=mix(tint.rgb,color,core);
          gl_FragColor=vec4(color*alpha,alpha);
        }
      `);
      function stream(p,attributes,stride){
        const buffer=gl.createBuffer();buffers.push(buffer);
        return {p,buffer,stride,attributes:attributes.map(([name,size,offset])=>({location:gl.getAttribLocation(p,name),size,offset})),viewport:gl.getUniformLocation(p,'viewport'),data:new Float32Array(0)};
      }
      const lines=stream(edgeProgram,[['position',2,0],['color',4,2],['dash',2,6]],8);
      const points=stream(nodeProgram,[['position',2,0],['radius',1,2],['color',4,3],['effects',2,7]],9);
      const ratioLocation=gl.getUniformLocation(nodeProgram,'pixelRatio'),maxLocation=gl.getUniformLocation(nodeProgram,'maxSize');
      const maxSize=gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)[1],rgbCache=new Map();
      function rgb(hex){if(!rgbCache.has(hex))rgbCache.set(hex,[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255));return rgbCache.get(hex);}
      function reserve(stream,size){if(stream.data.length<size)stream.data=new Float32Array(Math.ceil(size/4096)*4096);}
      function upload(stream,length,width,height){
        gl.useProgram(stream.p);gl.bindBuffer(gl.ARRAY_BUFFER,stream.buffer);
        gl.bufferData(gl.ARRAY_BUFFER,stream.data.subarray(0,length),gl.DYNAMIC_DRAW);
        for(let i=0;i<6;i++)gl.disableVertexAttribArray(i);
        for(const a of stream.attributes){gl.enableVertexAttribArray(a.location);gl.vertexAttribPointer(a.location,a.size,gl.FLOAT,false,stream.stride*4,a.offset*4);}
        gl.uniform2f(stream.viewport,width,height);
      }
      return {
        draw(nodes,batches,colors,width,height,pixelRatio){
          gl.viewport(0,0,canvas.width,canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);
          gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
          reserve(lines,batches.reduce((count,b)=>count+b.edges.length*16,0));let i=0;
          for(const batch of batches){
            const color=rgb(batch.color),dash=batch.kind==='inferred'?4:batch.kind==='contested'?2:0;
            for(const e of batch.edges){
              const a=e.a,b=e.b;
              if((a.screenX<0&&b.screenX<0)||(a.screenX>width&&b.screenX>width)||(a.screenY<0&&b.screenY<0)||(a.screenY>height&&b.screenY>height))continue;
              const base=a.depth+b.depth<0?.16:.045,alpha=(e.weight??1)*(base+(.68-base)*(e.emphasis??0));
              if(alpha<.003)continue;
              const length=dash?Math.hypot(a.screenX-b.screenX,a.screenY-b.screenY):0;
              const data=lines.data;
              data[i++]=a.screenX;data[i++]=a.screenY;data[i++]=color[0];data[i++]=color[1];data[i++]=color[2];data[i++]=alpha;data[i++]=0;data[i++]=dash;
              data[i++]=b.screenX;data[i++]=b.screenY;data[i++]=color[0];data[i++]=color[1];data[i++]=color[2];data[i++]=alpha;data[i++]=length;data[i++]=dash;
            }
          }
          upload(lines,i,width,height);gl.drawArrays(gl.LINES,0,i/8);
          reserve(points,nodes.length*9);i=0;
          for(const n of nodes){
            if(!n.inViewport||n.weight<.01)continue;
            const depthAlpha=Math.max(.12,Math.min(1,.66-n.depth/1050));
            const alpha=n.weight*(depthAlpha+(1-depthAlpha)*n.ring);
            const color=rgb(colors[n.colorKey]),data=points.data;
            data[i++]=n.screenX;data[i++]=n.screenY;data[i++]=n.screenR;
            data[i++]=color[0];data[i++]=color[1];data[i++]=color[2];data[i++]=alpha;
            data[i++]=n.ring;data[i++]=(n.degree>=4&&n.depth<=0)?1:.35;
          }
          upload(points,i,width,height);gl.uniform1f(ratioLocation,pixelRatio);gl.uniform1f(maxLocation,maxSize);gl.drawArrays(gl.POINTS,0,i/9);
        }
      };
    } catch(error) {
      for(const buffer of buffers)gl.deleteBuffer(buffer);
      for(const p of programs)gl.deleteProgram(p);
      for(const shader of shaders)gl.deleteShader(shader);
      console.warn('Atlas GPU renderer unavailable; using Canvas.',error);
      return null;
    }
  };
})();

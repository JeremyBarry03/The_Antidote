(async () => {
  'use strict';
  const status = document.querySelector('#map-status');
  const center=[-76.12,36.975],mapCanvas=document.querySelector('#coastal-map');
  const width=mapCanvas.clientWidth||window.innerWidth,height=mapCanvas.clientHeight||window.innerHeight*.65;
  const longitudeZoom=Math.log2(360*width/(512*1.16));
  const latitudeZoom=Math.log2(360*height*Math.cos(center[1]*Math.PI/180)/(512*.46));
  const HOME={center,zoom:Math.max(8,Math.min(longitudeZoom,latitudeZoom)),bearing:0,pitch:0};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let mapTheme=document.documentElement.dataset.theme==='light'?'light':'dark';
  const neutralPaints={
    dark:{land:'#111111',water:'#080808',coastline:'#c4c4c4',waterways:'#080808',label:'#b5b5b5',halo:'#080808'},
    light:{land:'#eeeeee',water:'#f7f7f7',coastline:'#3b3b3b',waterways:'#f7f7f7',label:'#4a4a4a',halo:'#f7f7f7'}
  };
  // Draw the tiny land marks directly at device-pixel resolution. A raster
  // background-pattern is filtered and cross-faded at fractional zoom levels,
  // which softens dots even when the source image itself has hard edges.
  function sharpLandDots() {
    let program, vertexArray, phase, spacing, dotSize, invert, owner;
    return {
      id:'land-dots', type:'custom', renderingMode:'2d',
      onAdd(map,gl) {
        owner=map;
        const compile=(type,source)=>{
          const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);
          if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(shader));
          return shader;
        };
        const vertex=compile(gl.VERTEX_SHADER,`#version 300 es
          void main(){
            vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));
            gl_Position=vec4(p*2.0-1.0,0.0,1.0);
          }`);
        const fragment=compile(gl.FRAGMENT_SHADER,`#version 300 es
          precision highp float;
          uniform vec2 u_phase;
          uniform float u_spacing;
          uniform float u_dot_size;
          uniform float u_invert;
          out vec4 color;
          void main(){
            vec2 cell=mod(gl_FragCoord.xy-u_phase+u_spacing*.5,u_spacing)-u_spacing*.5;
            float mark=1.0-step(u_dot_size*.5,max(abs(cell.x),abs(cell.y)));
            float gray=mix(8.0,190.0,mark)/255.0;
            color=vec4(vec3(mix(gray,1.0-gray,u_invert)),1.0);
          }`);
        program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
        gl.deleteShader(vertex);gl.deleteShader(fragment);
        if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
        vertexArray=gl.createVertexArray();
        phase=gl.getUniformLocation(program,'u_phase');spacing=gl.getUniformLocation(program,'u_spacing');dotSize=gl.getUniformLocation(program,'u_dot_size');
        invert=gl.getUniformLocation(program,'u_invert');
      },
      render(gl) {
        const canvas=owner.getCanvas(),ratio=canvas.width/canvas.clientWidth;
        const anchor=owner.project([-76.3,37]);
        const previousProgram=gl.getParameter(gl.CURRENT_PROGRAM),previousArray=gl.getParameter(gl.VERTEX_ARRAY_BINDING);
        const flags=[gl.BLEND,gl.DEPTH_TEST,gl.STENCIL_TEST,gl.CULL_FACE].map(flag=>[flag,gl.isEnabled(flag)]);
        flags.forEach(([flag])=>gl.disable(flag));
        gl.useProgram(program);gl.bindVertexArray(vertexArray);
        // Snap the grid to physical pixels, keeping the existing 8px spacing
        // and 2px square marks sharp while panning and at non-integer zoom.
        gl.uniform2f(phase,Math.round(anchor.x*ratio),Math.round(canvas.height-anchor.y*ratio));
        gl.uniform1f(spacing,Math.round(8*ratio));gl.uniform1f(dotSize,Math.max(1,Math.round(2*ratio)));
        gl.uniform1f(invert,mapTheme==='light'?1:0);
        gl.drawArrays(gl.TRIANGLES,0,3);
        gl.bindVertexArray(previousArray);gl.useProgram(previousProgram);
        flags.forEach(([flag,enabled])=>{if(enabled)gl.enable(flag);});
      },
      onRemove(map,gl){gl.deleteProgram(program);gl.deleteVertexArray(vertexArray);}
    };
  }
  try { const response = await fetch('/api/config'); const config = await response.json(); window.MAP_PREVIEW_TOKEN = config.mapbox_public_token; } catch {}
  if (!window.mapboxgl || !window.MAP_PREVIEW_TOKEN) {
    status.textContent = 'The coastal map could not load. Please reload the preview.';
    return;
  }
  const map = new mapboxgl.Map({container:'coastal-map',accessToken:window.MAP_PREVIEW_TOKEN,
    style:{version:8,glyphs:'mapbox://fonts/mapbox/{fontstack}/{range}.pbf',sources:{coast:{type:'vector',url:'mapbox://mapbox.mapbox-streets-v8'}},layers:[
      {id:'land',type:'background',paint:{'background-color':neutralPaints[mapTheme].land}},
      // Keep water in the ordered translucent pass, above the custom dot layer.
      // This rounds to opaque black in the framebuffer without leaking marks.
      {id:'water',type:'fill',source:'coast','source-layer':'water',paint:{'fill-color':neutralPaints[mapTheme].water,'fill-opacity':.9999,'fill-antialias':true}},
      {id:'coastline',type:'line',source:'coast','source-layer':'water',paint:{'line-color':neutralPaints[mapTheme].coastline,'line-width':.9,'line-opacity':.8}},
      {id:'waterways',type:'line',source:'coast','source-layer':'waterway',minzoom:11,paint:{'line-color':neutralPaints[mapTheme].waterways,'line-width':['interpolate',['linear'],['zoom'],11,1,15,5]}}
    ]},...HOME,minZoom:8,maxZoom:15,dragRotate:false,pitchWithRotate:false,touchPitch:false,attributionControl:true});
  map.touchZoomRotate.disableRotation();
  let ready = false;
  // Repaint only the basemap's neutral layers. Data layer colors remain exact.
  const setTheme=theme=>{
    mapTheme=theme==='light'?'light':'dark';
    if(ready){
      const palette=neutralPaints[mapTheme];
      for(const [layer,property,color]of[
        ['land','background-color',palette.land],['water','fill-color',palette.water],
        ['coastline','line-color',palette.coastline],['waterways','line-color',palette.waterways],
        ['place-labels','text-color',palette.label],['place-labels','text-halo-color',palette.halo]
      ])if(map.getLayer(layer)){
        map.setPaintProperty(layer,property+'-transition',{duration:0,delay:0});
        map.setPaintProperty(layer,property,color);
      }
    }
    map.triggerRepaint();
  };
  const timer = setTimeout(() => { if (!ready) status.textContent = 'Coastal geography is taking longer to load. Check your connection and reload.'; },18000);
  map.on('load', () => {
    map.addLayer(sharpLandDots(),'water');
    map.addSource('places',{type:'geojson',data:{type:'FeatureCollection',features:[
      ['Norfolk',-76.2859,36.8508],['Portsmouth',-76.2983,36.8354],['Newport News',-76.4730,36.9788],
      ['Hampton',-76.3452,37.0299],['Virginia Beach',-75.9780,36.8529],['Chesapeake',-76.2875,36.7682],
      ['Cape Charles',-76.0060,37.2671]
    ].map(([name,longitude,latitude])=>({type:'Feature',properties:{name},geometry:{type:'Point',coordinates:[longitude,latitude]}}))}});
    map.addLayer({id:'place-labels',type:'symbol',source:'places',layout:{'text-field':['get','name'],'text-font':['DIN Pro Regular'],'text-size':12,'text-anchor':'center','text-allow-overlap':false},paint:{'text-color':neutralPaints[mapTheme].label,'text-halo-color':neutralPaints[mapTheme].halo,'text-halo-width':3}});
    ready=true;setTheme(mapTheme);clearTimeout(timer);status.hidden=true;
    document.querySelector('#coastal-map').dataset.ready='true';
    window.dispatchEvent(new Event('coastal-ready'));
  });
  map.on('error', () => { if(!ready) status.textContent='The coastal map could not load. Check your connection and reload.'; });
  const duration=()=>reduced.matches?0:700;
  document.querySelector('#recenter').addEventListener('click',()=>{
    if (window.replayPreview) { window.replayPreview.fit(); return; }
    map.easeTo({...HOME,duration:duration()});document.querySelector('#announcement').textContent='Map recentered on Hampton Roads.';
  });
  document.querySelector('#zoom-in').addEventListener('click',()=>map.zoomIn({duration:reduced.matches?0:250}));
  document.querySelector('#zoom-out').addEventListener('click',()=>map.zoomOut({duration:reduced.matches?0:250}));
  const report=()=>{document.querySelector('#map-scale').textContent=`${map.getCenter().lat.toFixed(3)}° N · ${Math.abs(map.getCenter().lng).toFixed(3)}° W`;};
  map.on('move',report);report();
  window.coastalPreview={map,setTheme,getState:()=>({ready,theme:mapTheme,zoom:map.getZoom(),center:map.getCenter().toArray(),dotPattern:map.getLayer('land-dots')?.id})};
})();

// Month analysis is independent of the replay clock and selected map model.
import {setChartStatus} from './chart-status.mjs';
export const modelNames={A:'Poly',B:'XGBoost',C:'Antidote'};
const models=Object.keys(modelNames),namespace='http://www.w3.org/2000/svg';
const numeric=value=>typeof value==='number'&&Number.isFinite(value);
const minute=value=>numeric(value)?`${value>0?'+':''}${value.toFixed(1)}`:'—';
const absolute=value=>numeric(value)?value.toFixed(1):'—';
export function errorDomain(days,visible=models){
 const values=days.flatMap(day=>[...visible].map(model=>day.models[model]?.mean_error)).filter(numeric);
 const low=Math.min(0,...values),high=Math.max(0,...values),range=high-low;
 const min=range?(low<0?low-range*.04:0):-1,max=range?(high>0?high+range*.04:0):1;
 const target=(max-min)/4,power=10**Math.floor(Math.log10(target));
 const step=[1,2,2.5,5,10].find(value=>value*power>=target)*power;
 const ticks=[];for(let value=Math.ceil(min/step)*step;value<=max+step*1e-8;value+=step)ticks.push(Number(value.toPrecision(8)));
 return {min,max,ticks};
}
export function linePath(days,model,x,y){
 let path='',connected=false;
 for(const day of days){const value=day.models[model]?.mean_error;
  if(!numeric(value)){connected=false;continue;}
  path+=`${connected?'L':'M'}${x(day.day).toFixed(2)},${y(value).toFixed(2)}`;connected=true;
 }
 return path;
}
function svgNode(tag,attributes={},text){
 const node=document.createElementNS(namespace,tag);
 for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
 if(text!==undefined)node.textContent=String(text);
 return node;
}
function cell(row,tag,text,className){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;row.append(node);return node;}
export function createMonthlyChart(root,{fetcher=fetch,debounce=700,pollDelay=1300,onResult=()=>{},onState=()=>{}}={}){
 const svg=root.querySelector('.monthly-svg'),plot=root.querySelector('.monthly-plot');
 const inspector=root.querySelector('.monthly-inspector'),loading=root.querySelector('.monthly-loading');
 const retry=loading.querySelector('button'),view=root.ownerDocument.defaultView;
 const scenario=root.querySelector('.monthly-scenario'),coverage=root.querySelector('.monthly-coverage');
 const method=root.querySelector('.monthly-method-copy'),legend=root.querySelector('.monthly-legend');
 const shown=new Set(models),client=globalThis.crypto?.randomUUID?.()??`chart-${Date.now()}-${Math.random()}`;
 let result=null,settings={},controls=[],generation=0,timer,controller,geometry,selected=-1,lastKey=null,destroyed=false;
 let animationFrame=null,renderedDomain=null,renderedTicks=new Map(),scene=null;
 const reducedMotion=view?.matchMedia?.('(prefers-reduced-motion: reduce)');
 for(const model of models){const button=document.createElement('button');button.type='button';button.textContent=modelNames[model];button.style.setProperty('--series-color',`var(--model-${model})`);button.setAttribute('aria-pressed','true');button.setAttribute('aria-label',`Show ${modelNames[model]} line`);button.addEventListener('click',()=>{shown.has(model)?shown.delete(model):shown.add(model);button.setAttribute('aria-pressed',String(shown.has(model)));draw({animate:true});});legend.append(button);}
 function describeScenario(){
  const active=Object.entries(settings).filter(([,value])=>value>0).map(([key,value])=>{
   const control=controls.find(item=>item.id===key);return `${control?.label??key}: ${value}${control?.unit==='min'?' min':'%'}`;
  });
  scenario.dataset.active=String(active.length>0);
  scenario.textContent=active.length?`From Mar 15 · ${active.join(' · ')}`:'Poisoning off · all March uses clean data. Move a slider to apply an attack from Mar 15.';
 }
 function hideInspection(){selected=-1;inspector.hidden=true;svg.querySelector('.chart-selection')?.remove();}
 function stopAnimation(){if(animationFrame!==null)view.cancelAnimationFrame(animationFrame);animationFrame=null;delete svg.dataset.rescaling;}
 function draw({animate=false}={}){
  hideInspection();stopAnimation();scene=null;
  if(!result){svg.replaceChildren();geometry=null;renderedDomain=null;renderedTicks.clear();return;}
  const target=errorDomain(result.days,shown),from=renderedDomain,previousTicks=new Map(renderedTicks);
  svg.dataset.yMin=String(target.min);svg.dataset.yMax=String(target.max);
  const targetTicks=new Map(target.ticks.map(value=>[value,1]));
  if(!animate||!shown.size||!from||reducedMotion?.matches||!view?.requestAnimationFrame||(from.min===target.min&&from.max===target.max)){
   paint(target,targetTicks);return;
  }
  const start=view.performance.now(),duration=360;
  svg.dataset.rescaling='true';
  function frame(now){
   const progress=Math.min(1,Math.max(0,(now-start)/duration));
   const eased=progress<.5?4*progress**3:1-(-2*progress+2)**3/2;
   const domain={min:from.min+(target.min-from.min)*eased,max:from.max+(target.max-from.max)*eased};
   const ticks=new Map([...new Set([...previousTicks.keys(),...target.ticks])].map(value=>[value,(previousTicks.get(value)??0)*(1-eased)+(targetTicks.get(value)??0)*eased]));
   paint(domain,ticks);
   if(progress<1)animationFrame=view.requestAnimationFrame(frame);
   else{animationFrame=null;delete svg.dataset.rescaling;paint(target,targetTicks);for(const [value,mark] of scene.ticks)if(!targetTicks.has(value)){mark.group.remove();scene.ticks.delete(value);}}
  }
  // Keep the current geometry on the click frame, including during rapid toggles.
  paint(from,new Map([...previousTicks,...target.ticks.filter(value=>!previousTicks.has(value)).map(value=>[value,0])]));animationFrame=view.requestAnimationFrame(frame);
 }
 function buildScene(tickValues){
  svg.replaceChildren();
  const width=Math.max(230,plot.clientWidth),height=plot.clientHeight,left=40,right=13,top=26,bottom=30,end=result.end-86400;
  const x=time=>left+(time-result.start)/(end-result.start)*(width-left-right);
  const next={x,width,height,left,right,top,bottom,end,ticks:new Map(),paths:[],dots:[]};
  svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  svg.append(svgNode('title',{},'March 2024 daily ETA minus actual arrival, in minutes'));
  svg.append(svgNode('desc',{},'Visible model lines determine the Y axis, with a small margin and zero retained as the ideal reference. Negative errors predict early arrival; positive errors predict late arrival. Poisoning begins March 15 when sliders are active.'));
  if(result.poisoning_active)svg.append(svgNode('rect',{x:x(result.cutover),y:top,width:width-right-x(result.cutover),height:height-top-bottom,class:'chart-shade'}));
  for(const value of tickValues){
   const group=svgNode('g'),line=svgNode('line',{x1:left,x2:width-right,class:value===0?'chart-zero':'chart-grid'});
   const label=svgNode('text',{x:left-8,'text-anchor':'end'},`${value>0?'+':''}${value}`);
   group.append(line,label);svg.append(group);next.ticks.set(value,{group,line,label});
  }
  svg.append(svgNode('line',{x1:x(result.cutover),x2:x(result.cutover),y1:top-6,y2:height-bottom,class:'chart-cutover'}));
  svg.append(svgNode('text',{x:x(result.cutover)+5,y:12,class:'chart-axis-label'},result.poisoning_active?'15 Mar · poisoning':'15 Mar · boundary (off)'));
  for(const day of [1,8,15,22,31]){const time=result.start+(day-1)*86400;svg.append(svgNode('text',{x:x(time),y:height-9,'text-anchor':'middle'},`${String(day).padStart(2,'0')} Mar`));}
  const clipId=`monthly-clip-${client}`,defs=svgNode('defs'),clip=svgNode('clipPath',{id:clipId});
  clip.append(svgNode('rect',{x:left-3,y:top-3,width:width-left-right+6,height:height-top-bottom+6}));defs.append(clip);svg.append(defs);
  const series=svgNode('g',{'clip-path':`url(#${clipId})`});svg.append(series);
  for(const model of models)if(shown.has(model)){
   const path=svgNode('path',{class:'chart-line','data-series':model,style:`--series-color:var(--model-${model})`});series.append(path);next.paths.push({path,model});
   // A lone valid day stays visible even if adjacent days have no coverage.
   for(const day of result.days)if(numeric(day.models[model]?.mean_error)){
    const value=day.models[model].mean_error,dot=svgNode('circle',{cx:x(day.day),r:1.7,class:'chart-dot',style:`--series-color:var(--model-${model})`});series.append(dot);next.dots.push({dot,value});
   }
  }
  if(!shown.size)svg.append(svgNode('text',{x:(width+left-right)/2,y:height/2,'text-anchor':'middle'},'Select a model above to show its predictions'));
  return next;
 }
 function paint(domain,ticks){
  // Reuse SVG marks through the transition instead of rebuilding the chart on
  // every frame. Curves, dots and gridlines share one interpolated projection.
  if(!scene)scene=buildScene(ticks.keys());
  renderedDomain=domain;renderedTicks=ticks;
  const {x,width,height,left,right,top,bottom,end}=scene;
  const y=value=>top+(domain.max-value)/(domain.max-domain.min)*(height-top-bottom);
  geometry={x,y,left,right,width,end};
  for(const [value,mark] of scene.ticks){
   const position=y(value),opacity=ticks.get(value)??0,hidden=opacity<.001||position<top-1||position>height-bottom+1;
   mark.group.setAttribute('opacity',opacity);mark.group.setAttribute('visibility',hidden?'hidden':'visible');mark.group.setAttribute('aria-hidden',String(hidden));
   mark.line.setAttribute('y1',position);mark.line.setAttribute('y2',position);mark.label.setAttribute('y',position+3);
  }
  for(const {path,model} of scene.paths)path.setAttribute('d',linePath(result.days,model,x,y));
  for(const {dot,value} of scene.dots)dot.setAttribute('cy',y(value));
  if(selected>=0)inspect(selected);
 }
 function inspect(index){
  if(!result||!geometry)return;selected=Math.max(0,Math.min(result.days.length-1,index));
  const day=result.days[selected],date=new Date(day.day*1000).toLocaleDateString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short'});
  inspector.replaceChildren();const title=document.createElement('strong');title.textContent=`${date} · ${day.poisoned?'poisoned inputs':'clean inputs'}`;inspector.append(title);
  const table=document.createElement('table'),header=table.createTHead().insertRow();
  for(const label of ['Model','Error','MAE',...(day.poisoned?['Clean error']:[])])cell(header,'th',label);
  const body=table.createTBody();
  for(const model of models){if(!shown.has(model))continue;const values=day.models[model],row=body.insertRow();const name=cell(row,'td',modelNames[model],'series-name');name.style.setProperty('--series-color',`var(--model-${model})`);cell(row,'td',minute(values?.mean_error));cell(row,'td',absolute(values?.mae));if(day.poisoned)cell(row,'td',minute(values?.clean_mean_error));}
  inspector.append(table);
  const note=document.createElement('p');note.textContent=`Minutes · ${day.matched_decisions}/${day.scheduled_decisions} matched checkpoints · ${day.approaches} approaches. `+(day.matched_decisions?'Early − / late +. MAE = average absolute error.':'No common predictions; lines have a gap.');inspector.append(note);
  const unavailable=models.filter(model=>day.models[model]?.unavailable_decisions>0).map(model=>`${modelNames[model]}: ${day.models[model].unavailable_decisions}`);
  if(unavailable.length){const p=document.createElement('p');p.textContent=`Unavailable predictions: ${unavailable.join(' · ')}.`;inspector.append(p);}
  inspector.hidden=false;const {x,y,width}=geometry;
  inspector.style.left=`${x(day.day)>width/2?4:Math.max(4,width-Math.min(290,width-8)-4)}px`;
  svg.querySelector('.chart-selection')?.remove();const group=svgNode('g',{class:'chart-selection'});
  group.append(svgNode('line',{x1:x(day.day),x2:x(day.day),y1:24,y2:plot.clientHeight-30,class:'chart-guide'}));
  for(const model of models)if(shown.has(model)&&numeric(day.models[model]?.mean_error))group.append(svgNode('circle',{cx:x(day.day),cy:y(day.models[model].mean_error),r:3,class:'chart-dot',style:`--series-color:var(--model-${model})`}));
  svg.append(group);
 }
 plot.addEventListener('pointermove',event=>{if(!result||!geometry)return;const local=event.clientX-plot.getBoundingClientRect().left;const {left,right,width}=geometry;inspect(Math.round((local-left)/(width-left-right)*(result.days.length-1)));});
 plot.addEventListener('pointerleave',()=>{if(document.activeElement!==plot)hideInspection();});
 plot.addEventListener('focus',()=>inspect(selected<0?14:selected));plot.addEventListener('blur',hideInspection);
 plot.addEventListener('keydown',event=>{if(!result)return;const offsets={ArrowLeft:-1,ArrowRight:1};if(event.key in offsets){event.preventDefault();inspect((selected<0?14:selected)+offsets[event.key]);}else if(event.key==='Home'||event.key==='End'){event.preventDefault();inspect(event.key==='Home'?0:result.days.length-1);}else if(event.key==='Escape'){hideInspection();}});
 async function calculate(version){
  controller=new AbortController();const signal=controller.signal;retry.hidden=true;loading.hidden=false;root.setAttribute('aria-busy','true');setChartStatus(loading,{status:'loading',message:'Preparing March model comparison…'});
  try{
   let url='/api/fleet/monthly?'+new URLSearchParams({poisoning:JSON.stringify(settings),client});
   while(version===generation&&!destroyed){
    const response=await fetcher(url,{signal}),data=await response.json();if(version!==generation||destroyed)return;
    if(!response.ok)throw Error(data.error||'Could not load monthly predictions.');
    if(data.status==='ready'){
     onResult(data);result=data;draw();loading.hidden=true;root.setAttribute('aria-busy','false');
     coverage.textContent=`${data.matched_decisions.toLocaleString()}/${data.scheduled_decisions.toLocaleString()} checkpoints`;
     method.textContent=`${data.methodology} ${data.approaches} approaches · ${data.vessels} vessels. ${data.source} ${data.caveat} ${data.affected_reports.toLocaleString()} reports modified; deterministic seed ${data.seed}.`;
     return;
    }
    if(data.status==='error')throw Error(data.error||'Monthly inference failed.');
    if(data.status==='superseded')throw Error('This scenario was replaced. Retry to calculate it again.');
    const progress={status:'loading',completed:data.completed,total:data.total,message:`${data.phase} · ${data.completed.toLocaleString()} / ${data.total.toLocaleString()} checkpoints${data.status==='queued'?' · queued':''}`};
    setChartStatus(loading,progress);onState(progress);
    url='/api/fleet/monthly?'+new URLSearchParams({job:data.job_id});
    await new Promise(resolve=>setTimeout(resolve,pollDelay));
   }
  }catch(error){if(version!==generation||destroyed||error.name==='AbortError')return;setChartStatus(loading,{status:'error',message:error.message});retry.hidden=false;root.setAttribute('aria-busy','false');onState({status:'error',message:error.message});}
 }
 function schedule(immediate=false){
  generation++;controller?.abort();clearTimeout(timer);result=null;draw();root.setAttribute('aria-busy','true');loading.hidden=false;retry.hidden=true;const progress={status:'loading',message:'Updating month from the poisoning sliders…'};setChartStatus(loading,progress);coverage.textContent='';method.textContent='Preparing all supported March checkpoints for the current slider settings. Daily means give each vessel approach equal weight; the completed result will include coverage and provenance.';
  onState(progress);
  timer=setTimeout(()=>void calculate(generation),immediate?0:debounce);
 }
 retry.addEventListener('click',()=>schedule(true));const resizeObserver=new ResizeObserver(()=>draw());resizeObserver.observe(plot);
 const motionChanged=()=>{if(reducedMotion.matches)draw();};reducedMotion?.addEventListener('change',motionChanged);
 return {
  update(values,definitions=[]){
   const key=JSON.stringify(Object.entries(values).sort(([a],[b])=>a.localeCompare(b)));if(key===lastKey)return;const first=lastKey===null;lastKey=key;settings={...values};controls=definitions??[];describeScenario();schedule(first);
  },
  refresh(){schedule(true);},
  destroy(){destroyed=true;generation++;controller?.abort();clearTimeout(timer);stopAnimation();resizeObserver.disconnect();reducedMotion?.removeEventListener('change',motionChanged);},
 };
}

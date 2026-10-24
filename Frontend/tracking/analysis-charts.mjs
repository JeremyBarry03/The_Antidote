// The arrival and delay views share the first graph's drawing and interaction style.
import {modelNames} from './monthly-chart.mjs';
import {setChartStatus} from './chart-status.mjs';
const models=Object.keys(modelNames),ns='http://www.w3.org/2000/svg';
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const format=value=>finite(value)?value.toFixed(1):'—';
const node=(tag,attributes={},text)=>{const element=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));if(text!==undefined)element.textContent=text;return element;};
const cell=(row,tag,text)=>{const element=document.createElement(tag);element.textContent=text;row.append(element);return element;};

export function maeExtent(samples){
 const largest=Math.max(5,...samples.flatMap(sample=>models.map(model=>sample.models[model]?.mae)).filter(finite));
 const power=10**Math.floor(Math.log10(largest)),step=[1,2,2.5,5,10].find(value=>value*power>=largest/4)*power;
 return Math.ceil(largest/step)*step;
}
export function maePath(samples,model,x,y){
 let path='',connected=false;
 for(const sample of samples){const value=sample.models[model]?.mae;if(!finite(value)){connected=false;continue;}
  path+=`${connected?'L':'M'}${x(sample.minute).toFixed(2)},${y(value).toFixed(2)}`;connected=true;
 }return path;
}

export function createAnalysisChart(root,{kind,onRetry=()=>{}}){
 const convergence=kind==='convergence',name=convergence?'arrival convergence':'poisoning stress';
 const plot=root.querySelector('.monthly-plot'),svg=root.querySelector('.monthly-svg'),inspector=root.querySelector('.monthly-inspector');
 const loading=root.querySelector('.monthly-loading'),retry=loading.querySelector('button');
 const legend=root.querySelector('.monthly-legend'),shown=new Set(models);
 let result=null,context={},geometry,selected=-1;
 for(const model of models){const button=document.createElement('button');button.type='button';button.textContent=modelNames[model];button.style.setProperty('--series-color',`var(--model-${model})`);button.setAttribute('aria-pressed','true');button.setAttribute('aria-label',`Show ${modelNames[model]} ${name}`);button.addEventListener('click',()=>{shown.has(model)?shown.delete(model):shown.add(model);button.setAttribute('aria-pressed',String(shown.has(model)));draw();});legend.append(button);}
 function hide(){selected=-1;inspector.hidden=true;svg.querySelector('.analysis-selection')?.remove();}
 function draw(){
  hide();svg.replaceChildren();if(!result)return;
  const width=Math.max(230,plot.clientWidth),height=plot.clientHeight,left=40,right=15,top=24,bottom=42;
  const extent=maeExtent(result.samples),maximum=convergence?60:15;
  const x=minute=>left+(convergence?(maximum-minute)/maximum:minute/maximum)*(width-left-right);
  const y=value=>top+(extent-value)/extent*(height-top-bottom);
  geometry={x,y,width,left,right,maximum};svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  svg.append(node('title',{},convergence?'Average absolute ETA error in the final hour before crossing':'Average absolute ETA error under increasing reporting delay'));
  svg.append(node('desc',{},context.smoothed?'Smoothed model results. Extra points interpolate between measured checkpoints.':convergence?'Three models aligned by time before crossing; lower error is better. Missing bins are gaps and the contributing approaches can change.':'Three models at zero, two, five, ten and fifteen minutes of reporting delay. Identical supported checkpoints across all models and delay levels; lower error is better.'));
  for(let tick=0;tick<=4;tick++){const value=extent*tick/4;svg.append(node('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:tick===0?'chart-zero':'chart-grid'}));svg.append(node('text',{x:left-8,y:y(value)+3,'text-anchor':'end'},Number(value.toFixed(2))));}
  const ticks=convergence?[60,45,30,15,0]:(width<340?[0,5,10,15]:[0,2,5,10,15]);
  for(const minute of ticks)svg.append(node('text',{x:x(minute),y:height-24,'text-anchor':'middle'},minute));
  svg.append(node('text',{x:left,y:11,class:'chart-axis-label'},'Average absolute error (min)'));
  svg.append(node('text',{x:(left+width-right)/2,y:height-5,'text-anchor':'middle',class:'chart-axis-label'},convergence?'Minutes before recorded crossing':'Report delivery delay (min)'));
  if(convergence){svg.append(node('line',{x1:x(0),x2:x(0),y1:top,y2:height-bottom,class:'chart-cutover'}));}
  for(const model of models)if(shown.has(model)){
   const style=`--series-color:var(--model-${model})`;
   svg.append(node('path',{d:maePath(result.samples,model,x,y),class:`chart-line ${kind}-line`,'data-series':model,style}));
   for(const sample of result.samples)if(!sample.interpolated&&finite(sample.models[model]?.mae))svg.append(node('circle',{cx:x(sample.minute),cy:y(sample.models[model].mae),r:2,class:'chart-dot',style}));
  }
 }
 function inspect(index){
  if(!result||!geometry||!result.samples.length)return;
  selected=Math.max(0,Math.min(result.samples.length-1,index));const sample=result.samples[selected];
  const from=Math.round(finite(sample.from_minutes)?sample.from_minutes:sample.minute);
  const to=Math.round(finite(sample.to_minutes)?sample.to_minutes:sample.minute);
  inspector.replaceChildren();const title=document.createElement('strong');title.textContent=convergence?`${from===to?from:`${from}–${to}`} min before crossing`:`${Math.round(sample.minute)}-minute report delay`;inspector.append(title);
  const showClean=convergence&&context.poisoning_active;
  const table=document.createElement('table'),header=table.createTHead().insertRow();
  for(const label of ['Model','MAE (min)',...(showClean?['Clean MAE']:[])])cell(header,'th',label);
  const body=table.createTBody();
  for(const model of models)if(shown.has(model)){
   const row=body.insertRow(),label=cell(row,'td',modelNames[model]);label.className='series-name';label.style.setProperty('--series-color',`var(--model-${model})`);
   cell(row,'td',format(sample.models[model]?.mae));if(showClean)cell(row,'td',format(sample.models[model]?.clean_mae));
  }
  inspector.append(table);
  if(!context.simulation){const note=document.createElement('p');note.textContent=`${sample.matched_decisions}/${sample.scheduled_decisions} matched checkpoints · ${sample.approaches} approaches. Lower is better.`;if(sample.interpolated)note.textContent='Interpolated between measured convergence checkpoints, not an additional observed forecast.';inspector.append(note);}
  if(!convergence){const unavailable=document.createElement('p');unavailable.textContent='Unavailable at this delay: '+models.filter(model=>shown.has(model)).map(model=>`${modelNames[model]} ${sample.models[model].unavailable_decisions}`).join(' · ');inspector.append(unavailable);}
  if(!context.simulation&&!sample.matched_decisions){const empty=document.createElement('p');empty.textContent='No common supported forecasts in this bin; this is a gap, not zero error.';inspector.append(empty);}
  const {x,y,width}=geometry;inspector.style.left=`${x(sample.minute)>width/2?4:Math.max(4,width-Math.min(290,width-8)-4)}px`;inspector.hidden=false;
  svg.querySelector('.analysis-selection')?.remove();const group=node('g',{class:'analysis-selection'});group.append(node('line',{x1:x(sample.minute),x2:x(sample.minute),y1:24,y2:plot.clientHeight-42,class:'chart-guide'}));
  for(const model of models)if(shown.has(model)&&finite(sample.models[model]?.mae))group.append(node('circle',{cx:x(sample.minute),cy:y(sample.models[model].mae),r:3.5,class:'chart-dot',style:`--series-color:var(--model-${model})`}));svg.append(group);
 }
 plot.addEventListener('pointermove',event=>{if(!result||!geometry)return;const local=event.clientX-plot.getBoundingClientRect().left;inspect(result.samples.reduce((best,sample,index)=>Math.abs(geometry.x(sample.minute)-local)<Math.abs(geometry.x(result.samples[best].minute)-local)?index:best,0));});
 plot.addEventListener('pointerleave',()=>{if(document.activeElement!==plot)hide();});plot.addEventListener('pointerdown',event=>{if(event.pointerType!=='mouse')plot.focus();});
 plot.addEventListener('focus',()=>inspect(selected<0?0:selected));plot.addEventListener('blur',hide);
 plot.addEventListener('keydown',event=>{if(!result)return;const moves={ArrowLeft:-1,ArrowRight:1};if(event.key in moves){event.preventDefault();inspect((selected<0?0:selected)+moves[event.key]);}else if(event.key==='Home'||event.key==='End'){event.preventDefault();inspect(event.key==='Home'?0:result.samples.length-1);}else if(event.key==='Escape')hide();});
 retry.addEventListener('click',onRetry);const observer=new ResizeObserver(draw);observer.observe(plot);
 return {
  setStatus(state){result=null;draw();loading.hidden=false;retry.hidden=state.status!=='error';root.setAttribute('aria-busy',String(state.status==='loading'));setChartStatus(loading,state);},
  setResult(data){
   const next=convergence?data.convergence:data;
   if(!next){this.setStatus({status:'error',message:'The updated analysis is not available yet. Retry after restarting the replay server.'});return;}
   result=next;context=data;draw();retry.hidden=true;root.setAttribute('aria-busy','false');
   const available=result.samples.some(sample=>models.some(model=>finite(sample.models[model]?.mae)));
   loading.hidden=available;setChartStatus(loading,{status:'empty',message:'No common supported predictions are available for this comparison.'});
  },
  destroy(){observer.disconnect();},
 };
}

// Compare forecast revisions across March approaches, aligned at their first ETA.
import {modelNames} from './monthly-chart.mjs';
import {setChartStatus} from './chart-status.mjs';
const models=Object.keys(modelNames),ns='http://www.w3.org/2000/svg';
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const signed=value=>finite(value)?`${value>0?'+':''}${value.toFixed(1)}`:'—';
export function sequenceExtent(samples){
 const largest=Math.max(5,...samples.flatMap(sample=>models.map(model=>sample.models[model]?.mean_eta_shift)).filter(finite).map(Math.abs));
 const power=10**Math.floor(Math.log10(largest)),step=[1,2,2.5,5,10].find(value=>value*power>=largest/2)*power;
 return Math.ceil(largest/step)*step;
}
export function sequencePath(samples,model,x,y){
 let path='',connected=false;
 for(const sample of samples){const value=sample.models[model]?.mean_eta_shift;
  if(!finite(value)){connected=false;continue;}
  path+=`${connected?'L':'M'}${x(sample.minute).toFixed(2)},${y(value).toFixed(2)}`;connected=true;
 }return path;
}
const node=(tag,attributes={},text)=>{const result=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attributes))result.setAttribute(key,String(value));if(text!==undefined)result.textContent=text;return result;};
const addCell=(row,tag,text)=>{const cell=document.createElement(tag);cell.textContent=text;row.append(cell);return cell;};
export function createEtaSequence(root,{onRetry=()=>{}}={}){
 const plot=root.querySelector('.monthly-plot'),svg=root.querySelector('.monthly-svg'),inspector=root.querySelector('.monthly-inspector');
 const loading=root.querySelector('.monthly-loading'),retry=loading.querySelector('button');
 const coverage=root.querySelector('.monthly-coverage'),method=root.querySelector('.monthly-method-copy'),description=root.querySelector('.window-description');
 const legend=root.querySelector('.monthly-legend'),shown=new Set(models);
 let result=null,selected=-1,geometry;
 for(const model of models){const button=document.createElement('button');button.type='button';button.textContent=modelNames[model];button.style.setProperty('--series-color',`var(--model-${model})`);button.setAttribute('aria-pressed','true');button.setAttribute('aria-label',`Show ${modelNames[model]} sequence`);button.addEventListener('click',()=>{shown.has(model)?shown.delete(model):shown.add(model);button.setAttribute('aria-pressed',String(shown.has(model)));draw();});legend.append(button);}
 function hide(){selected=-1;inspector.hidden=true;svg.querySelector('.sequence-selection')?.remove();}
 function draw(){
  hide();svg.replaceChildren();if(!result)return;
  const samples=result.sequence.samples,width=Math.max(230,plot.clientWidth),height=plot.clientHeight,left=40,right=13,top=26,bottom=30;
  const extent=sequenceExtent(samples),x=minute=>left+minute/30*(width-left-right),y=value=>top+(extent-value)/(2*extent)*(height-top-bottom);
  geometry={x,y,width,left,right};svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  svg.append(node('title',{},'Average change in predicted arrival time over 30 minutes'));
  svg.append(node('desc',{},'March approaches aligned at minute zero. Positive means a later arrival prediction; negative means an earlier arrival prediction. Zero means no revision.'));
  for(const value of [-extent,-extent/2,0,extent/2,extent]){
   svg.append(node('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:value===0?'chart-zero':'chart-grid'}));
   svg.append(node('text',{x:left-8,y:y(value)+3,'text-anchor':'end'},`${value>0?'+':''}${value}`));
  }
  for(const minute of [0,5,10,15,20,25,30])svg.append(node('text',{x:x(minute),y:height-9,'text-anchor':'middle'},minute));
  svg.append(node('text',{x:left,y:12,class:'chart-axis-label'},'Elapsed since first prediction (min)'));
  for(const model of models)if(shown.has(model)){
   const style=`--series-color:var(--model-${model})`;
   svg.append(node('path',{d:sequencePath(samples,model,x,y),class:'chart-line sequence-line','data-series':model,style}));
   for(const sample of samples)if(finite(sample.models[model]?.mean_eta_shift))svg.append(node('circle',{cx:x(sample.minute),cy:y(sample.models[model].mean_eta_shift),r:2,class:'chart-dot',style}));
  }
 }
 function inspect(index){
  if(!result||!geometry)return;
  const samples=result.sequence.samples;selected=Math.max(0,Math.min(samples.length-1,index));const sample=samples[selected];
  inspector.replaceChildren();const title=document.createElement('strong');title.textContent=`Minute ${sample.minute} · average ETA revision`;inspector.append(title);
  const table=document.createElement('table'),header=table.createTHead().insertRow();
  for(const label of ['Model','Shift (min)',...(result.poisoning_active?['Clean shift']:[])])addCell(header,'th',label);
  const body=table.createTBody();
  for(const model of models){if(!shown.has(model))continue;const row=body.insertRow(),label=addCell(row,'td',modelNames[model]);label.className='series-name';label.style.setProperty('--series-color',`var(--model-${model})`);addCell(row,'td',signed(sample.models[model]?.mean_eta_shift));if(result.poisoning_active)addCell(row,'td',signed(sample.models[model]?.clean_mean_eta_shift));}
  inspector.append(table);
  const note=document.createElement('p');note.textContent=`${sample.matched_instances}/${sample.scheduled_instances} matched approach instances · ${sample.vessels} vessels. + later arrival / − earlier arrival.`;inspector.append(note);
  if(!sample.matched_instances){const empty=document.createElement('p');empty.textContent='No common forecasts and initial predictions are available here; this is a gap, not zero.';inspector.append(empty);}
  const {x,y,width}=geometry;inspector.style.left=`${x(sample.minute)>width/2?4:Math.max(4,width-Math.min(290,width-8)-4)}px`;inspector.hidden=false;
  svg.querySelector('.sequence-selection')?.remove();const group=node('g',{class:'sequence-selection'});group.append(node('line',{x1:x(sample.minute),x2:x(sample.minute),y1:24,y2:plot.clientHeight-30,class:'chart-guide'}));
  for(const model of models)if(shown.has(model)&&finite(sample.models[model]?.mean_eta_shift))group.append(node('circle',{cx:x(sample.minute),cy:y(sample.models[model].mean_eta_shift),r:3.5,class:'chart-dot',style:`--series-color:var(--model-${model})`}));svg.append(group);
 }
 plot.addEventListener('pointermove',event=>{if(!result||!geometry)return;const {left,right,width}=geometry,minute=(event.clientX-plot.getBoundingClientRect().left-left)/(width-left-right)*30;const nearest=result.sequence.samples.reduce((best,sample,index)=>Math.abs(sample.minute-minute)<Math.abs(result.sequence.samples[best].minute-minute)?index:best,0);inspect(nearest);});
 plot.addEventListener('pointerleave',()=>{if(document.activeElement!==plot)hide();});plot.addEventListener('focus',()=>inspect(selected<0?0:selected));plot.addEventListener('blur',hide);
 plot.addEventListener('keydown',event=>{if(!result)return;const moves={ArrowLeft:-1,ArrowRight:1};if(event.key in moves){event.preventDefault();inspect((selected<0?0:selected)+moves[event.key]);}else if(event.key==='Home'||event.key==='End'){event.preventDefault();inspect(event.key==='Home'?0:result.sequence.samples.length-1);}else if(event.key==='Escape')hide();});
 retry.addEventListener('click',onRetry);const observer=new ResizeObserver(draw);observer.observe(plot);
 return {
  setStatus(state){
   if(state.status==='loading'){if(result){result=null;draw();}root.setAttribute('aria-busy','true');loading.hidden=false;retry.hidden=true;setChartStatus(loading,state);coverage.textContent='';description.textContent='0 = unchanged ETA · + later / − earlier';}
   else if(state.status==='error'){root.setAttribute('aria-busy','false');loading.hidden=false;setChartStatus(loading,state);retry.hidden=false;}
  },
  setResult(data){
   if(!data.sequence){root.setAttribute('aria-busy','false');loading.hidden=false;setChartStatus(loading,{status:'error',message:'The backend has not supplied the 30-minute sequence aggregation. Retry after updating the API.'});retry.hidden=false;return;}
   result=data;draw();loading.hidden=true;retry.hidden=true;root.setAttribute('aria-busy','false');
   coverage.textContent=`${data.sequence.matched_instances}/${data.sequence.approaches} approaches`;
   description.dataset.active=String(data.poisoning_active);description.textContent='0 = unchanged ETA · + later / − earlier'+(data.poisoning_active?' · sliders apply from Mar 15':' · clean March data');
   method.textContent=`${data.sequence.methodology} ${data.sequence.coverage_note} ${data.sequence.approaches} approaches across ${data.sequence.vessels} vessels. ${data.source} ${data.caveat}`;
  },
  destroy(){observer.disconnect();},
 };
}

// Counterfactual accuracy and fixed-cohort stability share the reviewed monthly job.
import {modelNames} from './monthly-chart.mjs';
import {setChartStatus} from './chart-status.mjs';
const models=Object.keys(modelNames),ns='http://www.w3.org/2000/svg';
const valid=value=>typeof value==='number'&&Number.isFinite(value);
const number=value=>valid(value)?value.toFixed(1):'—';
const signed=value=>valid(value)?`${value>0?'+':''}${value.toFixed(1)}`:'—';
const delta=values=>valid(values?.mae)&&valid(values?.clean_mae)?values.mae-values.clean_mae:null;
export function roundExtent(values,minimum=5){
 const maximum=Math.max(minimum,...values.filter(valid).map(Math.abs)),power=10**Math.floor(Math.log10(maximum));
 const step=[1,2,2.5,5,10].find(value=>value*power>=maximum/4)*power;
 return Math.ceil(maximum/step)*step;
}
export function evidencePath(rows,x,y,read){
 let output='',connected=false;
 for(const row of rows){const value=read(row);if(!valid(value)){connected=false;continue;}
  output+=`${connected?'L':'M'}${x(row).toFixed(2)},${y(value).toFixed(2)}`;connected=true;
 }return output;
}
export function bandPaths(rows,x,y,lower,upper){
 const groups=[];let group=[];
 for(const row of rows){if(valid(lower(row))&&valid(upper(row)))group.push(row);else if(group.length){groups.push(group);group=[];}}
 if(group.length)groups.push(group);
 return groups.map(values=>evidencePath(values,x,y,upper)+[...values].reverse().map(row=>`L${x(row).toFixed(2)},${y(lower(row)).toFixed(2)}`).join('')+'Z');
}
const svgElement=(tag,attributes={},text)=>{const element=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attributes))element.setAttribute(key,String(value));if(text!==undefined)element.textContent=String(text);return element;};
const textElement=(tag,text)=>{const element=document.createElement(tag);element.textContent=text;return element;};
const addCell=(row,tag,text)=>{const element=textElement(tag,text);row.append(element);return element;};
const styleFor=model=>`--series-color:var(--model-${model})`;
const dateText=seconds=>new Date(seconds*1000).toLocaleDateString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short'});

export function createEvidenceChart(root,{kind,onRetry=()=>{}}){
 const impact=kind==='impact',plot=root.querySelector('.insight-plot'),svg=plot.querySelector('svg');
 const inspector=plot.querySelector('.monthly-inspector'),loading=plot.querySelector('.monthly-loading');
 const retry=loading.querySelector('button');
 const context=root.querySelector('.insight-context'),note=root.querySelector('.insight-note');
 let data=null,metric=impact?'error':'movement',focus='all',geometry,selected=-1;
 for(const button of root.querySelectorAll('[data-metric]'))button.addEventListener('click',()=>{
  metric=button.dataset.metric;for(const peer of root.querySelectorAll('[data-metric]'))peer.setAttribute('aria-pressed',String(peer===button));draw();
 });
 if(!impact){
  const group=root.querySelector('.insight-models');
  for(const model of ['all',...models]){const button=textElement('button',model==='all'?'All':modelNames[model]);button.type='button';button.dataset.modelFocus=model;button.setAttribute('aria-pressed',String(model==='all'));button.setAttribute('aria-label',model==='all'?'Compare all stability models':`Focus ${modelNames[model]} stability spread`);if(model!=='all')button.style.setProperty('--series-color',`var(--model-${model})`);button.addEventListener('click',()=>{focus=model;for(const peer of group.children)peer.setAttribute('aria-pressed',String(peer===button));draw();});group.append(button);}
 }
 function hide(){selected=-1;inspector.hidden=true;svg.querySelector('.insight-selection')?.remove();}
 function draw(){
  hide();svg.replaceChildren();if(!data?.insights)return;
  const width=Math.max(230,plot.clientWidth),height=plot.clientHeight;svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
  impact?drawImpact(width,height):drawStability(width,height);
  if(data.simulation){context.textContent='Simulation mode';note.textContent='Hypothetical values with seeded variation, not observed model performance.';}
  if(data.smoothed){
   svg.querySelector('title').textContent='Smoothed curves between measured model results';
   context.textContent='Interpolated between measured checkpoints';
   note.textContent='Curves retain measured checkpoints. Intermediate values and spread are interpolated for display.';
  }
 }
 function drawImpact(width,height){
  const days=data.days,left=39,right=13,top=14,bottom=24,lane=(height-top-bottom)/3;
  const lastDay=data.end-86400,span=Math.max(86400,lastDay-data.start);
  const x=row=>left+(row.day-data.start)/span*(width-left-right);
  const extent=roundExtent(days.flatMap(row=>models.flatMap(model=>metric==='error'?[row.models[model]?.mae]:[delta(row.models[model])])),metric==='error'?5:2);
  const lanes=[];svg.append(svgElement('title',{},metric==='error'?(data.poisoning_active?'Absolute ETA error during the poisoned period for each model':'Absolute ETA error on normal, unpoisoned inputs for each model'):'Added absolute ETA error caused by the selected input changes'));
  for(const [index,model] of models.entries()){
   const start=top+index*lane,chartTop=start+22,chartBottom=start+lane-13;
   const y=value=>metric==='error'?chartBottom-value/extent*(chartBottom-chartTop):chartTop+(extent-value)/(2*extent)*(chartBottom-chartTop);
   lanes.push({model,y,top:chartTop,bottom:chartBottom});
   svg.append(svgElement('text',{x:left,y:start+10,class:'facet-model',style:styleFor(model)},modelNames[model]));
   const summary=data.insights.impact.models[model];
   const label=metric==='error'?`${number(summary.mae_scenario)} min`:`${signed(summary.added_mae)} min`;
   svg.append(svgElement('text',{x:width-right,y:start+10,'text-anchor':'end',class:'facet-number'},label));
   for(const value of metric==='error'?[0,extent/2,extent]:[-extent,0,extent]){
    svg.append(svgElement('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:value===0?'chart-zero':'chart-grid'}));
    svg.append(svgElement('text',{x:left-7,y:y(value)+3,'text-anchor':'end'},`${metric==='impact'&&value>0?'+':''}${Number(value.toFixed(2))}`));
   }
   svg.append(svgElement('path',{d:evidencePath(days,x,y,row=>metric==='error'?row.models[model]?.mae:delta(row.models[model])),class:'evidence-line impact-line','data-series':model,style:styleFor(model)}));
  }
  const dates=[data.start,lastDay];if(width>=340)for(let value=data.start+7*86400;value<lastDay;value+=7*86400)dates.push(value);
  if(data.cutover>=data.start&&data.cutover<=lastDay)dates.push(data.cutover);
  for(const day of [...new Set(dates)].sort((a,b)=>a-b)){const row={day};svg.append(svgElement('text',{x:x(row),y:height-5,'text-anchor':day===lastDay?'end':'middle'},width<350?String(new Date(day*1000).getUTCDate()):dateText(day)));}
  geometry={samples:days,x,width,lanes};
  const key=root.querySelector('.insight-key');key.hidden=true;
  const cutoverText=dateText(data.start),endText=dateText(lastDay);
  context.textContent=`${metric==='error'?(data.poisoning_active?'Poisoned-input MAE (min)':'Normal-input MAE (min)'):'Added MAE (min) · selected − clean'} · summaries: ${cutoverText}–${endText}`;
  note.textContent=data.poisoning_active?'Only the post-poisoning period is plotted. Added error compares the poisoned forecasts with clean forecasts for the same vessels and times.':'No poisoning selected. Showing normal inputs across the month; added error is zero.';
 }
 function drawStability(width,height){
  const result=data.insights.stability,rows=result.samples,left=39,right=69,top=28,bottom=31;
  const x=row=>left+row.minute/30*(width-left-right);
  const quantities=rows.flatMap(row=>models.map(model=>row.models[model][metric].mean));
  if(focus!=='all')quantities.push(...rows.map(row=>row.models[focus][metric].p90));
  const extent=roundExtent(quantities,2),y=value=>top+(extent-value)/extent*(height-top-bottom);
  svg.append(svgElement('title',{},metric==='movement'?'Mean absolute ETA movement from the first prediction':'Mean absolute ETA revision between five-minute updates'));
  for(let tick=0;tick<=4;tick++){const value=extent*tick/4;svg.append(svgElement('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:tick===0?'chart-zero':'chart-grid'}));svg.append(svgElement('text',{x:left-7,y:y(value)+3,'text-anchor':'end'},Number(value.toFixed(2))));}
  for(const minute of width<380?[0,10,20,30]:[0,5,10,15,20,25,30])svg.append(svgElement('text',{x:x({minute}),y:height-10,'text-anchor':'middle'},minute));
  svg.append(svgElement('text',{x:left,y:12,class:'axis-title'},metric==='movement'?'Mean |ETA(t) − ETA(0)| · min':'Mean |ETA(t) − ETA(t−5)| · min'));
  if(focus!=='all'){
   const get=row=>row.models[focus][metric];
   for(const d of bandPaths(rows,x,y,row=>get(row).p10,row=>get(row).p90))svg.append(svgElement('path',{d,class:'spread-fill','data-model-band':focus,style:styleFor(focus)}));
   for(const bound of ['p10','p90'])svg.append(svgElement('path',{d:evidencePath(rows,x,y,row=>get(row)[bound]),class:'spread-edge',style:styleFor(focus)}));
   if(data.poisoning_active)svg.append(svgElement('path',{d:evidencePath(rows,x,y,row=>get(row).clean_mean),class:'clean-line stability-clean',style:styleFor(focus)}));
  }
  const labels=[];
  for(const model of models){
   svg.append(svgElement('path',{d:evidencePath(rows,x,y,row=>row.models[model][metric].mean),class:`evidence-line stability-line${focus!=='all'&&focus!==model?' series-dim':''}`,'data-series':model,style:styleFor(model)}));
   const last=rows.at(-1),value=last.models[model][metric].mean;
   if(valid(value))labels.push({model,value,desired:y(value),last});
  }
  labels.sort((a,b)=>a.desired-b.desired);let previous=top-15;
  for(const label of labels){label.position=Math.max(top+3,label.desired,previous+14);previous=label.position;}
  const overflow=Math.max(0,(labels.at(-1)?.position??0)-(height-bottom-3));
  for(const label of labels){label.position-=overflow;svg.append(svgElement('path',{d:`M${x(label.last)},${y(label.value)}L${width-right+6},${label.position}`,class:'endpoint-leader',style:styleFor(label.model)}));svg.append(svgElement('text',{x:width-right+9,y:label.position+3,class:'endpoint-label',style:styleFor(label.model)},modelNames[label.model]));}
  geometry={samples:rows,x,y,width,top,bottom:height-bottom};
  context.textContent=`Same ${result.instances} approaches at every point · ${result.total_approaches-result.instances} excluded · ${result.vessels} vessels`;
  note.textContent=focus==='all'?'Average absolute movement keeps opposing ETA revisions from cancelling. Focus a model to reveal its observed 10th–90th percentile range.':`${modelNames[focus]}: shaded = middle 80% of approaches${data.poisoning_active?' · dashed = clean mean':''}. This is observed spread, not confidence in the mean.`;
 }
 function inspect(index){
  if(!data||!geometry)return;const rows=geometry.samples;selected=Math.max(0,Math.min(rows.length-1,index));const row=rows[selected];
  inspector.replaceChildren();const title=textElement('strong',impact?`${dateText(row.day)} · ${row.poisoned?'selected inputs':'clean period'}`:`Minute ${row.minute} · ${metric==='movement'?'movement from first ETA':'five-minute update size'}`);inspector.append(title);
  const table=document.createElement('table'),header=table.createTHead().insertRow();
  for(const label of impact?['Model','Clean','Selected','Added']:['Model','Mean','10–90%'])addCell(header,'th',label);
  const body=table.createTBody();
  for(const model of models){const line=body.insertRow(),name=addCell(line,'td',modelNames[model]);name.className='series-name';name.style.setProperty('--series-color',`var(--model-${model})`);
   if(impact){const values=row.models[model];addCell(line,'td',number(values?.clean_mae));addCell(line,'td',number(values?.mae));addCell(line,'td',signed(delta(values)));}
   else{const values=row.models[model][metric];addCell(line,'td',number(values.mean));addCell(line,'td',valid(values.p10)?`${number(values.p10)}–${number(values.p90)}`:'—');}
  }
  inspector.append(table);
  const paragraph=textElement('p',impact?`Minutes of absolute error · ${row.matched_decisions}/${row.scheduled_decisions} matched checkpoints · ${row.approaches} approaches.`:`Minutes · same ${row.instances} matched approaches at every offset. Range is observed vessel spread, not a confidence interval.`);if(data.smoothed)paragraph.textContent='Curves interpolate between measured checkpoints; extra points are not additional observations.';if(data.simulation)paragraph.textContent='Simulation mode. Synthetic values and assumed spread, not observed vessel outcomes.';inspector.append(paragraph);
  if(!impact&&data.poisoning_active&&focus!=='all')inspector.append(textElement('p',`${modelNames[focus]} clean mean: ${number(row.models[focus][metric].clean_mean)} min.`));
  const width=geometry.width,point=geometry.x(row);inspector.style.left=`${point>width/2?4:Math.max(4,width-Math.min(318,width-8)-4)}px`;inspector.hidden=false;
  svg.querySelector('.insight-selection')?.remove();const group=svgElement('g',{class:'insight-selection'});
  if(impact){for(const lane of geometry.lanes){group.append(svgElement('line',{x1:point,x2:point,y1:lane.top,y2:lane.bottom,class:'chart-guide'}));const value=metric==='error'?row.models[lane.model]?.mae:delta(row.models[lane.model]);if(valid(value))group.append(svgElement('circle',{cx:point,cy:lane.y(value),r:3,class:'chart-dot',style:styleFor(lane.model)}));}}
  else{group.append(svgElement('line',{x1:point,x2:point,y1:geometry.top,y2:geometry.bottom,class:'chart-guide'}));for(const model of models){const value=row.models[model][metric].mean;if(valid(value))group.append(svgElement('circle',{cx:point,cy:geometry.y(value),r:3,class:'chart-dot',style:styleFor(model)}));}}
  svg.append(group);
 }
 plot.addEventListener('pointermove',event=>{if(!geometry||!data)return;const position=event.clientX-plot.getBoundingClientRect().left;inspect(geometry.samples.reduce((best,row,index)=>Math.abs(geometry.x(row)-position)<Math.abs(geometry.x(geometry.samples[best])-position)?index:best,0));});
 plot.addEventListener('pointerleave',()=>{if(document.activeElement!==plot)hide();});plot.addEventListener('pointerdown',event=>{if(event.pointerType!=='mouse')plot.focus();});
 plot.addEventListener('focus',()=>inspect(0));plot.addEventListener('blur',hide);
 plot.addEventListener('keydown',event=>{if(!data||!geometry)return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();inspect(Math.max(0,selected)+(event.key==='ArrowLeft'?-1:1));}else if(event.key==='Home'||event.key==='End'){event.preventDefault();inspect(event.key==='Home'?0:geometry.samples.length-1);}else if(event.key==='Escape')hide();});
 retry.addEventListener('click',onRetry);const observer=new ResizeObserver(draw);observer.observe(plot);
 return {
  setStatus(state){data=null;geometry=null;hide();svg.replaceChildren();loading.hidden=false;retry.hidden=state.status!=='error';setChartStatus(loading,state);root.setAttribute('aria-busy',String(state.status==='loading'));},
  setResult(next){
   if(!next.insights){this.setStatus({status:'error',message:'The paired insights require the updated monthly API. Restart the preview and retry.'});return;}
   data=impact&&next.poisoning_active?{...next,start:Math.max(next.start,next.cutover),days:next.impact_days??next.days.filter(row=>row.day>=next.cutover)}:next;draw();root.setAttribute('aria-busy','false');retry.hidden=true;
   const result=impact?data.insights.impact:data.insights.stability;
   const count=impact?result.matched_decisions:result.instances;loading.hidden=count>0;setChartStatus(loading,{status:'empty',message:impact?'No matched clean/scenario forecasts are available.':'No complete supported 30-minute sequences are available. Short or unsupported sequences remain excluded.'});
  },
  destroy(){observer.disconnect();},
 };
}

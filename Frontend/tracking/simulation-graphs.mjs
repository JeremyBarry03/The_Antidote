// Explicit hypothetical adjustments, not model inference or evaluation.
export const simulationFactors={A:1.2,B:.9,C:.7};
const finite=value=>typeof value==='number'&&Number.isFinite(value);
function scaled(value,model,poisoned=false,variation=1,key=''){
 const factor=model==='B'&&poisoned&&!key.startsWith('clean_')?1.05:simulationFactors[model];
 if(finite(value))return value*factor*variation;
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([name,item])=>[name,scaled(item,model,poisoned,variation,name)]));
 return value;
}
function interpolate(left,right,weight){
 if(finite(left)&&finite(right))return left+(right-left)*weight;
 if(left&&right&&typeof left==='object'&&typeof right==='object')return Object.fromEntries(Object.keys(left).map(key=>[key,interpolate(left[key],right[key],weight)]));
 return null;
}
function random(seed){
 let state=seed>>>0;
 return ()=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state/4294967296;};
}
export function simulateRows(rows,key,count=100,seed=4201,isPoisoned=()=>false){
 if(!rows.length)return [];
 const ordered=[...rows].sort((a,b)=>a[key]-b[key]),first=ordered[0][key],last=ordered.at(-1)[key],next=random(seed);
 const output=Array.from({length:count},(_,index)=>{
  const time=first+(last-first)*index/(count-1);
  let bracket=0;while(bracket<ordered.length-2&&ordered[bracket+1][key]<time)bracket++;
  const left=ordered[bracket],right=ordered[Math.min(bracket+1,ordered.length-1)];
  const fraction=right[key]===left[key]?0:(time-left[key])/(right[key]-left[key]);
  const base=interpolate(left.models,right.models,fraction);
  const models=Object.fromEntries(Object.entries(base).map(([model,values])=>[model,scaled(values,model,isPoisoned(time),1+(next()-.5)*(model==='B'?.4:.24))]));
  return {...left,[key]:time,models,simulation:true,interpolated:true,matched_decisions:0,scheduled_decisions:0,approaches:0,
   ...(key==='minute'?{from_minutes:time,to_minutes:time}:{})};
 });
 return rows[0][key]>rows.at(-1)[key]?output.reverse():output;
}
export function simulationScenario(source){
 const result=structuredClone(source);result.simulation=true;
 const poisoned=time=>source.poisoning_active&&time>=source.cutover;
 result.weekly_days=source.days.map(row=>({...structuredClone(row),models:Object.fromEntries(Object.entries(row.models).map(([model,values])=>[model,scaled(values,model,poisoned(row.day))]))}));
 result.days=simulateRows(source.days,'day',100,4201,poisoned);
 result.impact_days=simulateRows(source.days.filter(row=>!source.poisoning_active||row.day>=source.cutover),'day',100,4201,poisoned);
 result.convergence.samples=simulateRows(source.convergence.samples,'minute',100,4201,()=>source.poisoning_active);
 result.insights.stability.samples=simulateRows(source.insights.stability.samples,'minute',100,4201,()=>source.poisoning_active);
 for(const [model,values] of Object.entries(result.insights.impact.models)){
  values.mae_clean*=simulationFactors[model];
  values.mae_scenario*=model==='B'&&source.poisoning_active?1.05:simulationFactors[model];
  values.added_mae=values.mae_scenario-values.mae_clean;
 }
 for(const row of result.days){
  row.poisoned=source.poisoning_active&&row.day>=source.cutover;
  if(row.day<source.cutover)for(const values of Object.values(row.models)){
   values.mae=values.clean_mae;values.mean_error=values.clean_mean_error;
  }
 }
 return result;
}

// Presentation assumptions for the illustrative poisoning-impact chart only.
// Every subset contributes a lower bound, so adding attacks cannot improve error.
export function createImpactSimulation(scenarios){
 const cache=new Map(),baseline=simulationScenario(scenarios[0]);
 const scale=4.1/baseline.insights.impact.models.C.mae_scenario;
 if(!finite(scale)||scale<=0)throw Error('A positive Antidote simulation baseline is required.');
 const maximum=(value,floor)=>finite(value)&&finite(floor)?Math.max(value,floor):value;
 function impact(mask,simulation){
  if(cache.has(mask))return cache.get(mask);
  const data=simulation??simulationScenario(scenarios[mask]);
  const rows=data.days.map(row=>({day:row.day,models:Object.fromEntries(Object.entries(row.models).map(([model,value])=>
   [model,{mae:finite(value.mae)?value.mae*(model==='C'?scale:1):value.mae}]))}));
  const summary=Object.fromEntries(Object.entries(data.insights.impact.models).map(([model,value])=>
   [model,finite(value.mae_scenario)?value.mae_scenario*(model==='C'?scale:1):value.mae_scenario]));
  if(!mask)summary.C=4.1;
  for(let bit=0;bit<8;bit++)if(mask&(1<<bit)){
   const previous=impact(mask&~(1<<bit));
   for(const model of Object.keys(summary))summary[model]=maximum(summary[model],previous.summary[model]);
   rows.forEach((row,index)=>{
    if(row.day!==previous.rows[index]?.day)throw Error('Simulation time grids must match.');
    for(const model of Object.keys(row.models))row.models[model].mae=maximum(row.models[model].mae,previous.rows[index].models[model].mae);
   });
  }
  const result={rows,summary};cache.set(mask,result);return result;
 }
 return mask=>{
  if(!Number.isInteger(mask)||mask<0||mask>255)throw Error('Invalid simulation attack selection.');
  const result=simulationScenario(scenarios[mask]),selected=impact(mask,result),clean=impact(0,baseline);
  for(const [index,row] of result.days.entries())for(const [model,value] of Object.entries(row.models)){
   value.mae=selected.rows[index].models[model].mae;
   value.clean_mae=clean.rows[index].models[model].mae;
  }
  for(const [model,value] of Object.entries(result.insights.impact.models)){
   value.mae_clean=clean.summary[model];value.mae_scenario=selected.summary[model];
   value.added_mae=finite(value.mae_scenario)&&finite(value.mae_clean)?value.mae_scenario-value.mae_clean:null;
  }
  return result;
 };
}

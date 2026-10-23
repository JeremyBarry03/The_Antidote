// Display interpolation only. Saved predictions, rankings and summaries stay intact.
function blend(left,right,weight){
 if(typeof left==='number'&&typeof right==='number'){
  return Number.isFinite(left)&&Number.isFinite(right)?left+(right-left)*weight:null;
 }
 if(left&&right&&typeof left==='object'&&typeof right==='object'){
  return Object.fromEntries(Object.keys(left).map(key=>[key,blend(left[key],right[key],weight)]));
 }
 return null;
}

export function smoothRows(rows,key,step,cutover=null){
 if(rows.length<2)return structuredClone(rows);
 const descending=rows[0][key]>rows.at(-1)[key];
 const ordered=descending?[...rows].reverse():rows,output=[];
 for(let index=0;index<ordered.length-1;index++){
  const left=ordered[index],right=ordered[index+1],span=right[key]-left[key];
  output.push(structuredClone(left));
  for(let time=left[key]+step;time<right[key];time+=step){
   const fraction=(time-left[key])/span,weight=fraction*fraction*(3-2*fraction);
   const models=blend(left.models,right.models,weight);
   // Do not suggest that an input change affected earlier observations.
   if(key==='day'&&cutover!==null&&time<cutover){
    for(const model of Object.values(models)){
     model.mae=model.clean_mae;model.mean_error=model.clean_mean_error;
    }
   }
   output.push({...left,[key]:time,models,interpolated:true,
    ...(key==='day'?{poisoned:time>=cutover&&(left.poisoned||right.poisoned)}:{from_minutes:time,to_minutes:time})});
  }
 }
 output.push(structuredClone(ordered.at(-1)));
 return descending?output.reverse():output;
}

export function smoothScenario(source){
 const result=structuredClone(source);
 result.smoothed=true;
 result.days=smoothRows(source.days,'day',3600,source.cutover);
 result.convergence.samples=smoothRows(source.convergence.samples,'minute',.25);
 result.insights.stability.samples=smoothRows(source.insights.stability.samples,'minute',.25);
 return result;
}

import {createMonthlyChart} from './monthly-chart.mjs';
import {createAnalysisChart} from './analysis-charts.mjs';
import {createEvidenceChart} from './insights.mjs';

export function scenarioSettings(mask,controls){
 return Object.fromEntries(controls.filter((_,bit)=>mask&(1<<bit)).map(control=>[control.id,control.maximum*.25]));
}

export function validateGraphBundle(data){
 if(data?.version!==1||data.strength_fraction!==.25||data.controls?.length!==8||new Set(data.controls.map(control=>control.id)).size!==8)
  throw Error('The saved graph data has an unsupported format.');
 for(let mask=0;mask<256;mask++){
  const scenario=data.scenarios?.[mask];
  if(scenario?.status!=='ready'||!Array.isArray(scenario.days)||!scenario.convergence||!scenario.insights||scenario.poisoning_active!==Boolean(mask))
   throw Error(`The saved graph data is missing scenario ${mask}.`);
 }
 return data;
}

export function createPreloadedGraphs(root,{fetcher=fetch}={}){
 const document=root.ownerDocument,$=id=>document.getElementById(id);
 const fieldset=root.querySelector('fieldset'),options=root.querySelector('.scenario-options');
 const summary=root.querySelector('[role=status]'),reset=root.querySelector('.scenario-reset'),retry=root.querySelector('.scenario-retry');
 let bundle=null,mask=0,destroyed=false;
 const controller=new AbortController(),onRetry=()=>void load();
 const monthly=createMonthlyChart($('monthly-eta'),{onRetry});
 const convergence=createAnalysisChart($('arrival-convergence'),{kind:'convergence',onRetry});
 const impact=createEvidenceChart($('paired-impact'),{kind:'impact',onRetry});
 const stability=createEvidenceChart($('forecast-stability'),{kind:'stability',onRetry});
 const charts=[monthly,convergence,impact,stability];
 function render(){
  if(!bundle)return;
  const data=bundle.scenarios[mask];
  monthly.setResult(data);
  for(const chart of [convergence,impact,stability])chart.setResult(data);
  const labels=bundle.controls.filter((_,bit)=>mask&(1<<bit)).map(control=>control.label);
  summary.textContent=labels.length?`${labels.join(' + ')} · each at 25% strength`:'Clean reference · no attacks selected';
  reset.disabled=mask===0;
  for(const input of options.querySelectorAll('input'))input.checked=Boolean(mask&(1<<Number(input.value)));
 }
 function select(next){mask=next;render();}
 reset.addEventListener('click',()=>select(0));retry.addEventListener('click',onRetry);
 async function load(){
  fieldset.disabled=true;reset.disabled=true;retry.hidden=true;summary.textContent='Loading saved comparisons…';
  for(const chart of charts)chart.setStatus({status:'loading',message:'Loading saved model comparisons…'});
  try{
   const response=await fetcher(new URL('./data/scenarios.json',import.meta.url),{signal:controller.signal,cache:'no-store'});
   if(!response.ok)throw Error('Saved graph data could not be loaded.');
   const next=validateGraphBundle(await response.json());if(destroyed)return;bundle=next;
   options.replaceChildren();
   for(const [bit,control] of bundle.controls.entries()){
    const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span'),strength=document.createElement('span');
    input.type='checkbox';input.value=String(bit);input.addEventListener('change',()=>select(mask^(1<<bit)));
    name.textContent=control.label;strength.className='scenario-strength';strength.textContent=control.unit==='min'?`${control.maximum*.25} min`:'25%';
    label.append(input,name,strength);options.append(label);
   }
   if(bundle.scope?.sampled){
    const scope=bundle.scope;
    root.title=`March demo sample: ${scope.approaches} of ${scope.total_approaches} approaches. Not a full-month accuracy benchmark. Each selected attack is at 25% of its maximum.`;
    document.querySelector('.analytics-featured')?.setAttribute('aria-label',`Model comparison · fixed demo sample of ${scope.approaches}/${scope.total_approaches} March approaches`);
   }
   fieldset.disabled=false;render();
  }catch(error){
   if(destroyed||error.name==='AbortError')return;
   const message=error.message||'Saved comparisons are unavailable.';summary.textContent=message;retry.hidden=false;
   for(const chart of charts)chart.setStatus({status:'error',message});
  }
 }
 void load();
 return {destroy(){destroyed=true;controller.abort();for(const chart of charts)chart.destroy();}};
}

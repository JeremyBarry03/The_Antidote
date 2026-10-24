<<<<<<< Updated upstream
import {simulationScenario,simulateRows} from './simulation-graphs.mjs';
import {smoothScenario} from './smoothed-graphs.mjs';
=======
import {createImpactSimulation,simulateRows} from './simulation-graphs.mjs';
>>>>>>> Stashed changes
import {createMonthlyChart,weeklyRows} from './monthly-chart.mjs';
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

export function createPreloadedGraphs(root,{fetcher=fetch,initialMode='measured'}={}){
 const document=root.ownerDocument,$=id=>document.getElementById(id);
 const fieldset=root.querySelector('fieldset'),options=root.querySelector('.scenario-options');
 const summary=root.querySelector('[role=status]'),reset=root.querySelector('.scenario-reset'),retry=root.querySelector('.scenario-retry');
<<<<<<< Updated upstream
 const mode=root.querySelector('.graph-data-mode'),disclosure=root.querySelector('.graph-data-disclosure');
 mode.value=initialMode;
 const panels=['monthly-eta','arrival-convergence','paired-impact','forecast-stability'].map($);
 let bundle=null,fullBundle=null,mask=0,destroyed=false;
=======
 let bundle=null,simulate=null,mask=0,destroyed=false;
>>>>>>> Stashed changes
 const controller=new AbortController(),onRetry=()=>void load();
 const monthly=createMonthlyChart($('monthly-eta'),{onRetry,weekly:true});
 const convergence=createAnalysisChart($('arrival-convergence'),{kind:'convergence',onRetry});
 const impact=createEvidenceChart($('paired-impact'),{kind:'impact',onRetry});
 const stability=createEvidenceChart($('forecast-stability'),{kind:'stability',onRetry});
 const charts=[monthly,convergence,impact,stability];
 function render(){
  if(!bundle)return;
<<<<<<< Updated upstream
  const full=mode.value==='full';
  if(full&&!fullBundle?.scenarios[String(mask)]){
   const message=fullBundle?'This combination is not cached for the full March cohort. Choose a completed single fault or another graph data mode.':'Full-March results are being prepared. Retry loading graphs shortly.';
   for(const panel of panels){panel.querySelector('.graph-coverage')?.remove();panel.dataset.origin='pending';panel.querySelector('header').dataset.simulation='false';}
   for(const chart of charts)chart.setStatus({status:'empty',message});
   disclosure.textContent=message;summary.textContent=message;retry.hidden=false;return;
  }
  const smoothed=mode.value==='smoothed';
  const simulation=mode.value==='simulation',source=full?fullBundle.scenarios[mask]:bundle.scenarios[mask];
  const data=simulation?simulationScenario(source):smoothed?smoothScenario(source):source;
  if(simulation)data.weekly_curve=simulateRows(weeklyRows(source),'day',100,4201,time=>source.poisoning_active&&time>=source.cutover);
  for(const panel of panels){
   panel.dataset.origin=full?'full':simulation?'simulation':smoothed?'smoothed':'measured';
   panel.querySelector('header').dataset.simulation=String(simulation);
  }
  const sample=`March sample: ${source.approaches} approaches, ${source.vessels} vessels, ${(source.evaluation_checkpoints??source.scheduled_decisions).toLocaleString()} archived checkpoints. All 256 combinations cached at 25% strength; selected faults begin 15 March. Sample results, not a full-cohort benchmark.`;
  disclosure.textContent=full?`Full March: ${source.approaches} approaches, ${source.vessels} vessels, ${source.evaluation_checkpoints.toLocaleString()} archived checkpoints. Cached actual forecasts with conditional repairs; selected faults begin 15 March.`:simulation?'Simulation mode: 100 synthetic points per curve with seeded variation. Assumed error changes: Antidote −30%, XGBoost −10% on clean inputs and +5% on poisoned inputs, Poly +20%. Not measured performance.':smoothed?`${sample} Curves interpolate between saved predictions; extra points are visual estimates.`:sample;
  root.title=disclosure.textContent;
  document.querySelector('.analytics-featured')?.setAttribute('aria-label',full?'Full March cohort, actual frozen-model forecasts':simulation?'Simulation mode, hypothetical model performance':smoothed?'Smoothed model comparison, interpolated between measured checkpoints':`Measured model comparison, ${source.approaches} sampled March approaches`);
  for(const panel of panels)panel.querySelector('.graph-coverage')?.remove();
  if(!simulation){
   const counts=[
    `${source.scheduled_decisions.toLocaleString()} checkpoints across ${source.days.length} days, daily/weekly summaries`,
    `${source.convergence.matched_decisions.toLocaleString()} final-hour checkpoints in five-minute bins`,
    `${source.insights.impact.matched_decisions.toLocaleString()} matched clean/scenario checkpoints after 15 Mar`,
    `${source.insights.stability.instances} complete approaches at seven offsets; ${source.insights.stability.short_or_incomplete} incomplete`,
   ];
   panels.forEach((panel,index)=>{const text=document.createElement('p');text.className='graph-coverage';text.textContent=counts[index];panel.append(text);});
  }
=======
  const source=bundle.scenarios[mask],data=simulate(mask);
  data.weekly_curve=simulateRows(weeklyRows(source),'day',100,4201,time=>source.poisoning_active&&time>=source.cutover);
  for(const id of ['monthly-eta','arrival-convergence','paired-impact','forecast-stability'])$(id).dataset.origin='simulation';
  document.querySelector('.analytics-featured')?.setAttribute('aria-label','Illustrative simulation of model performance');
>>>>>>> Stashed changes
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
<<<<<<< Updated upstream
   showControls(bundle.controls);
   fieldset.disabled=false;
   if(mode.value==='full'){await loadFull();}else render();
=======
   simulate=createImpactSimulation(bundle.scenarios);
   options.replaceChildren();
   for(const [bit,control] of bundle.controls.entries()){
    const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span'),strength=document.createElement('span');
    input.type='checkbox';input.value=String(bit);input.addEventListener('change',()=>select(mask^(1<<bit)));
    name.textContent=control.label;strength.className='scenario-strength';strength.textContent=control.unit==='min'?`${control.maximum*.25} min`:'25%';
    label.append(input,name,strength);options.append(label);
   }
   root.title='Illustrative March 2024 simulation. Selected faults use 25% strength; curves show hypothetical model performance.';
   fieldset.disabled=false;render();
>>>>>>> Stashed changes
  }catch(error){
   if(destroyed||error.name==='AbortError')return;
   const message=error.message||'Saved comparisons are unavailable.';summary.textContent=message;retry.hidden=false;
   for(const chart of charts)chart.setStatus({status:'error',message});
  }
 }
 async function loadFull(){
  try{
   const response=await fetcher(new URL('./data/full-month.json',import.meta.url),{signal:controller.signal,cache:'no-store'});
   if(response.ok){
    const result=await response.json();
    if(result.version!==1||result.scope?.sampled!==false||!result.scenarios?.['0'])throw Error('Invalid full-March graph bundle.');
    fullBundle=result;
   }
   if(!destroyed){retry.hidden=Boolean(fullBundle);render();}
  }catch(error){if(!destroyed&&error.name!=='AbortError'){summary.textContent=error.message;retry.hidden=false;}}
 }
 function showControls(list){
  options.replaceChildren();
  for(const [bit,control] of list.entries()){
   const label=document.createElement('label'),input=document.createElement('input'),name=document.createElement('span'),strength=document.createElement('span');
   input.type='checkbox';input.value=String(bit);input.addEventListener('change',()=>select(mask^(1<<bit)));
   name.textContent=control.label;strength.className='scenario-strength';strength.textContent=control.unit==='min'?`${control.maximum*.25} min`:'25%';
   label.append(input,name,strength);options.append(label);
  }
 }
 function changeMode(){
  retry.hidden=true;
  if(bundle){showControls(bundle.controls);fieldset.disabled=false;if(mode.value==='full'&&!fullBundle)void loadFull();else render();}
  else void load();
 }
 mode.addEventListener('change',changeMode);
 changeMode();
 return {destroy(){mode.removeEventListener('change',changeMode);destroyed=true;controller.abort();for(const chart of charts)chart.destroy();}};
}

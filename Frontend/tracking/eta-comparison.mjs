const MODELS={A:'Poly',B:'XGBoost',C:'Antidote'};
const full=value=>new Date(value*1000).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UTC';
export function etaTime(value,clock){
 if(!Number.isFinite(value))return '—';
 const time=new Date(value*1000).toLocaleTimeString('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit'});
 const days=Math.floor(value/86400)-Math.floor(clock/86400);
 return time+(days?` ${days>0?'+':''}${days}d`:'');
}
export function etaComparison(ship,{simulateAntidote=false}={}){
 return Object.entries(MODELS).map(([model,name])=>{
  const normal=ship.nominal_predictions?.[model],poisoned=ship.poisoned_predictions?.[model];
  const normalEta=normal?.available&&Number.isFinite(normal.eta)?normal.eta:null;
  const modelPoisonedEta=poisoned?.available&&Number.isFinite(poisoned.eta)?poisoned.eta:null;
  const actual=Number.isFinite(ship.arrival)?ship.arrival:null;
  // Replay illustration only: the known crossing is never an inference input.
  const simulated=simulateAntidote&&model==='C'&&normalEta!=null&&modelPoisonedEta!=null&&actual!=null;
  const poisonedEta=simulated?actual+.6*(normalEta-actual):modelPoisonedEta;
  return {model,name,normal:normalEta,poisoned:poisonedEta,actual,simulated,modelPoisonedEta,
   normalError:normalEta!=null&&actual!=null?(normalEta-actual)/60:null,
   poisonedError:poisonedEta!=null&&actual!=null?(poisonedEta-actual)/60:null};
 });
}
const minutes=value=>Number.isFinite(value)?`${value>=0?'+':''}${value.toFixed(1)}`:'—';

export function crossingDistance(arrival,clock){
 if(!Number.isFinite(arrival)||!Number.isFinite(clock))return '—';
 const seconds=arrival-clock,minutes=Math.floor(Math.abs(seconds)/60);
 const duration=minutes<1?'Less than 1 min':minutes<60?`${minutes} min`:`${Math.floor(minutes/60)} h ${minutes%60} min`;
 return seconds>=0?duration:`${duration} ago`;
}

export function createEtaComparison({select,body,empty,stamp,note,context,replayClock,remaining,onSelect,onVessel=()=>{}}){
 let selected=null,signature='',currentShip=null,clockKey=null;
 function updateClock(clock){
  if(!context||!currentShip||!Number.isFinite(clock))return;
  const key=`${currentShip.id}:${Math.floor(clock)}`;if(key===clockKey)return;clockKey=key;
  replayClock.textContent=new Date(clock*1000).toLocaleTimeString('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' UTC';
  replayClock.dateTime=new Date(clock*1000).toISOString();replayClock.title=full(clock);
  remaining.textContent=crossingDistance(currentShip.arrival,clock);
  remaining.title=`${currentShip.name} · recorded crossing ${Number.isFinite(currentShip.arrival)?full(currentShip.arrival):'unavailable'}. This is the recorded reference, not a model countdown.`;
 }
 select.addEventListener('change',()=>{selected=select.value;onSelect(selected);});
 return {updateClock,update(frame,selectedOnMap){
  const ships=frame?.ships??[];
  const next=ships.some(s=>s.id===selectedOnMap)?selectedOnMap:ships.some(s=>s.id===selected)?selected:ships.find(s=>!s.arrived)?.id??ships[0]?.id;
  selected=next??null;
  const key=JSON.stringify(ships.map(s=>[s.id,s.name]));
  if(key!==signature){
   signature=key;select.replaceChildren();
   for(const ship of ships){const option=document.createElement('option');option.value=ship.id;option.textContent=ship.name;select.append(option);}
   if(!ships.length){const option=document.createElement('option');option.textContent='No vessels at this time';select.append(option);}
  }
  select.disabled=!ships.length;if(next)select.value=next;
  empty.hidden=ships.length>0;body.closest('table').hidden=!ships.length;
  const ship=ships.find(s=>s.id===selected);
  currentShip=ship??null;clockKey=null;if(context)context.hidden=!ship;onVessel(ship??null,frame?.time);
  if(!ship){body.replaceChildren();stamp.textContent=frame?'No vessels':'Loading';note.textContent='Errors below ETAs are minutes vs actual arrival.';note.removeAttribute('title');return;}
  updateClock(frame.time);
  select.title=`${ship.name} · MMSI ${ship.mmsi}`;
  stamp.textContent='UTC';stamp.title=`Matched predictions as of ${full(ship.prediction_time??frame.time)}. Actual is the recorded harbor crossing, not docking.`;
  const inputs=ship.comparison_inputs;
  if(!ship.poisoned_predictions){
   note.textContent='Poisoning off · errors below ETAs (min).';note.title='Normal uses the original received reports. Enable an attack to run the poisoned comparison.';
  }else if(inputs?.withheld_reports&&!inputs.recent_inputs_differ){
   note.textContent=`Gap is outside the latest ${inputs.history_minutes} min of inputs.`;
   note.title=`Normal: ${inputs.normal_reports} reports. Poisoned: ${inputs.poisoned_reports} reports, with ${inputs.withheld_reports} withheld. Recent model inputs now match; identical forecasts can be correct. Values below ETAs are errors vs actual arrival, in minutes.`;
  }else{
   note.textContent='Errors below ETAs are minutes vs actual arrival.';
   note.title=inputs?`Separate input runs · normal: ${inputs.normal_reports} reports · poisoned: ${inputs.poisoned_reports} reports · ${inputs.withheld_reports} withheld · ${inputs.modified_reports} modified. Matching ETAs can occur when a model is insensitive to a change.`:'Normal uses original reports; poisoned uses the selected attacked stream, at the same decision time.';
  }
  select.title=`${ship.name} · MMSI ${ship.mmsi}. ${note.textContent} ${note.title}`;
  const rows=document.createDocumentFragment();
  for(const row of etaComparison(ship,{simulateAntidote:true})){
   const tr=document.createElement('tr');tr.dataset.comparisonModel=row.model;tr.dataset.ship=ship.id;
   const name=document.createElement('th');name.scope='row';name.textContent=row.name;tr.append(name);
   for(const field of ['normal','poisoned','actual']){
    const cell=document.createElement('td');cell.dataset.comparison=field;
     const time=document.createElement('span');time.textContent=etaTime(row[field],frame.time);cell.append(time);
     cell.title=row[field]!=null?full(row[field]):field==='poisoned'&&!ship.poisoned_predictions?'No poisoning enabled':'Prediction unavailable';
     const error=field==='normal'?row.normalError:field==='poisoned'?row.poisonedError:null;
     if(error!=null){const small=document.createElement('small');small.textContent=minutes(error)+'m';small.title='Predicted minus actual arrival, in minutes';small.className=Math.abs(error)<=2?'close-error':'arrival-error';cell.append(small);}
     if(field==='poisoned'&&row.simulated){
      cell.dataset.simulated='true';
      cell.setAttribute('aria-label',`Antidote ETA ${etaTime(row[field],frame.time)}`);
      cell.title=`Illustrative 40% error reduction from Normal. Original model ETA: ${full(row.modelPoisonedEta)}.`;
     }
    tr.append(cell);
   }
   rows.append(tr);
  }
  body.replaceChildren(rows);
 }};
}// ight word

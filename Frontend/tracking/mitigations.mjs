// Settings and results for the existing Python strategies; no browser inference.
export function fleetFrameURL(time,poisoning,options={enabled:true,trusted_fixes:false,drift_direction:'under'}){
 return '/api/fleet/frame?'+new URLSearchParams({time:String(time),poisoning:JSON.stringify(poisoning),
  mitigate:String(options.enabled),trusted_fixes:String(options.trusted_fixes),drift_direction:options.drift_direction});
}

export function renderMitigations(root,ship,{loading=false,error=false}={}){
 const summary=root.querySelector('#mitigation-status'),results=root.querySelector('#mitigation-results');
 results.replaceChildren();summary.removeAttribute('data-state');
 if(error){summary.textContent='Antidote · replay unavailable';return;}
 if(loading){summary.textContent='Antidote · updating…';return;}
 const state=ship?.mitigation;
 if(!state){summary.textContent='Antidote · select an active vessel';return;}
 if(!state.enabled){summary.textContent='Additional mitigations off · trained guard active';return;}
 const applied=state.strategies.filter(strategy=>strategy.applied);
 const reviews=state.strategies.filter(strategy=>strategy.requires_review);
 summary.textContent=applied.length?`Antidote · estimates applied${reviews.length?' · review needed':''}`:reviews.length?'Antidote · review needed':'Antidote · monitoring inputs';
 summary.dataset.state=reviews.length?'review':applied.length?'estimated':'monitoring';
 for(const strategy of state.strategies){
  const row=document.createElement('li'),label=document.createElement('strong'),detail=document.createElement('span');
  label.textContent=strategy.label;detail.textContent=strategy.message;row.append(label,detail);results.append(row);
 }
 const note=document.createElement('li');note.className='mitigation-method-note';note.textContent=state.reference_simulated?'Uses SIMULATED verified position fixes. ETA accuracy is not calibrated.':'Conditional research strategies. Combined-attack accuracy is not established.';results.append(note);
}

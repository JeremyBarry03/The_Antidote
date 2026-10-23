const REASONS={
 implausible_position_jump:'Implausible position jump',
 conflicting_bin_positions:'Conflicting positions in the same minute',
 no_reports:'No usable reports received',
 reporting_gap:'Reporting cadence interrupted',
};

export function inputWarnings(ship){
 if(ship.arrived)return [];
 const diagnostics=ship.diagnostics??{},reasons=(diagnostics.reasons??[]).filter(reason=>Object.hasOwn(REASONS,reason));
 const warnings=reasons.map(reason=>({code:reason,text:REASONS[reason]}));
 if(Number.isFinite(ship.age_minutes)&&ship.age_minutes>15)warnings.push({code:'stale_reports',text:`Latest received report is ${ship.age_minutes.toFixed(1)} min old`});
 if(diagnostics.state==='review'&&!ship.predictions?.C?.available&&!warnings.some(w=>w.code==='no_reports'))warnings.push({code:'eta_unavailable',text:'Insufficient usable input for an Antidote ETA'});
 return warnings;
}

// A dismissal lasts for the current vessel/warning episode. Audit poison labels
// never create alerts: these are observable input-guard warnings, not ground truth.
export class AnomalyEpisodes{
 dismissed=new Set();
 reset(){this.dismissed.clear();}
 update(ships,model){
  const active=ships.flatMap(ship=>inputWarnings(ship).map(warning=>({...warning,ship:ship.name,id:ship.id,key:`${ship.id}:${warning.code}`})));
  const keys=new Set(active.map(w=>w.key));
  for(const key of this.dismissed)if(!keys.has(key))this.dismissed.delete(key);
  return model==='C'?active.filter(warning=>!this.dismissed.has(warning.key)):[];
 }
 dismiss(warnings){for(const warning of warnings)this.dismissed.add(warning.key);}
}

export function createAnomalyNotice(container){
 const episodes=new AnomalyEpisodes();let current=[],signature='';
 const header=document.createElement('div');header.className='anomaly-header';
 const title=document.createElement('strong');title.textContent='Antidote · Input anomaly';
 const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Dismiss Antidote warning');
 const list=document.createElement('ul'),note=document.createElement('p');note.className='anomaly-note';note.textContent='Input-guard warning; this does not confirm poisoning.';
 header.append(title,close);container.append(header,list,note);
 function dismiss(){episodes.dismiss(current);container.hidden=true;signature='';}
 close.addEventListener('click',dismiss);
 container.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismiss();}});
 return {
  reset(){episodes.reset();signature='';current=[];container.hidden=true;},
  update(ships,model){
   current=episodes.update(ships,model);
   if(!current.length){container.hidden=true;signature='';return;}
   const key=JSON.stringify(current.map(warning=>[warning.key,warning.text]));
   if(key!==signature){
    list.replaceChildren();
    const byShip=new Map();for(const warning of current){if(!byShip.has(warning.id))byShip.set(warning.id,{name:warning.ship,text:[]});byShip.get(warning.id).text.push(warning.text);}
    for(const warning of byShip.values()){
     const item=document.createElement('li'),name=document.createElement('b'),detail=document.createElement('span');name.textContent=warning.name;detail.textContent=warning.text.join(' · ');item.append(name,detail);list.append(item);
    }
    signature=key;
   }
   container.hidden=false;
  },
 };
}

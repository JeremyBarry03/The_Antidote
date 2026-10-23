import {etaTime} from './eta-comparison.mjs';

// Use the map's presentation cohort, including vessels finishing their arrival
// animation. Missing Antidote forecasts never fall back to another model.
export function createAntidoteEtas(container,{onSelect=()=>{}}={}){
 const list=container.querySelector('.antidote-eta-list'),count=container.querySelector('.antidote-eta-count'),rows=new Map();
 return {update(ships,time,selected){
  container.hidden=!ships.length;
  count.textContent=`${ships.length} ${ships.length===1?'vessel':'vessels'}`;
  const ids=new Set(ships.map(ship=>ship.id));
  for(const [id,row] of rows)if(!ids.has(id)){row.button.remove();rows.delete(id);}
  ships.forEach((ship,index)=>{
   let row=rows.get(ship.id);
   if(!row){
    const button=document.createElement('button'),name=document.createElement('span'),value=document.createElement('strong');
    button.type='button';button.className='antidote-eta-row';button.dataset.vessel=ship.id;
    name.className='antidote-eta-name';value.className='antidote-eta-value';button.append(name,value);
    button.addEventListener('click',()=>onSelect(ship.id));row={button,name,value};rows.set(ship.id,row);
   }
   const prediction=ship.predictions?.C,available=prediction?.available&&Number.isFinite(prediction.eta);
   const text=available?etaTime(prediction.eta,time)+' UTC':'Unavailable';
   row.name.textContent=ship.name;row.value.textContent=text;
   row.button.setAttribute('aria-pressed',String(selected===ship.id));
   row.button.setAttribute('aria-label',`${ship.name}: Antidote ETA ${text}. Select vessel`);
   const asOf=new Date((ship.prediction_time??time)*1000).toISOString().replace('T',' ').replace('.000Z',' UTC');
   row.button.title=`${ship.name} · Antidote forecast as of ${asOf} · ${ship.poisoned_predictions?'Simulated disruption':'Original reports'}. Arrival refers to the geographic reference crossing.`;
   // Avoid moving existing rows on ordinary updates, preserving keyboard focus.
   if(list.children[index]!==row.button)list.insertBefore(row.button,list.children[index]??null);
  });
 }};
}

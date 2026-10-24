// @vitest-environment jsdom
import {expect,it} from 'vitest';
import {etaComparison,createEtaComparison} from '../eta-comparison.mjs';

function ship(normal=1600){
 return {id:'vessel',name:'Vessel',mmsi:'123',arrival:1000,
  nominal_predictions:Object.fromEntries(['A','B','C'].map(model=>[model,{available:true,eta:normal}])),
  poisoned_predictions:Object.fromEntries(['A','B','C'].map(model=>[model,{available:true,eta:1900}]))};
}
it('makes the illustrative poisoned Antidote error 40% smaller than Normal for early and late forecasts',()=>{
 for(const normal of [400,1000,1600]){
  const source=ship(normal),before=structuredClone(source),raw=etaComparison(source);
  const illustrated=etaComparison(source,{simulateAntidote:true});
  const row=illustrated.find(row=>row.model==='C');
  expect(row.poisonedError).toBeCloseTo(row.normalError*.6,10);
  expect(row.simulated).toBe(true);
  expect(row.modelPoisonedEta).toBe(1900);
  expect(raw.find(row=>row.model==='C').poisoned).toBe(1900);
  for(const name of ['A','B'])expect(illustrated.find(row=>row.model===name)).toEqual(raw.find(row=>row.model===name));
  expect(source).toEqual(before);
 }
});
it('does not fabricate forecasts when poisoning, Normal, Actual or poisoned support is absent',()=>{
 for(const modify of [s=>{s.poisoned_predictions=null;},s=>{s.arrival=null;},
  s=>{s.nominal_predictions.C.available=false;},s=>{s.poisoned_predictions.C.available=false;}]){
  const source=ship();modify(source);
  expect(etaComparison(source,{simulateAntidote:true}).find(row=>row.model==='C').simulated).toBe(false);
 }
});
it('keeps illustration details accessible without an extra visible label',()=>{
 document.body.innerHTML='<select></select><table><tbody></tbody></table><p id="empty"></p><span id="stamp"></span><p id="note"></p>';
 const comparison=createEtaComparison({select:document.querySelector('select'),body:document.querySelector('tbody'),
  empty:document.getElementById('empty'),stamp:document.getElementById('stamp'),note:document.getElementById('note'),onSelect:()=>{}});
 const source=ship();comparison.update({ships:[source],time:500});
 expect(document.querySelectorAll('[data-simulated="true"]')).toHaveLength(1);
 const illustrated=document.querySelector('[data-comparison-model="C"] [data-comparison="poisoned"]');
 expect(illustrated.textContent).toContain('+6.0m');
 expect(illustrated.textContent).not.toContain('Simulated');
 expect(illustrated.getAttribute('aria-label')).toContain('Illustrative');
 expect(illustrated.title).toContain('Illustrative');
 expect(document.querySelector('[data-comparison-model="C"] [data-comparison="normal"]').textContent).toContain('+10.0m');
 source.poisoned_predictions=null;comparison.update({ships:[source],time:500});
 expect(document.querySelector('.comparison-simulation')).toBeNull();
});

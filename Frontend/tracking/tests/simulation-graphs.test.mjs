import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
import {simulationScenario,simulateRows,createImpactSimulation} from '../simulation-graphs.mjs';

it('keeps the source intact and applies explicit hypothetical summary factors',()=>{
 const bundle=JSON.parse(readFileSync('tracking/data/scenarios.json','utf8'));
 for(const mask of [0,64,255]){
  const source=bundle.scenarios[mask],before=JSON.stringify(source),result=simulationScenario(source);
  for(const samples of [result.days,result.impact_days,result.convergence.samples,result.insights.stability.samples])expect(samples).toHaveLength(100);
  for(const [model,factor] of Object.entries({A:1.2,B:.9,C:.7})){
   expect(result.insights.impact.models[model].mae_scenario).toBeCloseTo(source.insights.impact.models[model].mae_scenario*(model==='B'&&source.poisoning_active?1.05:factor),12);
  }
  expect(result.insights.impact.models.B.mae_clean).toBeCloseTo(source.insights.impact.models.B.mae_clean*.9,12);
  expect(result.insights.impact.models.B.added_mae).toBeCloseTo(result.insights.impact.models.B.mae_scenario-result.insights.impact.models.B.mae_clean,12);
  expect(result).toEqual(simulationScenario(source));
  expect(JSON.stringify(source)).toBe(before);
 }
});

it('uses seeded variation and never creates forecasts across missing model values',()=>{
 const rows=[{minute:0,models:{A:{mae:10},B:{mae:null}}},{minute:10,models:{A:{mae:10},B:{mae:null}}}];
 const first=simulateRows(rows,'minute'),second=simulateRows(rows,'minute',100,42);
 expect(first).not.toEqual(second);
 for(const row of first){expect(row.models.A.mae).toBeGreaterThan(10.5);expect(row.models.A.mae).toBeLessThan(13.5);expect(row.models.B.mae).toBeNull();}
});

it('switches XGBoost factors at poisoning without compounding the clean reduction',()=>{
 const values={mae:10,mean_error:8,clean_mae:10,clean_mean_error:8};
 const rows=[{day:0,models:{B:values}},{day:10,models:{B:values}}];
 const clean=simulateRows(rows,'day');
 const selected=simulateRows(rows,'day',100,4201,time=>time>=5);
 for(let index=0;index<100;index++){
  const ratio=selected[index].models.B.mae/clean[index].models.B.mae;
  expect(ratio).toBeCloseTo(selected[index].day<5?1:1.05/.9,12);
  expect(selected[index].models.B.clean_mae).toBe(clean[index].models.B.clean_mae);
 }
});

it('sets the illustrative Antidote baseline to 4.1 and never lowers impact when adding any attack',()=>{
 const bundle=JSON.parse(readFileSync('tracking/data/scenarios.json','utf8')),original=JSON.stringify(bundle);
 const simulate=createImpactSimulation(bundle.scenarios),results=Array.from({length:256},(_,mask)=>simulate(mask));
 expect(results[0].insights.impact.models.C.mae_scenario).toBe(4.1);
 for(let mask=0;mask<256;mask++){
  const result=results[mask];
  expect(result.insights.impact.models.C.mae_clean).toBe(4.1);
  for(let bit=0;bit<8;bit++)if(!(mask&(1<<bit))){
   const added=results[mask|(1<<bit)];
   for(const model of ['A','B','C']){
    expect(added.insights.impact.models[model].mae_scenario).toBeGreaterThanOrEqual(result.insights.impact.models[model].mae_scenario);
    result.days.forEach((row,index)=>{
     const value=row.models[model].mae,next=added.days[index].models[model].mae;
     if(value!==null&&next!==null)expect(next).toBeGreaterThanOrEqual(value);
    });
   }
  }
 }
 expect(simulate(64)).toEqual(results[64]);
 expect(simulate(0)).toEqual(results[0]);
 expect(JSON.stringify(bundle)).toBe(original);
},20000);

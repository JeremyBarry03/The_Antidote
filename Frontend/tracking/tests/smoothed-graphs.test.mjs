import {weeklyRows} from '../monthly-chart.mjs';
import {readFileSync} from 'node:fs';
import {expect,it} from 'vitest';
import {smoothRows,smoothScenario} from '../smoothed-graphs.mjs';

it('densifies saved results without changing measured points, summaries or source data',()=>{
 const bundle=JSON.parse(readFileSync('tracking/data/scenarios.json','utf8'));
 for(const mask of [0,1,65,255]){
  const source=bundle.scenarios[mask],snapshot=JSON.stringify(source),result=smoothScenario(source);
  expect(result.days).toHaveLength(721);
  expect(result.convergence.samples).toHaveLength(241);
  expect(result.insights.stability.samples).toHaveLength(121);
  for(const [original,smoothed,key] of [
   [source.days,result.days,'day'],
   [source.convergence.samples,result.convergence.samples,'minute'],
   [source.insights.stability.samples,result.insights.stability.samples,'minute'],
  ]){
   for(const row of original)expect(smoothed.find(point=>point[key]===row[key])).toEqual(row);
  }
  expect(result.insights.impact).toEqual(source.insights.impact);
  expect(result.matched_decisions).toBe(source.matched_decisions);
  expect(JSON.stringify(source)).toBe(snapshot);
 }
});

it('keeps interpolated values within endpoint bounds and preserves missing data',()=>{
 const rows=[{minute:0,models:{A:{mae:2},B:{mae:null}}},{minute:5,models:{A:{mae:8},B:{mae:4}}}];
 const result=smoothRows(rows,'minute',1);
 for(const point of result.slice(1,-1)){
  expect(point.models.A.mae).toBeGreaterThanOrEqual(2);
  expect(point.models.A.mae).toBeLessThanOrEqual(8);
  expect(point.models.B.mae).toBeNull();
 }
});

it('groups only measured checkpoints into weeks and keeps cutover periods separate',()=>{
 const start=Date.UTC(2024,2,1)/1000,day=86400;
 const data={start,end:start+14*day,cutover:start+3*day,poisoning_active:true,days:[
  {day:start,matched_decisions:2,scheduled_decisions:2,models:{A:{mean_error:2,mae:2}}},
  {day:start+2*day,matched_decisions:3,scheduled_decisions:3,models:{A:{mean_error:4,mae:4}}},
  {day:start+2.5*day,interpolated:true,matched_decisions:99,scheduled_decisions:99,models:{A:{mean_error:100,mae:100}}},
  {day:start+3*day,matched_decisions:1,scheduled_decisions:1,models:{A:{mean_error:10,mae:10}}},
 ]};
 const weeks=weeklyRows(data);
 expect(weeks).toHaveLength(3);
 expect(weeks[0].models.A.mean_error).toBe(3);
 expect(weeks[0].matched_decisions).toBe(5);
 expect(weeks[0].sampled_days).toBe(2);
 expect(weeks[0].poisoned).toBe(false);
 expect(weeks[1].models.A.mean_error).toBe(10);
 expect(weeks[1].poisoned).toBe(true);
 expect(weeks[2].models.A.mean_error).toBeNull();
});

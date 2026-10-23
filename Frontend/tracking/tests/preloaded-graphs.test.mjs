// @vitest-environment jsdom
import {readFileSync} from 'node:fs';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {createPreloadedGraphs,scenarioSettings,validateGraphBundle} from '../preloaded-graphs.mjs';

const controls=['reporting_gap','missing_speed','missing_course','missing_vessel_class','sensor_drift','location_drift','sensor_deterioration','position_jump'].map((id,index)=>({id,label:id,maximum:index?100:60,unit:index?'%':'min'}));
function result(mask){
 const models=Object.fromEntries(['A','B','C'].map(model=>[model,{mean_error:mask+1,mae:mask+1,clean_mean_error:1,clean_mae:1,unavailable_decisions:0}]));
 return {status:'ready',start:1709251200,end:1711929600,cutover:1710460800,period_label:'March 2024',poisoning_active:Boolean(mask),seed:4201,
  matched_decisions:1,scheduled_decisions:1,approaches:1,vessels:1,affected_reports:mask,
  days:[{day:1710547200,poisoned:Boolean(mask),models,matched_decisions:1,scheduled_decisions:1,approaches:1}],
  sequence:{samples:[],matched_instances:0,approaches:1,vessels:1},convergence:{samples:[],matched_decisions:0,scheduled_decisions:1,approaches:1},
  insights:{impact:{models:Object.fromEntries(['A','B','C'].map(model=>[model,{mae_clean:1,mae_scenario:mask+1,added_mae:mask}])),matched_decisions:1,scheduled_decisions:1},stability:{samples:[{minute:0,models:Object.fromEntries(['A','B','C'].map(model=>[model,{movement:{mean:0,p10:0,p90:0,clean_mean:0},updates:{mean:0,p10:0,p90:0,clean_mean:0}}]))}],instances:1,total_approaches:1,vessels:1,short_or_incomplete:0,unsupported:0}}};
}
beforeEach(()=>{
 document.documentElement.innerHTML=readFileSync('tracking/index.html','utf8').replace(/<!doctype html>/i,'').replace(/<\/?html[^>]*>/gi,'');
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});
});
const makeBundle=()=>({version:1,strength_fraction:.25,controls,scenarios:Object.fromEntries(Array.from({length:256},(_,mask)=>[mask,result(mask)])),stress:{status:'ready',samples:[],matched_decisions:0,scheduled_decisions:1,approaches:1}});
afterEach(()=>vi.unstubAllGlobals());

it('maps simultaneous attacks to one quarter of each real slider maximum',()=>{
 expect(scenarioSettings(65,controls)).toEqual({reporting_gap:15,sensor_deterioration:25});
 expect(scenarioSettings(255,controls)).toEqual(Object.fromEntries(controls.map(control=>[control.id,control.maximum/4])));
 expect(scenarioSettings(0,controls)).toEqual({});
});

it('requires all 256 genuine joint-scenario results rather than falling back to a single attack',()=>{
 const data=makeBundle();expect(validateGraphBundle(data)).toBe(data);
 delete data.scenarios[17];expect(()=>validateGraphBundle(data)).toThrow('scenario 17');
});

it('loads once and switches combined graph results without network requests',async()=>{
 document.documentElement.innerHTML=readFileSync('tracking/index.html','utf8').replace(/<!doctype html>/i,'').replace(/<\/?html[^>]*>/gi,'');
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});
 const fetcher=vi.fn(async()=>({ok:true,json:async()=>makeBundle()}));
 const root=document.getElementById('graph-scenarios'),graphs=createPreloadedGraphs(root,{fetcher});
 await vi.waitFor(()=>expect(root.querySelectorAll('input')).toHaveLength(8));
 const original=document.querySelector('#monthly-eta svg').innerHTML;
 root.querySelector('input[value="0"]').click();root.querySelector('input[value="6"]').click();
 expect(root.querySelector('[role=status]').textContent).toContain('reporting_gap + sensor_deterioration');
 expect(root.querySelectorAll('input:checked')).toHaveLength(2);
 expect(scenarioSettings(65,controls)).toEqual({reporting_gap:15,sensor_deterioration:25});
 expect(document.querySelector('#monthly-eta svg').innerHTML).not.toBe(original);
 expect(fetcher).toHaveBeenCalledTimes(1);
 root.querySelector('.scenario-reset').click();
 expect(root.querySelectorAll('input:checked')).toHaveLength(0);
 expect(root.querySelector('[role=status]').textContent).toContain('Clean reference');
 expect(fetcher).toHaveBeenCalledTimes(1);graphs.destroy();
});

it('shows a recoverable error for missing saved data and never requests live inference',async()=>{
 const fetcher=vi.fn(async()=>({ok:false})),root=document.getElementById('graph-scenarios');
 const graphs=createPreloadedGraphs(root,{fetcher});
 await vi.waitFor(()=>expect(root.querySelector('.scenario-retry').hidden).toBe(false));
 expect(root.querySelector('fieldset').disabled).toBe(true);
 expect(String(fetcher.mock.calls[0][0])).toContain('/data/scenarios.json');
 expect(fetcher).toHaveBeenCalledTimes(1);graphs.destroy();
});

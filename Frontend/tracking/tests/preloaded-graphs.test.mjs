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

it('toggles stability lines, endpoint labels and hover values independently across metrics and scenarios',async()=>{
 const graphs=createPreloadedGraphs(document.getElementById('graph-scenarios'),{fetcher:async()=>({ok:true,json:async()=>makeBundle()})});
 await vi.waitFor(()=>expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4));
 const panel=document.getElementById('forecast-stability'),plot=panel.querySelector('.insight-plot');
 const button=model=>panel.querySelector(`.insight-models [data-model="${model}"]`);
 const series=()=>[...panel.querySelectorAll('.stability-line')].map(line=>line.dataset.series);
 expect(series()).toEqual(['A','B','C']);
 for(const model of ['A','B']){button(model).click();expect(button(model).getAttribute('aria-pressed')).toBe('false');}
 expect(series()).toEqual(['C']);
 expect([...panel.querySelectorAll('.endpoint-label')].map(label=>label.textContent)).toEqual(['Antidote']);
 expect(panel.querySelectorAll('.spread-fill,.spread-edge,.series-dim')).toHaveLength(0);
 plot.dispatchEvent(new Event('focus'));
 expect([...panel.querySelectorAll('.monthly-inspector tbody tr')].map(row=>row.cells[0].textContent)).toEqual(['Antidote']);
 expect(panel.querySelectorAll('.insight-selection circle')).toHaveLength(1);
 panel.querySelector('[data-metric="updates"]').click();
 document.querySelector('#graph-scenarios input').click();
 expect(series()).toEqual(['C']);
 button('C').click();expect(series()).toEqual([]);
 expect(panel.querySelectorAll('.endpoint-label')).toHaveLength(0);
 button('A').click();expect(series()).toEqual(['A']);
 expect(button('A').getAttribute('aria-pressed')).toBe('true');
 graphs.destroy();
});

it('plots a full hour of stability and inspects the 60-minute endpoint in both metrics',async()=>{
 const bundle=JSON.parse(readFileSync('tracking/data/scenarios.json','utf8'));
 const graphs=createPreloadedGraphs(document.getElementById('graph-scenarios'),{fetcher:async()=>({ok:true,json:async()=>bundle})});
 await vi.waitFor(()=>expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4));
 const panel=document.getElementById('forecast-stability'),plot=panel.querySelector('.insight-plot');
 expect([...panel.querySelectorAll('svg text')].map(node=>node.textContent)).toContain('60');
 expect(panel.querySelector('svg').textContent).toContain('Minutes since first ETA');
 for(const metric of ['movement','updates']){
  panel.querySelector(`[data-metric="${metric}"]`).click();
  plot.dispatchEvent(new KeyboardEvent('keydown',{key:'End'}));
  expect(panel.querySelector('.monthly-inspector strong').textContent).toContain('Minute 60');
 }
 graphs.destroy();
});

it('keeps all four simulation hover tables without explanatory popup paragraphs',async()=>{
 const bundle=JSON.parse(readFileSync('tracking/data/scenarios.json','utf8'));
 const graphs=createPreloadedGraphs(document.getElementById('graph-scenarios'),{fetcher:async()=>({ok:true,json:async()=>bundle})});
 await vi.waitFor(()=>expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4));
 for(const id of ['monthly-eta','paired-impact','forecast-stability','arrival-convergence']){
  const panel=document.getElementById(id),plot=panel.querySelector('.monthly-plot,.insight-plot');
  plot.dispatchEvent(new Event('focus'));
  const inspector=panel.querySelector('.monthly-inspector');
  expect(inspector.hidden,id).toBe(false);
  expect(inspector.querySelector('table'),id).not.toBeNull();
  expect(inspector.textContent,id).not.toMatch(/simulation mode|assumed error changes|synthetic|hypothetical|no common supported/i);
  expect(inspector.querySelectorAll('p'),id).toHaveLength(0);
  plot.dispatchEvent(new Event('blur'));
 }
 graphs.destroy();
});

it('renders simulation only without a mode selector or repeated chart header labels',async()=>{
 const bundle=makeBundle(),source=JSON.stringify(bundle);
 const fetcher=vi.fn(async()=>({ok:true,json:async()=>bundle}));
 const root=document.getElementById('graph-scenarios'),graphs=createPreloadedGraphs(root,{fetcher});
 await vi.waitFor(()=>expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4));
 expect(document.querySelector('.graph-data-mode,.graph-mode-control')).toBeNull();
 expect(document.querySelectorAll('header[data-simulation]')).toHaveLength(0);
 expect(root.querySelector('.graph-data-disclosure').textContent).toContain('hypothetical');
 expect(document.querySelectorAll('#monthly-eta path[data-series]')).toHaveLength(3);
 const grouping=document.querySelector('.eta-grouping select');
 grouping.value='weekly';grouping.dispatchEvent(new Event('change'));
 expect(document.querySelector('#monthly-title').textContent).toBe('Weekly ETA error');
 for(const input of root.querySelectorAll('input'))input.click();
 expect(root.querySelectorAll('input:checked')).toHaveLength(8);
 expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4);
 expect(fetcher).toHaveBeenCalledTimes(1);
 expect(JSON.stringify(bundle)).toBe(source);
 graphs.destroy();
});
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
 const root=document.getElementById('graph-scenarios'),graphs=createPreloadedGraphs(root,{fetcher,initialMode:'measured'});
 await vi.waitFor(()=>expect(root.querySelectorAll('input')).toHaveLength(8));
 const original=document.querySelector('#monthly-eta svg').innerHTML;
 root.querySelector('input[value="0"]').click();root.querySelector('input[value="6"]').click();
 expect(root.querySelector('[role=status]').textContent).toContain('reporting_gap + sensor_deterioration');
 expect(root.querySelectorAll('input:checked')).toHaveLength(2);
 expect(document.querySelectorAll('#paired-impact .chart-cutover,#paired-impact .clean-line')).toHaveLength(0);
 expect(document.querySelector('#paired-impact .insight-key').hidden).toBe(true);
 expect(document.querySelectorAll('#paired-impact .impact-line')).toHaveLength(3);
 expect(scenarioSettings(65,controls)).toEqual({reporting_gap:15,sensor_deterioration:25});
 expect(document.querySelector('#monthly-eta svg').innerHTML).not.toBe(original);
 expect(fetcher).toHaveBeenCalledTimes(1);
 root.querySelector('.scenario-reset').click();
 expect(root.querySelectorAll('input:checked')).toHaveLength(0);
 expect(root.querySelector('[role=status]').textContent).toContain('Clean reference');
 expect(document.querySelectorAll('#paired-impact .impact-line')).toHaveLength(3);
 expect(document.querySelector('#paired-impact .monthly-loading').hidden).toBe(true);
 expect(fetcher).toHaveBeenCalledTimes(1);graphs.destroy();
});

it('shows a recoverable error for missing saved data and never requests live inference',async()=>{
 const fetcher=vi.fn(async()=>({ok:false})),root=document.getElementById('graph-scenarios');
 const graphs=createPreloadedGraphs(root,{fetcher,initialMode:'measured'});
 await vi.waitFor(()=>expect(root.querySelector('.scenario-retry').hidden).toBe(false));
 expect(root.querySelector('fieldset').disabled).toBe(true);
 expect(String(fetcher.mock.calls[0][0])).toContain('/data/scenarios.json');
 expect(fetcher).toHaveBeenCalledTimes(1);graphs.destroy();
});

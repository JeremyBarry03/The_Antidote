// @vitest-environment jsdom
import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';

it('boots the full fleet dashboard and loads all eight controls',async()=>{
 document.documentElement.innerHTML=readFileSync('tracking/index.html','utf8').replace(/<!doctype html>/i,'').replace(/<\/?html[^>]*>/gi,'');
 vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});
 vi.stubGlobal('requestAnimationFrame',()=>1);
 vi.stubGlobal('cancelAnimationFrame',()=>{});
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>String(url).includes('/data/scenarios.json')?JSON.parse(readFileSync('tracking/data/scenarios.json','utf8')):String(url).includes('/catalog')?
  {start:Date.UTC(2024,2,1)/1000,end:Date.UTC(2024,3,1)/1000-60,initial_time:Date.UTC(2024,2,1,0,15)/1000,evaluation_label:'March 2024',training_year:2023,model_c_variant:'C_nominal',windows:[],attack_controls:Array.from({length:8},(_,i)=>({id:'attack_'+i,label:'Attack '+i,maximum:100,unit:'%'}))}:
  {time:Date.UTC(2024,2,1,0,15)/1000,ships:[]}})));
 await import('../app.mjs');
 await vi.waitFor(()=>expect(document.querySelectorAll('#poison-controls input')).toHaveLength(8));
 expect(document.getElementById('mitigation-enabled')).toBeNull();
 expect(document.querySelector('#mitigation-help,#drift-direction,#trusted-fixes')).toBeNull();
 await vi.waitFor(()=>expect(fetch.mock.calls.some(([url])=>String(url).includes('/api/fleet/frame'))).toBe(true));
 const request=fetch.mock.calls.find(([url])=>String(url).includes('/api/fleet/frame'))[0];
 expect(new URL(request,'http://localhost').searchParams.get('mitigate')).not.toBe('false');
 expect(document.getElementById('error').hidden).toBe(true);
 expect(document.getElementById('play').disabled).toBe(true); // This fixture has no activity windows.
 expect(window.trackingConsole.getState().catalog.evaluation_label).toBe('March 2024');
 await vi.waitFor(()=>expect(document.querySelectorAll('[data-origin="simulation"]')).toHaveLength(4));
 expect(document.querySelector('.graph-data-mode')).toBeNull();
 expect(document.querySelector('#paired-impact').textContent).toContain('4.1 min');
 expect(document.getElementById('start-time').min).toBe('2024-03-01T00:00');
 expect(document.getElementById('end-time').max).toBe('2024-03-31T23:59');
});

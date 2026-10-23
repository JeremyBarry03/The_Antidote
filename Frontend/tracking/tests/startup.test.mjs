// @vitest-environment jsdom
import {readFileSync} from 'node:fs';
import {expect,it,vi} from 'vitest';

it('boots the full fleet dashboard and loads all eight controls',async()=>{
 document.documentElement.innerHTML=readFileSync('tracking/index.html','utf8').replace(/<!doctype html>/i,'').replace(/<\/?html[^>]*>/gi,'');
 vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});
 vi.stubGlobal('requestAnimationFrame',()=>1);
 vi.stubGlobal('cancelAnimationFrame',()=>{});
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,json:async()=>url.includes('/catalog')?
  {start:1712550000,end:1712559000,initial_time:1712554800,windows:[],attack_controls:Array.from({length:8},(_,i)=>({id:'attack_'+i,label:'Attack '+i,maximum:100,unit:'%'}))}:
  {time:1712554800,ships:[]}})));
 await import('../app.mjs');
 await vi.waitFor(()=>expect(document.querySelectorAll('#poison-controls input')).toHaveLength(8));
 expect(document.getElementById('mitigation-enabled')).toBeNull();
 expect(document.querySelector('#mitigation-help,#drift-direction,#trusted-fixes')).toBeNull();
 const request=fetch.mock.calls.find(([url])=>url.includes('/api/fleet/frame'))[0];
 expect(new URL(request,'http://localhost').searchParams.get('mitigate')).toBe('true');
 expect(document.getElementById('error').hidden).toBe(true);
 expect(document.getElementById('play').disabled).toBe(false);
});

// @vitest-environment jsdom
import {beforeEach,expect,it} from 'vitest';
import {fleetFrameURL,renderMitigations} from '../mitigations.mjs';
import {inputWarnings,AnomalyEpisodes} from '../anomalies.mjs';
import {FeedHistory} from '../feed-history.mjs';

function controls(){
 document.body.innerHTML='<details><summary id="mitigation-status"></summary><ul id="mitigation-results"></ul></details>';
}
beforeEach(()=>{document.body.replaceChildren();});

it('sends the selected experiment and mitigation options to the same fleet endpoint',()=>{
 const url=new URL(fleetFrameURL(123,{location_drift:60},{enabled:true,trusted_fixes:true,drift_direction:'over'}),'http://localhost');
 expect(url.pathname).toBe('/api/fleet/frame');
 expect(JSON.parse(url.searchParams.get('poisoning'))).toEqual({location_drift:60});
 expect(url.searchParams.get('mitigate')).toBe('true');
 expect(url.searchParams.get('trusted_fixes')).toBe('true');
 expect(url.searchParams.get('drift_direction')).toBe('over');
});

it('uses automatic Antidote defaults without auxiliary controls or simulated references',()=>{
 const url=new URL(fleetFrameURL(123,{location_drift:60}),'http://localhost');
 expect(url.searchParams.get('mitigate')).toBe('true');
 expect(url.searchParams.get('trusted_fixes')).toBe('false');
 expect(url.searchParams.get('drift_direction')).toBe('under');
});

it('renders actual strategy outcomes, conditional-reference labels, loading and error states',()=>{
 controls();
 const ship={mitigation:{enabled:true,reference_simulated:true,strategies:[
  {id:'location_drift',label:'Location drift',applied:true,requires_review:false,message:'3 positions estimated'},
  {id:'sensor_drift',label:'Speed drift',applied:false,requires_review:true,message:'Independent verification needed'}
 ]}};
 renderMitigations(document,ship);
 expect(document.getElementById('mitigation-status').textContent).toContain('estimates applied');
 expect(document.getElementById('mitigation-results').textContent).toContain('SIMULATED');
 renderMitigations(document,ship,{loading:true});
 expect(document.getElementById('mitigation-status').textContent).toContain('updating');
 expect(document.getElementById('mitigation-results').children).toHaveLength(0);
 renderMitigations(document,ship,{error:true});
 expect(document.getElementById('mitigation-status').textContent).toContain('unavailable');
 renderMitigations(document,{mitigation:{enabled:false}});
 expect(document.getElementById('mitigation-status').textContent).toContain('trained guard active');
});

it('shows corrections and review only for Antidote, never from simulator poison labels',()=>{
 const ship={id:'one',name:'Ship',arrived:false,diagnostics:{reasons:[]},predictions:{C:{available:true}},
  mitigation:{strategies:[{id:'sensor_drift',label:'Speed drift',applied:true,message:'2 readings estimated'}]}};
 expect(inputWarnings(ship)).toEqual([{code:'sensor_drift',text:'Speed drift: 2 readings estimated'}]);
 const notices=new AnomalyEpisodes();
 expect(notices.update([ship],'B')).toEqual([]);
 expect(notices.update([ship],'C')).toHaveLength(1);
 notices.dismiss(notices.update([ship],'C'));
 expect(notices.update([ship],'C')).toEqual([]);
 const raw={...ship,mitigation:undefined,reports:[{poisoned_fields:['speed']}]};
 expect(inputWarnings(raw)).toEqual([]);
});

it('updates retained feed estimates without changing displayed received measurements',()=>{
 const history=new FeedHistory();
 const report={record_id:'r',time:10,delivered:10,speed:7,course:270,longitude:-76,latitude:37};
 const ship={id:'one',name:'Ship',mmsi:'1',reports:[report]};
 history.ingest([ship],10);
 const revision=history.revision;
 history.ingest([{...ship,reports:[{...report,estimated_values:{speed:10}}]}],10);
 expect(history.revision).toBeGreaterThan(revision);
 expect(history.rows()[0].report.speed).toBe(7);
 expect(history.rows()[0].report.estimated_values.speed).toBe(10);
});

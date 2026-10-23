// @vitest-environment jsdom
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {setupArcDateTime} from '../arc-date-time.mjs';
import {inputWarnings} from '../anomalies.mjs';

function picker(start='2024-04-08T05:26',end='2024-04-21T20:41'){
 document.body.innerHTML='<input id="start-time" type="datetime-local"><input id="end-time" type="datetime-local">';
 const startInput=document.getElementById('start-time'),endInput=document.getElementById('end-time');
 for(const input of [startInput,endInput]){input.min=start;input.max=end;}
 startInput.value=start;endInput.value=end;
 return setupArcDateTime({startInput,endInput}).pickers[0];
}

beforeEach(()=>{vi.stubGlobal('matchMedia',()=>({matches:true}));});

describe('catalog-driven UTC dates',()=>{
 it('shows April dates and renders the real month and weekdays',()=>{
  const control=picker();
  expect(control.trigger.textContent).toContain('08 Apr 05:26');
  control.open();
  expect(control.panel.querySelector('[role="grid"]').getAttribute('aria-label')).toBe('April 2024');
  expect(control.panel.querySelectorAll('[data-date-day]')).toHaveLength(30);
  expect(control.panel.querySelector('.arc-date-week').children[0].className).toBe('arc-date-blank');
  expect(control.panel.querySelector('[data-date-previous]').disabled).toBe(true);
  expect(control.panel.querySelector('[data-date-next]').disabled).toBe(true);
 });
 it('applies a selected day without switching its month',()=>{
  const control=picker();control.open();
  const changed=vi.fn();control.input.addEventListener('change',changed);
  control.panel.querySelector('[data-date-day="10"]').click();
  control.panel.querySelector('[data-date-apply]').click();
  expect(control.input.value).toBe('2024-04-10T05:26');expect(changed).toHaveBeenCalledOnce();
 });
 it('supports leap February',()=>{
  const control=picker('2024-02-01T00:00','2024-02-29T23:59');control.open();
  expect(control.panel.querySelectorAll('[data-date-day]')).toHaveLength(29);
  expect(control.panel.querySelector('[data-date-day="29"]').getAttribute('aria-label')).toBe('29 February 2024');
 });
 it('navigates across a year boundary within catalog limits',()=>{
  const control=picker('2024-12-15T12:00','2025-01-20T12:00');control.open();
  control.panel.querySelector('[data-date-next]').click();
  expect(control.panel.querySelector('[role="grid"]').getAttribute('aria-label')).toBe('January 2025');
  expect(control.panel.querySelector('[data-date-next]').disabled).toBe(true);
  control.panel.querySelector('[data-date-day="10"]').click();control.panel.querySelector('[data-date-apply]').click();
  expect(control.input.value).toBe('2025-01-10T12:00');
 });
 it('rejects times outside the catalog bounds',()=>{
  const control=picker();control.open();
  const hour=control.panel.querySelector('.arc-date-hour');hour.value='00';hour.dispatchEvent(new Event('input'));
  expect(control.panel.querySelector('[data-date-apply]').disabled).toBe(true);
  expect(control.panel.querySelector('.arc-date-error').textContent).toContain('replay date range');
 });
});

it('shows reporting-gap warnings only from observed diagnostics and clears on recovery',()=>{
 const ship={arrived:false,predictions:{C:{available:true}},diagnostics:{reasons:['reporting_gap']}};
 expect(inputWarnings(ship)).toEqual([{code:'reporting_gap',text:'Reporting cadence interrupted'}]);
 expect(inputWarnings({...ship,diagnostics:{reasons:[]},reports:[{poisoned_fields:['speed']}]})).toEqual([]);
});

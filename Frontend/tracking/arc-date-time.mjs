/* UTC endpoint picker adapted from Arc UI's free DatePicker, Calendar and
 * TimePicker. Original source is retained in vendor/uiarc; see THIRD_PARTY_NOTICES.md.
 * Native datetime-local inputs remain the app's value and change-event contract. */
const pad=value=>String(value).padStart(2,'0');
const asTime=value=>/^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(value||'')?Date.parse(value.slice(0,16)+'Z'):NaN;
const chevron='<svg class="arc-date-chevron dropdown-chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>';
const clockIcon='<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5"/><path d="M8 4.5V8l2 1.5"/></svg>';
const reduce=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;

export function setupArcDateTime({startInput=document.getElementById('start-time'),endInput=document.getElementById('end-time')}={}){
 const inputs=[startInput,endInput].filter(Boolean),pickers=[];
 let current=null;
 for(const input of inputs){
  if(input.dataset.arcDateEnhanced)continue;
  const isStart=input===startInput,kind=isStart?'Start':'End',other=isStart?endInput:startInput;
  const trigger=document.createElement('button');trigger.type='button';trigger.className='arc-date-trigger';trigger.id=input.id+'-trigger';
  trigger.setAttribute('aria-label',`${kind} date and time, UTC`);trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-expanded','false');
  trigger.innerHTML='<span class="arc-date-value">Choose date</span>'+chevron;
  const panel=document.createElement('section');panel.id=input.id+'-picker';panel.className='arc-date-popover';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label',`${kind} date and time, UTC`);trigger.setAttribute('aria-controls',panel.id);
  panel.innerHTML=`<header class="arc-date-header"><span>${kind} date / time</span><span class="arc-date-zone">UTC</span></header><div class="arc-date-month">March 2024</div><div class="arc-date-calendar" role="grid" aria-label="March 2024"><div class="arc-date-weekdays" role="row">${['Su','Mo','Tu','We','Th','Fr','Sa'].map(day=>`<span role="columnheader">${day}</span>`).join('')}</div><div class="arc-date-weeks" role="rowgroup"></div></div><div class="arc-date-time-row">${clockIcon}<span id="${panel.id}-time-label">Time</span><div class="arc-date-time-fields" role="group" aria-labelledby="${panel.id}-time-label"><input class="arc-date-hour" type="text" inputmode="numeric" maxlength="2" pattern="[0-9]{1,2}" role="spinbutton" aria-label="${kind} hour, UTC" aria-valuemin="0" aria-valuemax="23" autocomplete="off"><span aria-hidden="true">:</span><input class="arc-date-minute" type="text" inputmode="numeric" maxlength="2" pattern="[0-9]{1,2}" role="spinbutton" aria-label="${kind} minute, UTC" aria-valuemin="0" aria-valuemax="59" autocomplete="off"></div><span class="arc-date-zone">24 h</span></div><p class="arc-date-error" role="status"></p><footer class="arc-date-footer"><button type="button" data-date-cancel aria-label="Cancel">Cancel</button><button type="button" data-date-apply aria-label="Apply">Apply</button></footer>`;
  const value=trigger.querySelector('.arc-date-value'),weeks=panel.querySelector('.arc-date-weeks'),hour=panel.querySelector('.arc-date-hour'),minute=panel.querySelector('.arc-date-minute'),apply=panel.querySelector('[data-date-apply]'),error=panel.querySelector('.arc-date-error');
  let draftDay=1,activeDay=1;
  const bounds=()=>({min:asTime(input.min)||Date.UTC(2024,2,1),max:asTime(input.max)||Date.UTC(2024,2,31,23,59)});
  const validPart=(field,max)=>/^\d{1,2}$/.test(field.value)&&Number(field.value)>=0&&Number(field.value)<=max;
  function candidate(){return validPart(hour,23)&&validPart(minute,59)?`2024-03-${pad(draftDay)}T${pad(Number(hour.value))}:${pad(Number(minute.value))}`:'';}
  function validate(){
   const raw=candidate(),time=asTime(raw),{min,max}=bounds(),otherTime=asTime(other?.value);let message='';
   if(!raw)message='Enter a valid 24-hour time.';
   else if(time<min||time>max)message='Choose a time within March 2024.';
   else if(Number.isFinite(otherTime)&&(isStart?time>=otherTime:time<=otherTime))message=isStart?'Start must be before end.':'End must be after start.';
   apply.disabled=Boolean(message);error.textContent=message;panel.dataset.invalid=String(Boolean(message));
   for(const [field,max]of [[hour,23],[minute,59]]){field.setAttribute('aria-invalid',String(!validPart(field,max)));if(validPart(field,max))field.setAttribute('aria-valuenow',String(Number(field.value)));else field.removeAttribute('aria-valuenow');}
   return !message;
  }
  function dayAllowed(day){const {min,max}=bounds();return Date.UTC(2024,2,day,23,59)>=min&&Date.UTC(2024,2,day)<=max;}
  function markDays(){for(const button of weeks.querySelectorAll('[data-date-day]')){const day=Number(button.dataset.dateDay);button.setAttribute('aria-selected',String(day===draftDay));button.tabIndex=day===activeDay&&!button.disabled?0:-1;}}
  function renderCalendar(){
   weeks.replaceChildren();let day=1;
   for(let week=0;week<6&&day<=31;week++){
    const row=document.createElement('div');row.className='arc-date-week';row.setAttribute('role','row');
    for(let column=0;column<7;column++){
     if((week===0&&column<5)||day>31){const blank=document.createElement('span');blank.className='arc-date-blank';blank.setAttribute('role','gridcell');row.append(blank);continue;}
     const button=document.createElement('button');button.type='button';button.setAttribute('role','gridcell');button.dataset.dateDay=day;button.textContent=day;button.setAttribute('aria-label',`${day} March 2024`);button.disabled=!dayAllowed(day);button.addEventListener('click',()=>{draftDay=activeDay=Number(button.dataset.dateDay);markDays();validate();});row.append(button);day++;
    }weeks.append(row);
   }markDays();
  }
  function position(){
   if(panel.hidden)return;const rect=trigger.getBoundingClientRect(),margin=12;
   panel.style.maxHeight=Math.max(80,innerHeight-margin*2)+'px';const box=panel.getBoundingClientRect(),below=innerHeight-rect.bottom-margin,above=rect.top-margin;
   const side=below>=box.height||below>=above?'bottom':'top';panel.dataset.side=side;
   panel.style.left=Math.max(margin,Math.min(innerWidth-margin-box.width,isStart?rect.left:rect.right-box.width))+'px';
   panel.style.top=Math.max(margin,Math.min(innerHeight-margin-box.height,side==='bottom'?rect.bottom+7:rect.top-box.height-7))+'px';
  }
  function close(restore=false){
   if(panel.hidden)return;panel.hidden=true;trigger.setAttribute('aria-expanded','false');if(current===picker)current=null;if(restore)trigger.focus({preventScroll:true});
  }
  function open(){
   if(input.disabled)return;current?.close();const parsed=new Date(asTime(input.value));const time=Number.isFinite(parsed.getTime())?parsed:new Date(Date.UTC(2024,2,isStart?1:31,isStart?0:23,isStart?0:59));
   draftDay=activeDay=time.getUTCDate();hour.value=pad(time.getUTCHours());minute.value=pad(time.getUTCMinutes());renderCalendar();validate();
   panel.hidden=false;trigger.setAttribute('aria-expanded','true');current=picker;document.dispatchEvent(new Event('arc-overlay-open'));position();
   if(!reduce())panel.animate([{opacity:0,transform:`translateY(${panel.dataset.side==='top'?4:-4}px) scale(.98)`},{opacity:1,transform:'none'}],{duration:150,easing:'cubic-bezier(.22,1,.36,1)'});
   weeks.querySelector(`[data-date-day="${activeDay}"]`)?.focus({preventScroll:true});
  }
  function sync(){
   trigger.disabled=input.disabled;const parsed=new Date(asTime(input.value));
   value.textContent=Number.isFinite(parsed.getTime())?`${pad(parsed.getUTCDate())} Mar ${pad(parsed.getUTCHours())}:${pad(parsed.getUTCMinutes())}`:'Choose date';
   trigger.setAttribute('aria-label',`${kind} date and time: ${value.textContent}, UTC`);
   if(input.disabled)close();else if(!panel.hidden)validate();
  }
  const picker={input,trigger,panel,open,close,sync,position};pickers.push(picker);
  trigger.addEventListener('click',()=>panel.hidden?open():close(true));
  trigger.addEventListener('keydown',event=>{if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();open();}else if(event.key==='Enter'||event.key===' '){event.preventDefault();panel.hidden?open():close(true);}else if(event.key==='Escape')close(true);});
  panel.querySelector('[data-date-cancel]').addEventListener('click',()=>close(true));
  apply.addEventListener('click',()=>{if(!validate())return;input.value=candidate();input.dispatchEvent(new Event('change',{bubbles:true}));sync();close(true);});
  weeks.addEventListener('keydown',event=>{
   const button=event.target.closest('[data-date-day]');if(!button)return;const day=Number(button.dataset.dateDay),weekday=new Date(Date.UTC(2024,2,day)).getUTCDay();
   if(event.key==='Enter'||event.key===' '){event.preventDefault();button.click();return;}
   const next=event.key==='ArrowRight'?day+1:event.key==='ArrowLeft'?day-1:event.key==='ArrowDown'?day+7:event.key==='ArrowUp'?day-7:event.key==='Home'?day-weekday:event.key==='End'?day+(6-weekday):null;
   if(next!=null){event.preventDefault();activeDay=Math.max(1,Math.min(31,next));if(dayAllowed(activeDay)){markDays();weeks.querySelector(`[data-date-day="${activeDay}"]`)?.focus({preventScroll:true});}else activeDay=day;}
  });
  for(const [field,max]of [[hour,23],[minute,59]]){
   field.addEventListener('input',validate);field.addEventListener('focus',()=>field.select());
   field.addEventListener('blur',()=>{if(validPart(field,max))field.value=pad(Number(field.value));});
   field.addEventListener('keydown',event=>{if(event.key==='ArrowUp'||event.key==='ArrowDown'){event.preventDefault();const old=validPart(field,max)?Number(field.value):0;field.value=pad((old+(event.key==='ArrowUp'?1:-1)+max+1)%(max+1));validate();}else if(event.key==='Enter'){event.preventDefault();if(validate())apply.click();}});
  }
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}});
  panel.addEventListener('focusout',event=>{
   // Pointer focus moves through blur before focus. A microtask can see <body>
   // during that gap and hide Apply before its click is delivered.
   if(panel.contains(event.relatedTarget)||event.relatedTarget===trigger)return;
   requestAnimationFrame(()=>{if(!panel.hidden&&!panel.contains(document.activeElement)&&document.activeElement!==trigger)close();});
  });
  input.addEventListener('change',()=>queueMicrotask(()=>pickers.forEach(p=>p.sync())));input.addEventListener('input',sync);
  const observer=new MutationObserver(sync);observer.observe(input,{attributes:true,attributeFilter:['disabled','min','max','value']});
  document.body.append(panel);input.insertAdjacentElement('afterend',trigger);input.classList.add('arc-date-native');input.dataset.arcDateEnhanced='true';input.tabIndex=-1;sync();
 }
 document.addEventListener('pointerdown',event=>{if(current&&!current.panel.contains(event.target)&&!current.trigger.contains(event.target))current.close();});
 window.addEventListener('resize',()=>current?.position());
 // Positioning uses live trigger geometry when the document or an ancestor scrolls.
 window.addEventListener('scroll',event=>{if(current&&!current.panel.contains(event.target))current.position();},true);
 return {sync:()=>pickers.forEach(picker=>picker.sync()),close:()=>current?.close(),pickers};
}

// Availability is navigation metadata, never an input to ETA prediction.
export function activityPeriods(windows,start,end){
 const periods=[];
 for(const window of windows??[]){
  if(!Number.isFinite(window.start)||!Number.isFinite(window.arrival))continue;
  const first=Math.ceil(Math.max(start,window.start)/60)*60;
  const stop=Math.min(end+1,window.arrival);
  if(first>=stop)continue;
  periods.push({start:first,end:stop,count:1});
 }
 periods.sort((a,b)=>a.start-b.start);
 const merged=[];
 for(const period of periods){
  const last=merged.at(-1);
  if(last&&period.start<=last.end){last.end=Math.max(last.end,period.end);last.count+=period.count;}
  else merged.push({...period});
 }
 return merged;
}

export function activityJump(periods,time,direction){
 if(direction>0)return periods.find(period=>period.start>time)?.start??null;
 return periods.findLast(period=>period.start<time)?.start??null;
}

export function setupActivityNavigation({track,previous,next,label,onSeek}){
 let periods=[],signature='';
 previous.addEventListener('click',()=>jump(-1));next.addEventListener('click',()=>jump(1));
 let clock=0;
 function jump(direction){const target=activityJump(periods,clock,direction);if(target!=null)void onSeek(target);}
 return {update(catalog,start,end,time){
  clock=time;
  const key=`${start}:${end}:${catalog?.windows.length??0}`;
  if(key!==signature){
   signature=key;periods=activityPeriods(catalog?.windows,start,end);track.replaceChildren();
   for(const period of periods){
    const mark=document.createElement('button');mark.type='button';mark.tabIndex=-1;mark.className='activity-period';
    const date=new Date(period.start*1000).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
    mark.title=`Ships present · ${date} UTC · ${period.count} approach${period.count===1?'':'es'}`;mark.setAttribute('aria-label',`Jump to ${mark.title}`);
    mark.style.left=(period.start-start)/(end-start)*100+'%';mark.style.width=(period.end-period.start)/(end-start)*100+'%';
    mark.addEventListener('click',()=>void onSeek(period.start));track.append(mark);
   }
  }
  previous.disabled=activityJump(periods,time,-1)==null;next.disabled=activityJump(periods,time,1)==null;
  label.title=`${periods.length} periods with vessels in this date range. Marks beneath the timeline show when ships are present.`;
 }};
}

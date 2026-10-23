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

// Piecewise elapsed time: every offset belongs to a real vessel window. UTC
// clocks and model inputs stay untouched; only navigation omits idle intervals.
export function activityTimeline(windows,start,end,{retention=0}={}){
 const periods=activityPeriods((windows??[]).map(window=>({...window,arrival:window.arrival+retention})),start,end);
 let total=0;
 const segments=periods.map(period=>{const segment={...period,offset:total};total+=period.end-period.start;return segment;});
 const maximum=Math.max(0,total-1);
 function timeAt(offset){
  if(!segments.length)return null;
  let remaining=Math.max(0,Math.min(maximum,Number.isFinite(offset)?offset:0));
  for(const segment of segments){const duration=segment.end-segment.start;if(remaining<duration)return segment.start+remaining;remaining-=duration;}
  return segments.at(-1).end-1;
 }
 function offsetAt(time){
  for(const segment of segments){
   if(time<segment.start)return segment.offset;
   if(time<segment.end)return Math.min(maximum,segment.offset+time-segment.start);
  }
  return maximum;
 }
 return {periods,segments,total,maximum,timeAt,offsetAt,
  snap:time=>timeAt(offsetAt(time)),advance:(time,seconds)=>timeAt(offsetAt(time)+seconds)};
}

export function setupActivityNavigation({track,previous,next,label,onSeek}){
 let periods=[],signature='';
 previous.addEventListener('click',()=>jump(-1));next.addEventListener('click',()=>jump(1));
 let clock=0;
 function jump(direction){const target=activityJump(periods,clock,direction);if(target!=null)void onSeek(target);}
 return {update(catalog,start,end,time,timeline){
  clock=time;
  const key=`${start}:${end}:${catalog?.windows.length??0}:${timeline?.total??''}`;
  if(key!==signature){
   signature=key;periods=timeline?.periods??activityPeriods(catalog?.windows,start,end);track.replaceChildren();
   for(const period of periods){
    const mark=document.createElement('button');mark.type='button';mark.tabIndex=-1;mark.className='activity-period';
    const date=new Date(period.start*1000).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
    mark.title=`Ships present · ${date} UTC · ${period.count} approach${period.count===1?'':'es'}`;mark.setAttribute('aria-label',`Jump to ${mark.title}`);
    mark.style.left=(timeline?timeline.offsetAt(period.start)/timeline.total:(period.start-start)/(end-start))*100+'%';mark.style.width=(period.end-period.start)/(timeline?.total??(end-start))*100+'%';
    mark.addEventListener('click',()=>void onSeek(period.start));track.append(mark);
   }
  }
  previous.disabled=activityJump(periods,time,-1)==null;next.disabled=activityJump(periods,time,1)==null;
  label.title=timeline?`${periods.length} vessel activity periods. Empty intervals are omitted; the UTC clock jumps between periods. Arrival animations remain included.`:`${periods.length} periods with vessels in this date range. Marks beneath the timeline show when ships are present.`;
 }};
}

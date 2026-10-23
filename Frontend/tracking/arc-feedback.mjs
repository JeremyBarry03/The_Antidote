/* Native adapters for Arc UI's free Badge, Skeleton, EmptyState, Alert and
   ScrollArea. Original references are retained in vendor/uiarc/; see the
   attribution note there and THIRD_PARTY_NOTICES.md. No report data is changed. */
export function createArcFeedback(root=document){
 const panel=root.querySelector('.feed-table-wrap'),status=root.querySelector('#feed-status'),empty=root.querySelector('#feed-empty'),error=root.querySelector('#error'),retry=root.querySelector('#retry');
 if(!panel||!status||!empty||!error||!retry)throw new Error('Arc feedback requires the existing replay feed and retry controls.');
 const table=panel.querySelector('table'),body=panel.querySelector('tbody'),reduce=matchMedia('(prefers-reduced-motion: reduce)');
 const state={loading:true,hasFrame:false,playing:false,rate:null,error:null};
 let scheduled=0,disposed=false,labelAnimation=null;

 panel.classList.add('arc-feed-scroll');panel.tabIndex=0;panel.setAttribute('role','region');panel.setAttribute('aria-labelledby','feed-title');panel.setAttribute('aria-describedby','feed-note');
 status.classList.remove('sr-only');status.classList.add('arc-feed-badge');status.setAttribute('aria-live','polite');status.setAttribute('aria-atomic','true');

 // Keep the app's source node intact: renderFeed owns its hidden flag and text.
 // The view follows that node rather than inserting extra rows in the table.
 empty.classList.add('arc-feed-empty-source');empty.setAttribute('aria-hidden','true');
 const emptyView=document.createElement('section');emptyView.className='arc-feed-empty-view';emptyView.hidden=true;emptyView.setAttribute('aria-label','Replay feed is empty');
 emptyView.innerHTML='<div class="arc-empty-glyph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6.5h16v13H4zM8 3.5h8M8 10.5h8M8 14.5h5"/></svg></div><h3>No received reports</h3><p></p>';
 panel.append(emptyView);
 const skeleton=document.createElement('div');skeleton.className='arc-feed-skeleton';skeleton.setAttribute('role','status');skeleton.setAttribute('aria-label','Loading received ship reports');skeleton.setAttribute('aria-busy','true');skeleton.hidden=true;
 const skeletonShapes=document.createElement('div');skeletonShapes.className='arc-skeleton-lines';skeletonShapes.setAttribute('aria-hidden','true');
 for(let i=0;i<6;i++){const line=document.createElement('span');line.style.setProperty('--arc-line-index',i);skeletonShapes.append(line);}skeleton.append(skeletonShapes);panel.append(skeleton);

 error.classList.add('arc-feedback-error');
 const message=error.querySelector('span'),copy=document.createElement('div'),title=document.createElement('h3');copy.className='arc-alert-copy';title.className='arc-alert-title';title.textContent='Replay unavailable';
 const alertIcon=document.createElementNS('http://www.w3.org/2000/svg','svg');alertIcon.classList.add('arc-alert-icon');alertIcon.setAttribute('viewBox','0 0 24 24');alertIcon.setAttribute('aria-hidden','true');alertIcon.innerHTML='<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5.5M12 16h.01"/>';
 copy.append(title,message);error.prepend(alertIcon,copy);retry.classList.add('arc-retry-button');

 function syncScroll(){
  scheduled=0;if(disposed)return;
  const overflow=panel.scrollHeight>panel.clientHeight+1;
  panel.dataset.overflow=String(overflow);panel.dataset.scrollStart=String(panel.scrollTop<=1);panel.dataset.scrollEnd=String(panel.scrollTop+panel.clientHeight>=panel.scrollHeight-1);
 }
 function scheduleScroll(){if(!scheduled&&!disposed)scheduled=requestAnimationFrame(syncScroll);}
 function syncEmpty(){
  const initial=!state.hasFrame&&!state.error;
  emptyView.hidden=initial||!!state.error||empty.hidden;
  const text=empty.textContent.trim().replace(/^No received reports at this replay time\.\s*/,'');if(emptyView.querySelector('p').textContent!==text)emptyView.querySelector('p').textContent=text;
  scheduleScroll();
 }
 function update(next={}){
  Object.assign(state,next);
  const initial=!state.hasFrame&&!state.error;
  const retrying=!!state.error&&state.loading;
  const label=retrying?'Retrying':state.error?(state.hasFrame?'Interrupted':'Unavailable'):initial?'Loading':state.loading&&!state.playing?'Updating':state.playing?'Receiving':'Paused';
  const rate=Number.isFinite(state.rate)&&state.rate>0?state.rate.toLocaleString('en-US',{maximumFractionDigits:8}):'';
  const text=label+(!state.error&&!initial&&rate?` · ${rate}×`:'');
  if(status.textContent!==text){
   status.textContent=text;labelAnimation?.cancel();
   if(!reduce.matches&&status.animate)labelAnimation=status.animate([{opacity:.45,transform:'translateY(2px)'},{opacity:1,transform:'none'}],{duration:160,easing:'cubic-bezier(.22,1,.36,1)'});
  }
  status.dataset.state=state.error?'error':initial?'loading':state.playing?'playing':'paused';
  status.setAttribute('aria-label',`Replay feed: ${text}`);
  panel.dataset.phase=initial?'loading':state.error?'error':'ready';panel.setAttribute('aria-busy',String(initial));skeleton.hidden=!initial;
  title.textContent=state.hasFrame?'Replay needs attention':'Replay unavailable';
  retry.disabled=retrying;retry.textContent=retrying?'Retrying…':'Retry';retry.setAttribute('aria-busy',String(retrying));
  syncEmpty();
 }
 const emptyObserver=new MutationObserver(syncEmpty);emptyObserver.observe(empty,{attributes:true,attributeFilter:['hidden'],childList:true,subtree:true,characterData:true});
 const rowsObserver=new MutationObserver(scheduleScroll);if(body)rowsObserver.observe(body,{childList:true,subtree:true});
 const resize=typeof ResizeObserver==='function'?new ResizeObserver(scheduleScroll):null;resize?.observe(panel);if(table)resize?.observe(table);
 panel.addEventListener('scroll',scheduleScroll,{passive:true});
 const onReduce=()=>{if(reduce.matches)labelAnimation?.cancel();};reduce.addEventListener('change',onReduce);
 update();
 return {update,refresh:syncEmpty,destroy(){disposed=true;cancelAnimationFrame(scheduled);labelAnimation?.cancel();emptyObserver.disconnect();rowsObserver.disconnect();resize?.disconnect();reduce.removeEventListener('change',onReduce);panel.removeEventListener('scroll',scheduleScroll);emptyView.remove();skeleton.remove();}};
}

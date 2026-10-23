import {setupAppearance} from './appearance.mjs';
import {arrivalVisual} from './arrival.mjs';
import {FleetMotion} from './fleet-motion.mjs';
import {deliveredReports,trailGeometry,poisonedFields} from './geometry.mjs';
import {FeedHistory} from './feed-history.mjs';
import {StableCalloutLayout,calloutPath} from './callout.mjs';
import {createArcSelect,enhanceArcGroup,enhanceArcDisclosure,enhanceArcDialog,setupArcTooltips,enhanceArcSlider,setArcPlayIcon} from './arc-components.mjs';
import {setupArcDateTime} from './arc-date-time.mjs';
import {createArcFeedback} from './arc-feedback.mjs';
import {createPoisoningControls} from './poisoning-controls.mjs';
import {createAnomalyNotice} from './anomalies.mjs';
import {createEtaComparison} from './eta-comparison.mjs';
import {setupActivityNavigation} from './activity.mjs';
import {fleetFrameURL,renderMitigations} from './mitigations.mjs?v=fleet-mitigations-2';
const $=id=>document.getElementById(id);
const names={A:'Poly',B:'XGBoost',C:'Antidote'};
const state={catalog:null,frame:null,time:0,start:0,end:0,model:'C',playing:false,speedMultiplier:1,expanded:false,selected:null,busy:false,version:0,mapReady:false,loadedMinute:null,failedMinute:null,feedSignature:'',error:null,poisoning:{},appliedPoisoningSignature:null,pendingPoisoning:false};
const motion=new FleetMotion(), markers=new Map(),callouts=new Map(),feedHistory=new FeedHistory();
const presentationShips=new Map();
const calloutLayout=new StableCalloutLayout();
const feedPanel=document.querySelector('.feed-table-wrap');
const feedback=createArcFeedback();
const anomalyNotice=createAnomalyNotice($('antidote-alert'));
const comparison=createEtaComparison({select:$('comparison-vessel'),body:$('comparison-body'),empty:$('comparison-empty'),stamp:$('comparison-stamp'),note:$('comparison-note'),onSelect:selectShip});
const activity=setupActivityNavigation({track:$('activity-track'),previous:$('previous-ships'),next:$('next-ships'),label:$('activity-label'),onSeek:async time=>{await seek(time);fit();}});
let feedRestoreScroll=null;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const map=()=>window.coastalPreview?.map;
const number=(value,digits=1)=>value!=null&&Number.isFinite(value)?value.toFixed(digits):'—';
const clock=(value,seconds=false)=>value!=null&&Number.isFinite(value)?new Date(value*1000).toLocaleTimeString('en-GB',{timeZone:'UTC',hour:'2-digit',minute:'2-digit',...(seconds?{second:'2-digit'}:{})}):'—';
const fullClock=value=>new Date(value*1000).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const localInput=value=>new Date(value*1000).toISOString().slice(0,16);
async function api(path){const response=await fetch(path);const data=await response.json();if(!response.ok)throw Error(data.error||'Replay unavailable.');return data;}
function syncFeedback(){feedback.update({loading:state.busy,hasFrame:!!state.frame,playing:state.playing,rate:replayRate(),error:state.error});}
function showError(error){state.error=error;$('error').hidden=!error;$('error').querySelector('span').textContent=error?.message??'';syncFeedback();}
const replayRate=()=>10*state.speedMultiplier;
function renderSpeed(){
 const rate=replayRate(),format=value=>value.toLocaleString('en-US',{maximumFractionDigits:8});
 $('replay-speed').textContent=`${format(rate)}×`;$('replay-speed').title=`${format(rate)}×`;$('replay-speed').setAttribute('aria-label',`${format(rate)} times playback`);
 $('speed-boost').dataset.arcTooltip=`Double to ${format(rate*2)}×`;
 $('speed-slow').dataset.arcTooltip=`Slow to ${format(rate/2)}×`;
 syncFeedback();
}
function multiplySpeed(factor){const next=state.speedMultiplier*factor;if(Number.isFinite(next)&&next>0){state.speedMultiplier=next;renderSpeed();}}
function playback(playing){state.playing=playing;renderSpeed();setArcPlayIcon($('play'),playing);$('play').setAttribute('aria-label',playing?'Pause replay':'Play replay');$('play').dataset.arcTooltip=playing?'Pause replay':'Play replay';if(!playing&&state.frame){drawTrails();updateMarkers();}}
function shipVisual(ship){return arrivalVisual(ship,state.time,{reducedMotion:reduced.matches,arrivalTime:motion.arrivalTime(ship.id)});}
function visibleShips(){return [...presentationShips.values()].filter(ship=>shipVisual(ship).phase!=='complete'&&deliveredReports(ship,state.time).length);}
function renderClock(){if(!state.catalog)return;const full=`${fullClock(state.time)} UTC`;$('clock').textContent=new Date(state.time*1000).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}).replace(',','')+' UTC';$('clock').setAttribute('aria-label',full);$('clock').title=full;$('clock').dateTime=new Date(state.time*1000).toISOString();$('scrub').value=String(state.time);$('scrub').setAttribute('aria-valuetext',`${fullClock(state.time)} UTC`);const fraction=(state.time-state.start)/(state.end-state.start||1);const progress=Math.max(0,Math.min(1,fraction))*100+'%';document.querySelector('.timeline .timeline-thumb').style.left=progress;document.querySelector('.timeline .scrubber').style.setProperty('--progress',progress);}
function renderPopup(){
 const ships=visibleShips(),ids=new Set(ships.map(ship=>ship.id));
 for(const [id,entry] of callouts)if(!ids.has(id)){entry.popup.remove();entry.shape.remove();callouts.delete(id);}
 for(const ship of ships){
  let entry=callouts.get(ship.id);
  if(!entry){
   const popup=$('ship-popup-template').content.firstElementChild.cloneNode(true),shape=document.createElementNS('http://www.w3.org/2000/svg','path');
   popup.dataset.ship=ship.id;shape.dataset.ship=ship.id;
   entry={popup,shape,parts:Object.fromEntries([...popup.querySelectorAll('[data-part]')].map(el=>[el.dataset.part,el]))};
   callouts.set(ship.id,entry);$('ship-popups').append(popup);$('ship-callouts').append(shape);
   popup.addEventListener('click',event=>event.stopPropagation());
   entry.parts['ship-name'].addEventListener('click',()=>selectShip(ship.id));
  }
  const label=entry.parts['ship-name'];label.textContent=ship.name;
  label.setAttribute('aria-label',`Select ${ship.name}`);
  label.setAttribute('aria-pressed',String(state.selected===ship.id));
  entry.popup.title=`${ship.name} · MMSI ${ship.mmsi}`;
  entry.popup.classList.toggle('selected',state.selected===ship.id);
 }
 positionPopups();
}
function positionPopups(){
 const {width,height}=$('coastal-map').parentElement.getBoundingClientRect();
 const project=coordinates=>state.mapReady?map().project(coordinates):fallbackProject(coordinates,width,height);
 const ships=visibleShips().map(ship=>({ship,pose:motion.pose(ship.id)})).filter(item=>item.pose).map(item=>({...item,anchor:project(item.pose.position)}));
 const svg=$('ship-callouts');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
 const layoutItems=[];
 for(const {ship,pose,anchor} of ships){
  const entry=callouts.get(ship.id);if(!entry)continue;
  const {popup,shape}=entry,onscreen=anchor.x>=0&&anchor.x<=width&&anchor.y>=0&&anchor.y<=height;
  popup.hidden=!onscreen;shape.toggleAttribute('hidden',!onscreen);if(!onscreen)continue;
  layoutItems.push({id:ship.id,anchor,width:popup.offsetWidth,height:popup.offsetHeight,heading:pose.heading-(state.mapReady?map().getBearing():0)});
 }
 const placements=calloutLayout.layout(layoutItems,{width,height});
 for(const {ship,anchor} of ships){
  const placement=placements.get(ship.id);if(!placement)continue;
  const {popup,shape}=callouts.get(ship.id);
  popup.style.left=placement.x+'px';popup.style.top=placement.y+'px';popup.dataset.side=placement.side;popup.dataset.slot=placement.slot;
  const {path,tip}=calloutPath(placement);shape.setAttribute('d',path);shape.dataset.anchorX=anchor.x;shape.dataset.anchorY=anchor.y;shape.dataset.tipX=tip.x;shape.dataset.tipY=tip.y;
  const fade=String(shipVisual(ship).opacity);popup.style.opacity=fade;shape.style.opacity=fade;
 }
}
function renderComparison(){
 const frame=state.frame?{...state.frame,ships:visibleShips()}:null;
 comparison.update(frame,state.selected);
 const selected=$('comparison-vessel').value;
 renderMitigations(document,frame?.ships.find(ship=>ship.id===selected),{loading:state.pendingPoisoning,error:!!state.error});
}
function selectShip(id){state.selected=id;renderPopup();renderFeed();updateMarkers();renderComparison();}
function feedRowHeight(){const cell=feedPanel.querySelector('tr[data-ship] td');return cell?.getBoundingClientRect().height||parseFloat(getComputedStyle(feedPanel).getPropertyValue('--feed-row-height'))||30;}
function resetFeed(){feedHistory.clear();state.feedSignature='';feedPanel.scrollTop=0;feedRestoreScroll=null;renderFeed();}
function collectFeed(frame){
 const oldRows=feedHistory.rows(),rowHeight=feedRowHeight();
 if(feedPanel.scrollTop>rowHeight){
  const index=Math.floor(feedPanel.scrollTop/rowHeight),entry=oldRows[index];
  if(entry)feedRestoreScroll={key:entry.key,offset:feedPanel.scrollTop-index*rowHeight};
 }
 feedHistory.ingest(frame.ships,frame.time);
}
function renderFeed(){
 const reports=feedHistory.rows(),rowHeight=feedRowHeight();
 let scroll=feedPanel.scrollTop;
 if(feedRestoreScroll){const index=reports.findIndex(entry=>entry.key===feedRestoreScroll.key);if(index>=0)scroll=index*rowHeight+feedRestoreScroll.offset;}
 // Keep a long native scrollbar while rendering only its visible rows. History
 // has no report cap, and scrolling can reach every accumulated observation.
 const start=Math.max(0,Math.floor(scroll/rowHeight)-8);
 const end=Math.min(reports.length,start+Math.ceil(feedPanel.clientHeight/rowHeight)+18);
 const signature=`${feedHistory.revision}:${state.selected}:${start}:${end}:${rowHeight}`;
 if(signature===state.feedSignature)return;state.feedSignature=signature;
 const body=$('feed-body'),fragment=document.createDocumentFragment();
 const spacer=count=>{if(!count)return;const row=document.createElement('tr'),cell=document.createElement('td');row.className='feed-spacer';row.setAttribute('aria-hidden','true');cell.colSpan=6;cell.style.height=(count*rowHeight)+'px';row.append(cell);fragment.append(row);};
 spacer(start);
 for(const {ship,report,key} of reports.slice(start,end)){
  const row=document.createElement('tr');row.tabIndex=0;row.dataset.ship=ship.id;row.dataset.report=key;row.classList.toggle('withheld',Boolean(report.withheld));row.classList.toggle('selected',ship.id===state.selected);row.title=`${ship.name} · MMSI ${ship.mmsi}${report.withheld?' · Report withheld by simulated reporting gap; measurements were not delivered':''} · click to inspect`;row.setAttribute('aria-label',`${ship.name}, ${new Date(report.time*1000).toISOString()}. View arrival details.`);
  const fields=poisonedFields(report);
  for(const [field,value] of [['time',report.withheld?`${clock(report.time)} gap`:clock(report.time,true)],['speed',number(report.speed)],['longitude',number(report.longitude,4)],['latitude',number(report.latitude,4)],['course',number(report.course,0)],['vessel_type',number(report.vessel_type,0)]]){
   const cell=document.createElement('td');cell.textContent=value;cell.dataset.field=field;
   if(fields.has(field)){
    const original=field==='longitude'?report.original_longitude:field==='latitude'?report.original_latitude:report.original_values?.[field];
    cell.className='poisoned';cell.title=report.withheld?'Report withheld · simulator audit; no measurement was delivered':`Poisoned ${field} · ${(report.attack_names??[]).join(', ')||'simulator audit'}${original!=null?` · original ${number(original,field==='longitude'||field==='latitude'?4:1)}`:''}`;
    cell.setAttribute('aria-label',report.withheld?`${field}: report withheld, simulator audit`:`${field} ${value}, poisoned data`);
   }
   const estimate=report.estimated_values?.[field];
   if(estimate!=null){cell.classList.add('has-estimate');cell.title+=(cell.title?' · ':'')+`Antidote estimate: ${number(estimate,field==='longitude'||field==='latitude'?4:1)}. Displayed value is the received reading.`;cell.setAttribute('aria-label',`${field}: received ${value}; Antidote estimate ${estimate}`);}
   row.append(cell);
  }
  row.addEventListener('click',()=>selectShip(ship.id));row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectShip(ship.id);}});fragment.append(row);
 }
 spacer(reports.length-end);body.replaceChildren(fragment);
 if(feedRestoreScroll){feedPanel.scrollTop=scroll;feedRestoreScroll=null;}
 $('feed-empty').hidden=reports.length>0;$('feed-empty').textContent='No received reports at this replay time. Scrub the timeline to another time.';
 $('feed-note').textContent=`${reports.length.toLocaleString()} accumulated reports · newest first · UTC. Speeds are in knots. Red cells are audited modifications. Red rows with dashes are withheld-report audit events, not received measurements.`;
}
feedPanel.addEventListener('scroll',()=>renderFeed(),{passive:true});
async function loadFrame({snap=false}={}){
 if(state.busy&&!snap)return;const version=++state.version;state.busy=true;const requested=Math.floor(state.time/60)*60;
 syncFeedback();
 const settings={...state.poisoning},scenarioSignature=JSON.stringify(settings);
 const frameURL=time=>fleetFrameURL(time,settings);
 try{
  const frame=await api(frameURL(state.time));if(version!==state.version)return;
  // Constrain the displayed stream to what was delivered at this frame.
  frame.ships=frame.ships.map(ship=>({...ship,reports:deliveredReports(ship,frame.time)}));
  // A response finishing after Pause must retain the frozen display cursor and
  // completed-arrival state. Only an explicit seek/refresh snaps the scene.
  const continuous=!snap&&!reduced.matches,ids=new Set(frame.ships.map(ship=>ship.id));
  if(!continuous)presentationShips.clear();
  const missing=[...presentationShips.values()].filter(ship=>!ids.has(ship.id)&&ship.arrival<=frame.time&&!ship.crossing_position);
  // Very high playback speeds can skip the server's short arrived-vessel window.
  // Recover only the already-past terminal frame, never future reports, so that
  // a known boat can finish its real route instead of vanishing mid-animation.
  const times=[...new Set(missing.map(ship=>Math.floor(ship.arrival/60)*60+60))];
  const terminalFrames=await Promise.all(times.map(time=>api(frameURL(time))));
  if(version!==state.version)return;
  const terminalShips=missing.map(ship=>terminalFrames.flatMap(frame=>frame.ships).find(item=>item.id===ship.id)).filter(Boolean).map(ship=>({...ship,reports:deliveredReports(ship,frame.time)}));
  for(const ship of terminalShips)presentationShips.set(ship.id,ship);
  for(const [id,ship]of presentationShips)if(!ids.has(id)&&(ship.arrival>frame.time||shipVisual(ship).phase==='complete'))presentationShips.delete(id);
  for(const ship of frame.ships)presentationShips.set(ship.id,ship);
  if(state.appliedPoisoningSignature!==scenarioSignature){resetFeed();anomalyNotice.reset();state.appliedPoisoningSignature=scenarioSignature;}
  collectFeed({...frame,ships:[...frame.ships,...terminalShips]});state.frame=frame;state.loadedMinute=requested;state.failedMinute=null;state.feedSignature='';
  motion.update([...presentationShips.values()],continuous,state.time);showError(null);renderAll();$('play').disabled=false;renderSpeed();
 }catch(error){if(version!==state.version)return;playback(false);state.failedMinute=requested;showError(error);renderComparison();}
 finally{if(version===state.version){state.busy=false;syncFeedback();}}
}
function renderAll(){renderClock();renderFeed();renderPopup();drawTrails();updateMarkers();anomalyNotice.update(state.frame?.ships??[],state.model);renderComparison();activity.update(state.catalog,state.start,state.end,state.time);}
function setupMap(){if(state.mapReady)return;state.mapReady=true;calloutLayout.clear();const m=map();m.addSource('fleet-trails',{type:'geojson',data:trailGeometry([],motion,state.time)});m.addLayer({id:'fleet-dots',type:'circle',source:'fleet-trails',paint:{'circle-radius':1.3,'circle-color':getComputedStyle(document.documentElement).getPropertyValue('--map-dot').trim(),'circle-opacity':['get','fade']}});m.on('move',()=>renderPopup());m.on('moveend',()=>{calloutLayout.clear();renderPopup();});m.on('click',e=>{if(e.originalEvent.target.closest('.ship-marker'))return;state.selected=null;renderPopup();renderFeed();updateMarkers();});$('fallback-map').hidden=true;drawTrails();updateMarkers();if(state.frame)fit();}
function drawTrails(){if(state.mapReady)map().getSource('fleet-trails')?.setData(trailGeometry(visibleShips(),motion,state.time));else drawFallback();}
const SHIP='<svg viewBox="-7 -14 14 28" aria-hidden="true"><path class="ship-hull" d="M0-12C-3-10-5-5-5 2L-4 10H4L5 2C5-5 3-10 0-12Z" fill="var(--ink)" stroke="var(--muted)" stroke-width="1" stroke-linejoin="round"/><path class="ship-deck" d="M-2 3H2V7H-2Z" fill="var(--map-bg)" opacity=".55"/></svg>';
function updateMarkers(){
 if(!state.mapReady)return;const ships=visibleShips(),ids=new Set(ships.map(s=>s.id));
 for(const [id,entry] of markers)if(!ids.has(id)){entry.marker.remove();markers.delete(id);}
 for(const ship of ships){const pose=motion.pose(ship.id);if(!pose)continue;let entry=markers.get(ship.id);
  if(!entry){const el=document.createElement('button');el.className='ship-marker';el.innerHTML=SHIP;el.setAttribute('aria-label',`View ${ship.name} arrival details`);el.title=`${ship.name} · ${ship.mmsi}`;el.addEventListener('click',e=>{e.stopPropagation();selectShip(ship.id);});const marker=new mapboxgl.Marker({element:el,rotationAlignment:'map'}).setLngLat(pose.position).addTo(map());entry={marker,el};markers.set(ship.id,entry);}
  entry.marker.setLngLat(pose.position).setRotation(pose.heading);
  const visual=shipVisual(ship);
  entry.el.dataset.arrivalPhase=visual.phase;
  for(const [key,value] of Object.entries({'opacity':visual.opacity,'marker-scale':visual.markerScale,'ring-scale':visual.ringScale,'ring-opacity':visual.ringOpacity}))entry.el.style.setProperty('--arrival-'+key,String(value));
  entry.el.classList.toggle('selected',state.selected===ship.id);entry.el.setAttribute('aria-pressed',String(state.selected===ship.id));
 }
 if(state.selected&&!ids.has(state.selected))state.selected=null;
 if(ships.length!==callouts.size)renderPopup();else positionPopups();
}
let bounds=[-76.58,36.85,-75.98,37.15];
function fallbackProject(position,width,height){const [west,south,east,north]=bounds;return{x:35+(position[0]-west)/(east-west)*(width-70),y:50+(north-position[1])/(north-south)*(height-125)};}
function drawFallback(){
 if(!state.frame||state.mapReady)return;const svg=$('fallback-map');svg.hidden=false;const {width,height}=svg.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.replaceChildren();
 const el=(tag,attrs,text)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;svg.append(node);return node;};
 for(let i=0;i<=4;i++){const x=35+i*(width-70)/4,y=50+i*(height-125)/4;el('path',{d:`M${x} 50V${height-75}M35 ${y}H${width-35}`,stroke:'var(--border)',fill:'none'});el('text',{x,y:height-58,fill:'var(--muted)','font-size':11},`${(bounds[0]+i*(bounds[2]-bounds[0])/4).toFixed(2)}°`);}
 for(const feature of trailGeometry(visibleShips(),motion,state.time).features){const p=fallbackProject(feature.geometry.coordinates,width,height);el('circle',{cx:p.x,cy:p.y,r:1.3,fill:'var(--map-dot)',opacity:feature.properties.fade});}
 for(const ship of visibleShips()){
  const pose=motion.pose(ship.id);if(!pose)continue;
  const p=fallbackProject(pose.position,width,height),visual=shipVisual(ship);
  if(visual.ringOpacity)el('circle',{cx:p.x,cy:p.y,r:11*visual.ringScale,fill:'none',stroke:'var(--muted)',opacity:visual.ringOpacity});
  const g=el('g',{transform:`translate(${p.x} ${p.y}) rotate(${pose.heading})`,tabindex:0,role:'button','aria-label':`View ${ship.name} arrival details`,style:'cursor:pointer',opacity:visual.opacity});
  g.innerHTML=`<circle r="15" fill="transparent"/><g transform="scale(${visual.markerScale})"><path d="M0 -12 6 -3 5 10 -5 10 -6 -3Z" fill="var(--ink)" stroke="var(--map-bg)" stroke-width="1.5"/><path d="M-3 3H3M0 -4V7" stroke="var(--ground)"/></g>`;
  g.addEventListener('click',()=>selectShip(ship.id));g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectShip(ship.id);}});
 }
 $('map-status').textContent='Coordinate view · coastal basemap unavailable';$('map-status').hidden=false;
}
function fit(){const points=visibleShips().flatMap(s=>deliveredReports(s,state.time).map(r=>[r.longitude,r.latitude]));if(!points.length)return;if(state.mapReady){const box=new mapboxgl.LngLatBounds();points.forEach(p=>box.extend(p));map().fitBounds(box,{padding:{top:75,bottom:85,left:65,right:65},maxZoom:11,duration:reduced.matches?0:600});}else{const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);bounds=[Math.min(...xs)-.025,Math.min(...ys)-.025,Math.max(...xs)+.025,Math.max(...ys)+.025];drawFallback();}}
window.replayPreview={fit};
const modelSelect=createArcSelect({trigger:$('model'),menu:$('model-menu'),label:$('model-name'),getValue:()=>state.model,onChange:model=>{state.model=model;renderAll();}});
const closeModels=(restore=false)=>modelSelect.close(restore);
$('play').addEventListener('click',async()=>{if(state.time>=state.end){await seek(state.start);}playback(!state.playing);});
async function seek(time){playback(false);anomalyNotice.reset();clearTimeout(scrubTimer);state.pendingSeek=false;calloutLayout.clear();resetFeed();state.time=Math.max(state.start,Math.min(state.end,time));renderClock();await loadFrame({snap:true});}
let scrubTimer;$('scrub').addEventListener('input',()=>{playback(false);state.version++;state.busy=false;state.pendingSeek=true;anomalyNotice.reset();calloutLayout.clear();resetFeed();state.time=Number($('scrub').value);renderClock();clearTimeout(scrubTimer);scrubTimer=setTimeout(()=>{state.pendingSeek=false;void loadFrame({snap:true});},100);});
for(const id of ['start-time','end-time'])$(id).addEventListener('change',()=>{
 const start=Date.parse($('start-time').value+'Z')/1000,end=Date.parse($('end-time').value+'Z')/1000;
 if(!Number.isFinite(start)||!Number.isFinite(end)||start>=end||start<state.catalog.start||end>state.catalog.end){showError(Error('Choose a start before the end, within March 2024 (UTC).'));$('start-time').value=localInput(state.start);$('end-time').value=localInput(state.end);endpointPickers.sync();return;}
 state.start=start;state.end=end;$('scrub').min=start;$('scrub').max=end;void seek(Math.max(start,Math.min(end,state.time)));
});
const endpointPickers=setupArcDateTime();
function setExpanded(expanded){
 if(expanded)endpointPickers.close();
 state.expanded=expanded;
 $('map-console').classList.toggle('is-expanded',expanded);
 $('map-backdrop').hidden=!expanded;
 document.body.classList.toggle('map-expanded',expanded);
 for(const element of document.querySelectorAll('.timeline,.poison-panel,.feed-column,#error'))element.inert=expanded;
 $('map-console').setAttribute('role',expanded?'dialog':'region');
 if(expanded)$('map-console').setAttribute('aria-modal','true');else $('map-console').removeAttribute('aria-modal');
 $('fullscreen').setAttribute('aria-expanded',String(expanded));
 $('fullscreen').classList.toggle('collapse-icon',expanded);$('fullscreen').dataset.arcTooltip=expanded?'Collapse map':'Expand map';
 $('fullscreen').setAttribute('aria-label',expanded?'Collapse map':'Expand map');
 resize();$('fullscreen').focus({preventScroll:true});
}
$('fullscreen').addEventListener('click',()=>setExpanded(!state.expanded));
$('map-backdrop').addEventListener('click',()=>setExpanded(false));
$('speed-boost').addEventListener('click',()=>multiplySpeed(2));
$('speed-slow').addEventListener('click',()=>multiplySpeed(.5));
function resize(){$('map-console').classList.toggle('compact-toolbar',$('map-console').clientWidth<560);map()?.resize();renderPopup();drawFallback();renderFeed();}
for(const [toggleId,contentId,panelId] of [['feed-toggle','feed-content','live-feed'],['comparison-toggle','comparison-content','eta-comparison']]){
 $(toggleId).addEventListener('click',()=>{
  const expanded=$(toggleId).getAttribute('aria-expanded')!=='true';
  $(toggleId).setAttribute('aria-expanded',String(expanded));$(contentId).hidden=!expanded;$(panelId).classList.toggle('is-collapsed',!expanded);
  if(!expanded&&$(contentId).contains(document.activeElement))$(toggleId).focus();
  state.feedSignature='';renderFeed();
 });
}
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'){
  if(!$('model-menu').hidden){e.preventDefault();closeModels(true);return;}
  if(state.expanded){setExpanded(false);return;}
  if(!$('method-dialog').open){state.selected=null;renderPopup();}
 }
 if(e.key==='Tab'&&state.expanded){
  const controls=[...$('map-console').querySelectorAll('button:not(:disabled),select,[tabindex="0"]')].filter(el=>el.getClientRects().length);
  const first=controls[0],last=controls.at(-1);
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
 }
});
new ResizeObserver(resize).observe($('coastal-map'));
let poisonTimer;
function scenarioChanged(){
 state.version++;state.busy=false;state.pendingPoisoning=true;state.failedMinute=null;
 anomalyNotice.reset();renderComparison();clearTimeout(poisonTimer);
 poisonTimer=setTimeout(()=>{state.pendingPoisoning=false;void loadFrame({snap:true});},180);
}
const poisoningControls=createPoisoningControls({container:$('poison-controls'),
 onExplain:control=>{document.dispatchEvent(new Event('arc-overlay-open'));$('method-title').textContent=control.label;$('method-description').textContent=control.description;$('method-dialog').showModal();},
 onChange:settings=>{
  state.poisoning=settings;scenarioChanged();
 },
});
enhanceArcSlider($('scrub'));
setArcPlayIcon($('play'),false);
for(const id of ['zoom-in','zoom-out','recenter','fullscreen','speed-boost','speed-slow']){const button=$(id);button.dataset.arcTooltip=button.title||button.getAttribute('aria-label')||button.textContent;button.removeAttribute('title');}
enhanceArcGroup(document.querySelector('.navigation'));
enhanceArcGroup(document.querySelector('.replay-transport'));
enhanceArcDisclosure($('poison-panel'),{fixed:true});
enhanceArcDialog($('method-dialog'));
setupArcTooltips();
setupAppearance({button:$('invert'),onChange:()=>{if(state.mapReady&&map().getLayer('fleet-dots'))map().setPaintProperty('fleet-dots','circle-color',getComputedStyle(document.documentElement).getPropertyValue('--map-dot').trim());drawFallback();}});
$('close-dialog').addEventListener('click',()=>$('method-dialog').close());$('method-dialog').addEventListener('click',e=>{if(e.target===$('method-dialog')){const r=$('method-dialog').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('method-dialog').close();}});
$('retry').addEventListener('click',()=>state.catalog?void loadFrame({snap:true}):void start());
window.addEventListener('coastal-ready',setupMap,{once:true});if(window.coastalPreview?.getState().ready)setupMap();
let last=0,lastDraw=0,lastRequest=0,raf;
function tick(now){
 const delta=last?Math.max(0,(now-last)/1000):0;last=now;
 if(state.playing&&state.catalog){
  const before=state.time;state.time=Math.min(state.end,state.time+delta*replayRate());
  motion.advance(state.time-before);renderClock();
  if(state.time>=state.end)playback(false);
 }
 // The replay clock never waits for inference. Keep one request in flight and
 // coalesce intermediate clocks when the requested playback rate is very high.
 const minute=Math.floor(state.time/60)*60;
 if(state.catalog&&!state.busy&&!state.pendingSeek&&!state.pendingPoisoning&&minute!==state.loadedMinute&&minute!==state.failedMinute&&now-lastRequest>=150){lastRequest=now;void loadFrame();}
 if(now-lastDraw>100){lastDraw=now;drawTrails();updateMarkers();renderFeed();activity.update(state.catalog,state.start,state.end,state.time);if(!state.mapReady)renderPopup();}
 raf=requestAnimationFrame(tick);
}
async function start(){try{showError(null);state.catalog=await api('/api/fleet/catalog');state.poisoning=poisoningControls.configure(state.catalog.attack_controls);state.start=state.catalog.start;state.end=state.catalog.end;state.time=state.catalog.initial_time;for(const id of ['start-time','end-time']){$(id).disabled=false;$(id).min=localInput(state.catalog.start);$(id).max=localInput(state.catalog.end);}$('start-time').value=localInput(state.start);$('end-time').value=localInput(state.end);endpointPickers.sync();$('scrub').disabled=false;$('scrub').min=state.start;$('scrub').max=state.end;$('scrub').step='60';await loadFrame({snap:true});if(state.frame){playback(true);setTimeout(fit,900);}}catch(error){showError(error);$('feed-empty').textContent='The replay could not connect. Use Retry to reconnect.';}}
// Replay scenarios use the repository attacks; display-only audit labels never enter model inputs.
window.trackingConsole={getState:()=>({...state,feedCount:feedHistory.size,motion:undefined}),selectShip,seek,fit,refresh:()=>loadFrame({snap:true})};
window.addEventListener('pagehide',()=>{cancelAnimationFrame(raf);clearTimeout(poisonTimer);clearTimeout(scrubTimer);playback(false);for(const entry of markers.values())entry.marker.remove();},{once:true});
raf=requestAnimationFrame(tick);void start();

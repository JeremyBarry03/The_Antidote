// Arrival is the dataset's analytical harbor crossing, not a docking event.
// Keep each ship visible for eight replay minutes so the next approach can
// enter before this one fades out. Cleanup follows replay time, never wall time.
export const ARRIVAL_RETENTION_SECONDS = 480;
const clamp = value => Math.max(0, Math.min(1, value));
const smooth = value => {const t=clamp(value);return t*t*(3-2*t);};

export function arrivalVisual(ship,time,{reducedMotion=false,arrivalTime=ship?.arrival}={}) {
  const elapsed=Number.isFinite(arrivalTime)&&Number.isFinite(time)?time-arrivalTime:-1;
  if(elapsed<0)return {phase:'underway',progress:0,markerScale:1,opacity:1,ringScale:1,ringOpacity:0,trailStartFraction:0};
  const progress=clamp(elapsed/ARRIVAL_RETENTION_SECONDS);
  if(progress>=1)return {phase:'complete',progress:1,markerScale:reducedMotion?1:0,opacity:0,ringScale:1,ringOpacity:0,trailStartFraction:1};
  const acknowledgement=clamp(elapsed/64),finish=smooth(progress);
  return {
    phase:elapsed<64?'arriving':progress<1?'fading':'clearing',
    progress,
    markerScale:reducedMotion?1:(1-.08*Math.sin(Math.PI*acknowledgement))*(1-.12*finish),
    opacity:1-finish,
    ringScale:reducedMotion?1:.75+1.45*smooth(acknowledgement),
    ringOpacity:reducedMotion?0:.58*smooth(elapsed/8)*(1-smooth(acknowledgement)),
    trailStartFraction:smooth(progress),
  };
}

// Remove the oldest part of the route by distance, not report count. An
// interpolated tail endpoint keeps sparse AIS tracks from disappearing in
// whole segments; the latest point stays exactly where the vessel is shown.
export function retractTrail(coordinates,startFraction) {
  if(!coordinates.length)return [];
  const fraction=Number.isFinite(startFraction)?clamp(startFraction):0;
  if(fraction<=0)return coordinates.slice();
  if(fraction>=1)return [];
  if(coordinates.length===1)return coordinates.slice();
  const lengths=coordinates.slice(1).map((point,index)=>{
    const before=coordinates[index],longitude=(point[0]-before[0])*Math.cos((point[1]+before[1])*Math.PI/360);
    return Math.hypot(longitude,point[1]-before[1]);
  });
  const total=lengths.reduce((sum,length)=>sum+length,0);
  if(!total)return [coordinates.at(-1)];
  let remaining=total*fraction;
  for(let index=1;index<coordinates.length;index++){
    const length=lengths[index-1];
    if(length>0&&remaining<length){
      const before=coordinates[index-1],point=coordinates[index],t=remaining/length;
      if(t<1e-10)return coordinates.slice(index-1);
      if(t>1-1e-10)return coordinates.slice(index);
      const tail=[before[0]+(point[0]-before[0])*t,before[1]+(point[1]-before[1])*t];
      return [tail,...coordinates.slice(index)];
    }
    remaining-=length;
  }
  return [coordinates.at(-1)];
}

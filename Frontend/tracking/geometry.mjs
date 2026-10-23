import {arrivalVisual,retractTrail} from './arrival.mjs';
export const valid = r => Number.isFinite(r.longitude) && Number.isFinite(r.latitude) && Math.abs(r.longitude) <= 180 && Math.abs(r.latitude) < 85;
export function deliveredReports(ship, time) {
  return (ship.reports ?? []).filter(r => valid(r) && r.time <= time && r.delivered <= time).slice().sort((a,b) => a.delivered-b.delivered || a.time-b.time);
}
export function recentReports(ships, time, limit=32) {
  return ships.flatMap(ship=>deliveredReports(ship,time).map(report=>({ship,report})))
    .sort((a,b)=>b.report.delivered-a.report.delivered || b.report.time-a.report.time || a.ship.id.localeCompare(b.ship.id))
    .slice(0,limit);
}
export function trailGeometry(ships, motion, time) {
  return {type:'FeatureCollection',features:ships.flatMap(ship => {
    const visual=arrivalVisual(ship,time,{arrivalTime:motion.arrivalTime?.(ship.id)??ship.arrival}),fade=visual.opacity;
    if (!fade) return [];
    return retractTrail(motion.track(ship.id),visual.trailStartFraction).map(position => ({type:'Feature',geometry:{type:'Point',coordinates:position},properties:{id:ship.id,fade}}));
  })};
}
export function feedReports(ship,time){
 const withheld=(ship.audit_events??[]).filter(report=>report.withheld&&Number.isFinite(report.time)&&Number.isFinite(report.delivered)&&report.time<=time&&report.delivered<=time);
 return [...deliveredReports(ship,time),...withheld];
}
// Explicit audit fields are authoritative. Legacy `altered` means displacement.
export function poisonedFields(report) {
  return new Set(Array.isArray(report.poisoned_fields)?report.poisoned_fields:report.altered?['longitude','latitude']:[]);
}

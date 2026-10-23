import {feedReports} from './geometry.mjs';

// Retain observations across arriving/departing vessels for the current replay.
// Seeking starts a new history; repeated frames update existing reports.
export class FeedHistory {
  entries = new Map();
  revision = 0;
  ordered = [];
  dirty = false;

  clear() {
    this.entries.clear();this.ordered=[];this.dirty=false;this.revision++;
  }

  ingest(ships, time) {
    let changed=false;
    for(const ship of ships)for(const report of feedReports(ship,time)){
      const key=report.record_id?JSON.stringify([ship.id,report.record_id]):JSON.stringify([ship.id,report.time,report.delivered,
        report.longitude,report.latitude,report.speed,report.course]);
      const audit=JSON.stringify([report.longitude,report.latitude,report.speed,report.course,report.vessel_type,report.withheld,
        report.altered,report.poisoned_fields,report.attack_names,report.original_values,report.original_longitude,report.original_latitude,report.estimated_values]);
      const old=this.entries.get(key);
      if(old?.audit===audit)continue;
      this.entries.set(key,{key,audit,report:{...report},ship:{id:ship.id,name:ship.name,mmsi:ship.mmsi}});
      changed=true;
    }
    if(changed){this.dirty=true;this.revision++;}
  }

  rows() {
    if(this.dirty){
      this.ordered=[...this.entries.values()].sort((a,b)=>b.report.delivered-a.report.delivered
        ||b.report.time-a.report.time||a.ship.id.localeCompare(b.ship.id));
      this.dirty=false;
    }
    return this.ordered;
  }

  get size(){return this.entries.size;}
}

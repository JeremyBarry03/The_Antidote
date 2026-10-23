/** @typedef {{id:string,arrival:number,arrived?:boolean,crossing_position?:[number,number],reports:Array<{delivered:number,longitude:number,latitude:number,course?:number}>}} FleetShip */
/** @typedef {{at:number,position:[number,number],heading:number}} MotionPoint */
/** @typedef {{points:MotionPoint[],cursor:number,clock:number,arrivalRate:number,arrivedAt?:number,arrival:number,destination:boolean}} MotionState */

/** Interpolate display positions only within reports already delivered.
 * The replay clock advances the cursor; pausing needs no independent timer.
 * This layer never changes a report, forecast, or scoring input. */
export class FleetMotion {
  /** @type {Map<string,MotionState>} */ states = new Map();

  /** @param {FleetShip[]} ships @param {boolean} continuous @param {number} [replayTime] */
  update(ships, continuous, replayTime) {
    const visible = new Set();
    for (const ship of ships) {
      if (!ship.reports.length) continue;
      visible.add(ship.id);
      // AIS position fixes can wander slightly from one report to the next.
      // Apply a short, causal smoothing window to the display path so the boat
      // does not twitch, while leaving reports and every model input untouched.
      const points = ship.reports.map((report, index) => {
        const previous = ship.reports[index - 1];
        const older = ship.reports[index - 2];
        const weights = previous && older ? [0.6, 0.28, 0.12] : previous ? [0.72, 0.28] : [1];
        const samples = [report, ...(previous ? [previous] : []), ...(older ? [older] : [])];
        const position = /** @type {[number,number]} */ ([0, 0]);
        let headingX = 0, headingY = 0;
        samples.forEach((sample, sampleIndex) => {
          position[0] += sample.longitude * weights[sampleIndex];
          position[1] += sample.latitude * weights[sampleIndex];
          const heading = (sample.course ?? 270) * Math.PI / 180;
          headingX += Math.sin(heading) * weights[sampleIndex];
          headingY += Math.cos(heading) * weights[sampleIndex];
        });
        return {
          at: report.delivered,
          position,
          heading: (Math.atan2(headingX, headingY) * 180 / Math.PI + 360) % 360,
        };
      });
      if (ship.arrived && ship.crossing_position) {
        const last = points.at(-1);
        if (last&&(last.position[0]!==ship.crossing_position[0]||last.position[1]!==ship.crossing_position[1]))
          points.push({
            at: Math.max(last.at + 1, ship.arrival),
            position: ship.crossing_position,
            heading: last.heading,
          });
      }
      const last = points.at(-1);
      if (!last) continue;
      const previous = this.states.get(ship.id);
      const cursor=continuous&&previous?Math.max(points[0].at,Math.min(previous.cursor,last.at)):last.at;
      const destination=Boolean(ship.arrived&&ship.crossing_position);
      // A sparse/delayed report stream can leave the display cursor behind the
      // recorded crossing. Finish that known route in at most 64 replay seconds,
      // then start arrival cleanup at the actual displayed endpoint.
      const arrivalRate=destination&&continuous&&previous
        ? previous.destination?previous.arrivalRate:Math.max(1,(last.at-cursor)/64)
        : 1;
      const clock=Number.isFinite(replayTime)?replayTime:previous?.clock??last.at;
      const arrivedAt=destination
        ? !continuous||!previous?ship.arrival:previous.arrivedAt??(cursor>=last.at?Math.max(ship.arrival,clock):undefined)
        : undefined;
      this.states.set(ship.id, {
        points,
        cursor,clock,arrivalRate,arrivedAt,arrival:ship.arrival,destination,
      });
    }
    for (const id of this.states.keys())
      if (!visible.has(id)) this.states.delete(id);
  }

  /** @param {number} seconds */
  advance(seconds) {
    for (const state of this.states.values()) {
      const last = state.points.at(-1);
      const delta=Math.max(0,seconds),before=state.cursor;
      if (last) {
        state.cursor = Math.min(last.at, before + delta*state.arrivalRate);
        if(state.destination&&state.arrivedAt===undefined&&state.cursor>=last.at)
          state.arrivedAt=Math.max(state.arrival,state.clock+(last.at-before)/state.arrivalRate);
      }
      state.clock+=delta;
    }
  }

  /** The replay time the visible boat reached its endpoint; Infinity while underway. */
  arrivalTime(id) {return this.states.get(id)?.arrivedAt??Infinity;}

  /** @param {string} id */
  pose(id) {
    const state = this.states.get(id);
    if (!state) return null;
    let index = state.points.findIndex((point) => point.at > state.cursor);
    if (index < 0) index = state.points.length;
    const before = state.points[Math.max(0, index - 1)];
    const after = state.points[index] ?? before;
    const span = after.at - before.at;
    const t =
      span > 0
        ? Math.max(0, Math.min(1, (state.cursor - before.at) / span))
        : 0;
    const turn = ((after.heading - before.heading + 540) % 360) - 180;
    return {
      position: /** @type {[number,number]} */ ([
        before.position[0] + (after.position[0] - before.position[0]) * t,
        before.position[1] + (after.position[1] - before.position[1]) * t,
      ]),
      heading: (before.heading + turn * t + 360) % 360,
      index,
    };
  }

  /** @param {string} id @returns {[number,number][]} */
  track(id) {
    const state = this.states.get(id),
      pose = this.pose(id);
    if (!state || !pose) return [];
    const points = state.points
      .slice(0, pose.index)
      .map((point) => point.position);
    if (pose.index < state.points.length) points.push(pose.position);
    return points.length ? points : [pose.position];
  }
}

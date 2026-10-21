/** @import {FleetShip} from './fleet-types.js' */
/** @typedef {{at:number,position:[number,number],heading:number}} MotionPoint */
/** @typedef {{points:MotionPoint[],cursor:number}} MotionState */

/** Interpolate display positions only within reports already delivered.
 * The replay clock advances the cursor; pausing needs no independent timer.
 * This layer never changes a report, forecast, or scoring input. */
export class FleetMotion {
  /** @type {Map<string,MotionState>} */ states = new Map();

  /** @param {FleetShip[]} ships @param {boolean} continuous */
  update(ships, continuous) {
    const visible = new Set();
    for (const ship of ships) {
      if (!ship.reports.length) continue;
      visible.add(ship.id);
      const points = ship.reports.map((report) => ({
        at: report.delivered,
        position: /** @type {[number,number]} */ ([
          report.longitude,
          report.latitude,
        ]),
        heading: report.course ?? 270,
      }));
      if (ship.arrived && ship.crossing_position) {
        const last = points.at(-1);
        if (last)
          points.push({
            at: Math.max(last.at + 1, ship.arrival),
            position: ship.crossing_position,
            heading: last.heading,
          });
      }
      const last = points.at(-1);
      if (!last) continue;
      const previous = this.states.get(ship.id);
      this.states.set(ship.id, {
        points,
        cursor:
          continuous && previous
            ? Math.max(points[0].at, Math.min(previous.cursor, last.at))
            : last.at,
      });
    }
    for (const id of this.states.keys())
      if (!visible.has(id)) this.states.delete(id);
  }

  /** @param {number} seconds */
  advance(seconds) {
    for (const state of this.states.values()) {
      const last = state.points.at(-1);
      if (last)
        state.cursor = Math.min(last.at, state.cursor + Math.max(0, seconds));
    }
  }

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

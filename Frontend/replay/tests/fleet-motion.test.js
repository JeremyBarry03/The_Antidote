import { describe, expect, it } from "vitest";
import { FleetMotion } from "../fleet-motion.js";

/** @param {number[]} times @returns {import('../fleet-types.js').FleetShip} */
function vessel(times) {
  return /** @type {import('../fleet-types.js').FleetShip} */ (
    /** @type {unknown} */ ({
      id: "ship",
      arrived: false,
      arrival: 240,
      crossing_position: null,
      reports: times.map((time, index) => ({
        time: time - 60,
        delivered: time,
        longitude: index,
        latitude: index * 2,
        course: index ? 10 : 350,
      })),
    })
  );
}

describe("Delivered vessel motion", () => {
  it("glides between received positions and turns across north by the short arc", () => {
    const motion = new FleetMotion();
    motion.update([vessel([0])], false);
    motion.update([vessel([0, 120])], true);
    motion.advance(60);
    expect(motion.pose("ship")?.position).toEqual([0.5, 1]);
    expect(motion.pose("ship")?.heading).toBe(0);
    expect(motion.track("ship")).toEqual([
      [0, 0],
      [0.5, 1],
    ]);
  });
  it("stops at the latest delivered report without extrapolating a future route", () => {
    const motion = new FleetMotion();
    motion.update([vessel([0])], false);
    motion.update([vessel([0, 120])], true);
    motion.advance(1000);
    expect(motion.pose("ship")?.position).toEqual([1, 2]);
    expect(motion.track("ship")).toEqual([
      [0, 0],
      [1, 2],
    ]);
  });
  it("keeps motion progress when a frame or model selection renders again", () => {
    const motion = new FleetMotion();
    motion.update([vessel([0])], false);
    motion.update([vessel([0, 120])], true);
    motion.advance(30);
    motion.update([vessel([0, 120, 240])], true);
    motion.advance(0);
    expect(motion.pose("ship")?.position).toEqual([0.25, 0.5]);
    motion.advance(120);
    expect(motion.pose("ship")?.position).toEqual([1.25, 2.5]);
  });
  it("snaps on a seek, fault reset, or reduced-motion frame and removes departed ships", () => {
    const motion = new FleetMotion();
    motion.update([vessel([0])], false);
    motion.update([vessel([0, 120])], false);
    expect(motion.pose("ship")?.position).toEqual([1, 2]);
    motion.update([], true);
    expect(motion.pose("ship")).toBeNull();
  });
  it("adds the crossing point only once its arrival is revealed", () => {
    const motion = new FleetMotion(),
      ship = vessel([0, 120]);
    ship.crossing_position = [2, 4];
    motion.update([ship], false);
    expect(motion.track("ship")).toEqual([
      [0, 0],
      [1, 2],
    ]);
    ship.arrived = true;
    motion.update([ship], true);
    motion.advance(60);
    expect(motion.pose("ship")?.position).toEqual([1.5, 3]);
  });
});

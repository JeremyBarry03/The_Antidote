import { describe, expect, it } from "vitest";
import { score, sampleFrame } from "../fleet-charts.js";

/** @param {string} id @param {number} value */
const item = (id, value) => ({
  id,
  errors: { A: value, B: value * 2, C: value / 2 },
});

describe("Fleet comparison evidence", () => {
  it("weights each approach equally even when it has more replay frames", () => {
    const samples = [
      { time: 0, cases: [item("frequent", 10), item("sparse", 0)] },
      { time: 60, cases: [item("frequent", 10)] },
    ];
    expect(score(samples, "A", "mae")).toBe(5);
    expect(score(samples, "A", "mse")).toBe(50);
    expect(score(samples, "A", "rmse")).toBeCloseTo(Math.sqrt(50));
  });
  it("preserves the units and sign handling of absolute and squared error", () => {
    const samples = [
      { time: 0, cases: [item("vessel", -4)] },
      { time: 60, cases: [item("vessel", 2)] },
    ];
    expect(score(samples, "A", "mae")).toBe(3);
    expect(score(samples, "A", "mse")).toBe(10);
    expect(score([], "A", "mae")).toBeNull();
  });
  it("excludes unsupported and already-crossed cases without turning missing output into zero", () => {
    const supported = {
      A: { available: true, error: 2, eta: 1 },
      B: { available: true, error: 3, eta: 1 },
      C: { available: true, error: 1, eta: 1 },
    };
    const frame = /** @type {import('../fleet-types.js').FleetFrame} */ (
      /** @type {unknown} */ ({
        time: 1,
        ships: [
          { id: "valid", arrived: false, predictions: supported },
          {
            id: "missing",
            arrived: false,
            predictions: {
              ...supported,
              C: { available: false, error: null, eta: null },
            },
          },
          { id: "arrived", arrived: true, predictions: supported },
        ],
      })
    );
    expect(sampleFrame(frame).cases.map((record) => record.id)).toEqual([
      "valid",
    ]);
  });
});

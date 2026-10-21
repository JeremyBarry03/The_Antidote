/** @import {FleetFrame, Metric, ScoreSample} from './fleet-types.js' */
/** @import {SystemName} from './types.js' */
export const MODELS = /** @type {const} */ ([
  { id: "A", name: "Regression", color: "#96601b" },
  { id: "B", name: "XGBoost", color: "#446bb3" },
  { id: "C", name: "The Antidote", color: "#00776a" },
]);
/** @param {number} seconds @param {boolean} [withSeconds] */
export function utcClock(seconds, withSeconds = false) {
  return new Date(seconds * 1000).toLocaleTimeString("en-GB", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}
/** Equal approach weight, using the same supported cases for every model.
 * @param {ScoreSample[]} samples @param {SystemName} model @param {Metric} metric */
export function score(samples, model, metric) {
  /** @type {Map<string,number[]>} */ const byApproach = new Map();
  for (const sample of samples)
    for (const item of sample.cases) {
      const list = byApproach.get(item.id) ?? [];
      list.push(item.errors[model]);
      byApproach.set(item.id, list);
    }
  if (!byApproach.size) return null;
  const perApproach = [...byApproach.values()].map(
    (errors) =>
      errors.reduce(
        (sum, value) => sum + (metric === "mae" ? Math.abs(value) : value ** 2),
        0,
      ) / errors.length,
  );
  const mean =
    perApproach.reduce((sum, value) => sum + value, 0) / perApproach.length;
  return metric === "rmse" ? Math.sqrt(mean) : mean;
}
/** @param {FleetFrame} frame @returns {ScoreSample} */
export function sampleFrame(frame) {
  return {
    time: frame.time,
    cases: frame.ships
      .filter(
        (ship) =>
          !ship.arrived &&
          MODELS.every(
            (model) =>
              ship.predictions[model.id].available &&
              Number.isFinite(ship.predictions[model.id].error),
          ),
      )
      .map((ship) => ({
        id: ship.id,
        errors: {
          A: /** @type {number} */ (ship.predictions.A.error),
          B: /** @type {number} */ (ship.predictions.B.error),
          C: /** @type {number} */ (ship.predictions.C.error),
        },
      })),
  };
}

export class FleetCharts {
  /** @type {ScoreSample[]} */ samples = [];
  /** @type {FleetFrame|null} */ frame = null;
  /** @type {Metric} */ metric = "mae";
  /** @param {HTMLElement} container */
  constructor(container) {
    this.container = container;
    container.innerHTML = MODELS.map(
      (model) =>
        `<article class="comparison-chart" style="--chart-color:${model.color}" data-chart="${model.id}"><div class="comparison-chart-header"><span class="model-code">${model.id}</span><h3>${model.name}</h3></div><div class="chart-value-row"><div class="metric-value" data-value>—<small>min</small></div><div class="chart-sample" data-sample>Waiting for a matched forecast</div></div><svg viewBox="0 0 400 126" role="img" aria-label="${model.name} error across the replay window"></svg><div class="chart-metadata"><span data-metric>Mean absolute error</span><span data-coverage>Coverage —</span></div><p class="chart-footnote">* ${model.id === "C" ? "C uses quality features and degraded-example training; the input guard can be disabled above." : "Frozen " + model.name + " baseline; the delivered reports are matched to the other models."} March 1–19: train; 20–24: development; 25–31: inspected exploratory. This replay is not held-out evidence.</p></article>`,
    ).join("");
  }
  reset() {
    this.samples = [];
    this.frame = null;
    this.render();
  }
  /** @param {FleetFrame} frame */
  update(frame) {
    this.frame = frame;
    const sample = sampleFrame(frame);
    const previous = this.samples.at(-1);
    if (
      previous &&
      (sample.time < previous.time || sample.time - previous.time > 10800)
    )
      this.samples = [];
    if (previous?.time === sample.time) this.samples.pop();
    if (sample.cases.length) this.samples.push(sample);
    this.samples = this.samples.slice(-120);
    this.render();
  }
  render() {
    const title =
      this.metric === "mae"
        ? "Mean absolute error"
        : this.metric === "rmse"
          ? "Root mean squared error"
          : "Mean squared error";
    const allScores = MODELS.flatMap((model) =>
      this.samples.map((sample) => score([sample], model.id, this.metric)),
    ).filter((value) => value !== null);
    const maximum = Math.max(5, .../** @type {number[]} */ (allScores)) * 1.15;
    const first = this.samples[0]?.time ?? 0,
      last = this.samples.at(-1)?.time ?? first;
    for (const model of MODELS) {
      const article = /** @type {HTMLElement} */ (
        this.container.querySelector(`[data-chart="${model.id}"]`)
      );
      const value = score(this.samples, model.id, this.metric),
        unit = this.metric === "mse" ? "min²" : "min";
      /** @type {HTMLElement} */ (
        article.querySelector("[data-value]")
      ).innerHTML =
        `${value === null ? "—" : value.toFixed(1)}<small>${unit}</small>`;
      const ids = new Set(
        this.samples.flatMap((sample) => sample.cases.map((item) => item.id)),
      );
      const cases = this.samples.reduce(
        (sum, sample) => sum + sample.cases.length,
        0,
      );
      /** @type {HTMLElement} */ (
        article.querySelector("[data-sample]")
      ).textContent = `${ids.size} approaches · ${cases} matched forecasts`;
      /** @type {HTMLElement} */ (
        article.querySelector("[data-metric]")
      ).textContent = title;
      const active = this.frame?.ships.filter((ship) => !ship.arrived) ?? [];
      const available = active.filter(
        (ship) => ship.predictions[model.id].available,
      ).length;
      /** @type {HTMLElement} */ (
        article.querySelector("[data-coverage]")
      ).textContent = `Current coverage ${available}/${active.length}`;
      const points = this.samples.map((sample) => [
        35 + ((sample.time - first) / Math.max(60, last - first)) * 345,
        98 - ((score([sample], model.id, this.metric) ?? 0) / maximum) * 82,
      ]);
      const path = points
        .map(
          ([x, y], index) =>
            `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`,
        )
        .join(" ");
      const svg = /** @type {SVGSVGElement} */ (article.querySelector("svg"));
      svg.innerHTML = `<path d="M35 18H383M35 58H383M35 98H383" stroke="#cbd4c9" stroke-width=".8"/><text x="7" y="22">${maximum.toFixed(this.metric === "mse" ? 0 : 1)}</text><text x="20" y="101">0</text>${points.length ? `<path d="${path}" stroke="${model.color}" stroke-width="2" fill="none"/>${points.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="2.6" fill="${model.color}" stroke="none"/>`).join("")}<text x="35" y="116">${utcClock(first)}</text><text x="383" y="116" text-anchor="end">${utcClock(last)} UTC</text>` : '<text x="200" y="65" text-anchor="middle">Play the replay to build a measured history.</text>'}`;
    }
  }
}

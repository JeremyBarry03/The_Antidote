/** @import {Snapshot, Timeline} from './types.js' */
import {MODEL_COLORS, clock, node, svgNode, utcDate} from './format.js';

const CHART_WIDTH = 1000;
const CHART_HEIGHT = 230;
const LEFT = 70;
const RIGHT = 24;
const TOP = 25;
const BOTTOM = 42;

/** @param {HTMLElement} container @param {Timeline} timeline @param {Snapshot} snapshot */
export function renderTimeline(container, timeline, snapshot) {
  container.replaceChildren();
  const valid = timeline.points.filter(point => point.available && point.predicted_arrival_time);
  if (!valid.length) {
    container.append(node('p', timeline.available ? 'No supported forecasts at this clock yet.'
      : 'Saved evaluation timeline is unavailable for this selection. Current forecasts are shown above.', 'empty-state'));
    return;
  }
  const svg = svgNode('svg', {viewBox: `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`, role: 'img',
    'aria-label': 'Predicted arrival time against decision time for A, B and C. Only decisions up to the replay clock are shown.'});
  const times = timeline.points.map(point => utcDate(point.decision_time).getTime());
  const arrivals = valid.map(point => utcDate(/** @type {string} */ (point.predicted_arrival_time)).getTime());
  if (snapshot.reference_arrival) arrivals.push(utcDate(snapshot.reference_arrival).getTime());
  const xMin = Math.min(...times), xRange = Math.max(60_000, Math.max(...times) - xMin);
  const yMin = Math.min(...arrivals) - 120_000;
  const yMax = Math.max(...arrivals) + 120_000;
  /** @param {number} value */
  const x = value => LEFT + (value - xMin) / xRange * (CHART_WIDTH - LEFT - RIGHT);
  /** @param {number} value */
  const y = value => CHART_HEIGHT - BOTTOM - (value - yMin) / (yMax - yMin) * (CHART_HEIGHT - TOP - BOTTOM);
  for (let index = 0; index <= 3; index += 1) {
    const value = yMin + index * (yMax - yMin) / 3;
    svg.append(svgNode('line', {x1: LEFT, x2: CHART_WIDTH - RIGHT, y1: y(value), y2: y(value), class: 'plot-grid'}));
    const label = svgNode('text', {x: LEFT - 10, y: y(value) + 4, 'text-anchor': 'end', class: 'plot-label'});
    label.textContent = clock(new Date(value).toISOString());
    svg.append(label);
  }
  for (let index = 0; index <= 3; index += 1) {
    const value = xMin + index * xRange / 3;
    const label = svgNode('text', {x: x(value), y: CHART_HEIGHT - 16, 'text-anchor': 'middle', class: 'plot-label'});
    label.textContent = clock(new Date(value).toISOString());
    svg.append(label);
  }
  for (const system of /** @type {const} */ (['A', 'B', 'C'])) {
    let path = '', connected = false;
    for (const point of timeline.points.filter(item => item.system === system)) {
      if (!point.available || !point.predicted_arrival_time) {connected = false; continue;}
      const px = x(utcDate(point.decision_time).getTime());
      const py = y(utcDate(point.predicted_arrival_time).getTime());
      path += `${connected ? 'L' : 'M'}${px},${py} `;
      connected = true;
      const dot = svgNode('circle', {cx: px, cy: py, r: 3, fill: MODEL_COLORS[system]});
      const title = svgNode('title', {});
      title.textContent = `${system}: at ${clock(point.decision_time)} UTC, ETA ${clock(point.predicted_arrival_time)} UTC`;
      dot.append(title);
      svg.append(dot);
    }
    svg.append(svgNode('path', {d: path, stroke: MODEL_COLORS[system], 'stroke-width': 2, fill: 'none'}));
  }
  if (snapshot.reference_arrival) {
    const py = y(utcDate(snapshot.reference_arrival).getTime());
    svg.append(svgNode('line', {x1: LEFT, x2: CHART_WIDTH - RIGHT, y1: py, y2: py,
      stroke: '#ffffff', 'stroke-width': 1.5, 'stroke-dasharray': '6 4'}));
    const label = svgNode('text', {x: CHART_WIDTH - RIGHT, y: py - 7, 'text-anchor': 'end', class: 'plot-label'});
    label.textContent = 'Recorded crossing';
    svg.append(label);
  }
  container.append(svg);
}

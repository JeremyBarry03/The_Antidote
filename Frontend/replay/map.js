/** @import {Gate, Snapshot, WindowWithMapbox} from './types.js' */
/** @import {Feature, FeatureCollection, Geometry} from 'geojson' */
/** @typedef {{kind: string, record_id?: string, altered?: boolean}} MapProperties */
import {clock, svgNode} from './format.js';

const MAPBOX_VERSION = '3.32.0';
const MAPBOX_ASSET_URL = `https://api.mapbox.com/mapbox-gl-js/v${MAPBOX_VERSION}`;
const MAP_LOAD_TIMEOUT_MS = 15_000;
const PLOT_WIDTH = 1000;
const PLOT_HEIGHT = 400;
const PLOT_PADDING = 44;
const POINT_COLOR = '#54d9ba';
const FAULT_COLOR = '#ff8d82';
const GATE_COLOR = '#e8b46a';

/** @param {Snapshot} snapshot @param {Gate} gate @returns {FeatureCollection<Geometry, MapProperties>} */
export function mapFeatures(snapshot, gate) {
  /** @type {Feature<Geometry, MapProperties>[]} */
  const features = [];
  /** @param {Geometry} geometry @param {MapProperties} properties */
  const add = (geometry, properties) => features.push({type: 'Feature', geometry, properties});
  const reports = snapshot.inspection?.records ?? snapshot.received_history;
  const originals = new Map(snapshot.inspection?.records.map(report => [report.record_id, report]));
  add({type: 'LineString', coordinates: [[gate.longitude, gate.south], [gate.longitude, gate.north]]}, {kind: 'gate'});
  if (reports.length > 1) {
    add({type: 'LineString', coordinates: reports.map(report => [report.longitude, report.latitude])}, {kind: 'track'});
  }
  for (const report of reports) {
    const original = originals.get(report.record_id);
    const altered = original?.fault_applied === true;
    add({type: 'Point', coordinates: [report.longitude, report.latitude]},
      {kind: 'report', record_id: report.record_id, altered});
    if (altered && original) {
      add({type: 'Point', coordinates: [original.original_longitude, original.original_latitude]}, {kind: 'original'});
      add({type: 'LineString', coordinates: [[original.original_longitude, original.original_latitude],
        [report.longitude, report.latitude]]}, {kind: 'displacement'});
    }
  }
  const latest = reports.at(-1);
  if (latest) add({type: 'Point', coordinates: [latest.longitude, latest.latitude]}, {kind: 'latest'});
  return {type: 'FeatureCollection', features};
}

/** @param {FeatureCollection<Geometry, MapProperties>} collection @returns {[number, number][]} */
function coordinates(collection) {
  return collection.features.flatMap(feature => feature.geometry.type === 'Point'
    ? [/** @type {[number, number]} */ (feature.geometry.coordinates)]
    : feature.geometry.type === 'LineString' ? /** @type {[number, number][]} */ (feature.geometry.coordinates) : []);
}

/** Load the optional SDK only after the user supplies a public token. */
export async function loadMapbox() {
  const surface = /** @type {WindowWithMapbox} */ (window);
  if (surface.mapboxgl) return surface.mapboxgl;
  const css = document.createElement('link');
  css.rel = 'stylesheet';
  css.href = `${MAPBOX_ASSET_URL}/mapbox-gl.css`;
  document.head.append(css);
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const timeout = setTimeout(() => {script.remove(); reject(new Error('Mapbox could not load. Check your connection.'));}, MAP_LOAD_TIMEOUT_MS);
    script.src = `${MAPBOX_ASSET_URL}/mapbox-gl.js`;
    script.onload = () => {clearTimeout(timeout); resolve(undefined);};
    script.onerror = () => {clearTimeout(timeout); script.remove(); reject(new Error('Mapbox could not load. Check your connection.'));};
    document.head.append(script);
  });
  if (!surface.mapboxgl) throw new Error('Mapbox is unavailable. The coordinate map remains active.');
  return surface.mapboxgl;
}

export class ReplayMap {
  /** @type {import('mapbox-gl').Map | null} */
  map = null;
  /** @type {Snapshot | null} */
  snapshot = null;
  ready = false;
  approachKey = '';
  connectionVersion = 0;
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  loadTimeout;

  /** @param {SVGSVGElement} plot @param {HTMLElement} basemap @param {HTMLElement} status
   * @param {Gate} gate @param {(identity: string) => void} onSelect */
  constructor(plot, basemap, status, gate, onSelect) {
    this.plot = plot;
    this.basemap = basemap;
    this.status = status;
    this.gate = gate;
    this.onSelect = onSelect;
    this.resizeObserver = new ResizeObserver(() => this.map?.resize());
    this.resizeObserver.observe(basemap);
  }

  /** @param {string} token */
  async connect(token) {
    if (!token.startsWith('pk.')) throw new Error('Enter a public Mapbox token beginning with pk.');
    this.useCoordinates();
    const version = this.connectionVersion;
    this.status.textContent = 'Loading Mapbox… Coordinate map is active.';
    const sdk = await loadMapbox();
    if (version !== this.connectionVersion) return;
    const map = new sdk.Map({container: this.basemap, accessToken: token,
      style: 'mapbox://styles/mapbox/dark-v11', center: [-76.25, 37], zoom: 10});
    this.map = map;
    // Keep the canvas measurable while its basemap loads behind the SVG plot.
    this.basemap.hidden = false;
    this.loadTimeout = setTimeout(() => {
      if (!this.ready) this.failMapbox('Mapbox timed out. Check the public token and connection.');
    }, MAP_LOAD_TIMEOUT_MS);
    map.on('load', () => {
      if (map !== this.map) return;
      clearTimeout(this.loadTimeout);
      this.ready = true;
      this.plot.toggleAttribute('hidden', true);
      this.status.textContent = 'Mapbox basemap · received reports · analytical arrival reference';
      map.addSource('replay', {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      const lineStyles = /** @type {[string, string, number][]} */ ([
        ['track', POINT_COLOR, 2], ['gate', GATE_COLOR, 3], ['displacement', FAULT_COLOR, 2]]);
      for (const [kind, color, width] of lineStyles) {
        map.addLayer({id: String(kind), type: 'line', source: 'replay', filter: ['==', ['get', 'kind'], kind],
          paint: {'line-color': color, 'line-width': width, ...(kind === 'displacement' ? {'line-dasharray': [2, 2]} : {})}});
      }
      map.addLayer({id: 'original', type: 'circle', source: 'replay', filter: ['==', ['get', 'kind'], 'original'],
        paint: {'circle-radius': 4, 'circle-color': '#102b32', 'circle-stroke-color': POINT_COLOR, 'circle-stroke-width': 1.5}});
      map.addLayer({id: 'reports', type: 'circle', source: 'replay', filter: ['==', ['get', 'kind'], 'report'],
        paint: {'circle-radius': 4.5, 'circle-color': ['case', ['get', 'altered'], FAULT_COLOR, POINT_COLOR],
          'circle-stroke-color': '#10222b', 'circle-stroke-width': 1}});
      map.addLayer({id: 'latest', type: 'circle', source: 'replay', filter: ['==', ['get', 'kind'], 'latest'],
        paint: {'circle-radius': 9, 'circle-color': 'transparent', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2}});
      map.on('click', 'reports', event => {
        const identity = event.features?.[0]?.properties?.record_id;
        if (typeof identity === 'string') this.onSelect(identity);
      });
      map.on('mouseenter', 'reports', () => {map.getCanvas().style.cursor = 'pointer';});
      map.on('mouseleave', 'reports', () => {map.getCanvas().style.cursor = '';});
      this.updateMapbox(true);
    });
    map.on('error', event => {
      const status = 'status' in event.error ? event.error.status : null;
      if (map === this.map && (!this.ready || status === 401 || status === 403)) {
        this.failMapbox('Mapbox could not load. Check the public token, URL restrictions, and connection.');
      }
    });
  }

  /** @param {string} message */
  failMapbox(message) {
    this.useCoordinates();
    this.status.textContent = `${message} Coordinate map is active.`;
  }

  useCoordinates() {
    this.connectionVersion += 1;
    clearTimeout(this.loadTimeout);
    this.ready = false;
    this.map?.remove();
    this.map = null;
    this.basemap.hidden = true;
    this.plot.toggleAttribute('hidden', false);
    this.status.textContent = 'Coordinate map · add a public Mapbox token for a geographic basemap';
  }

  /** @param {Snapshot} snapshot @param {string} approachId */
  render(snapshot, approachId) {
    const key = `${approachId}:${snapshot.scenario}`;
    const shouldFit = key !== this.approachKey;
    this.approachKey = key;
    this.snapshot = snapshot;
    this.drawCoordinates();
    this.updateMapbox(shouldFit);
  }

  /** @param {boolean} fit */
  updateMapbox(fit) {
    if (!this.ready || !this.map || !this.snapshot) return;
    const collection = mapFeatures(this.snapshot, this.gate);
    const source = /** @type {import('mapbox-gl').GeoJSONSource} */ (this.map.getSource('replay'));
    source.setData(collection);
    if (fit) {
      const points = coordinates(collection);
      this.map.fitBounds([[Math.min(...points.map(point => point[0])), Math.min(...points.map(point => point[1]))],
        [Math.max(...points.map(point => point[0])), Math.max(...points.map(point => point[1]))]],
      {padding: 55, duration: 0, maxZoom: 13});
    }
  }

  fit() { this.updateMapbox(true); }

  drawCoordinates() {
    if (!this.snapshot) return;
    const collection = mapFeatures(this.snapshot, this.gate);
    const points = coordinates(collection);
    const xMin = Math.min(...points.map(point => point[0])) - .003;
    const xMax = Math.max(...points.map(point => point[0])) + .003;
    const yMin = Math.min(...points.map(point => point[1])) - .003;
    const yMax = Math.max(...points.map(point => point[1])) + .003;
    /** @param {number[]} point */
    const project = point => [PLOT_PADDING + (point[0] - xMin) / (xMax - xMin) * (PLOT_WIDTH - 2 * PLOT_PADDING),
      PLOT_HEIGHT - PLOT_PADDING - (point[1] - yMin) / (yMax - yMin) * (PLOT_HEIGHT - 2 * PLOT_PADDING)];
    const defs = svgNode('defs', {});
    const marker = svgNode('marker', {id: 'offset-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5,
      markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse'});
    marker.append(svgNode('path', {d: 'M 0 0 L 10 5 L 0 10 z', fill: FAULT_COLOR}));
    defs.append(marker);
    this.plot.replaceChildren(defs);
    for (let index = 0; index <= 4; index += 1) {
      const y = PLOT_PADDING + index * (PLOT_HEIGHT - 2 * PLOT_PADDING) / 4;
      this.plot.append(svgNode('line', {x1: PLOT_PADDING, x2: PLOT_WIDTH - PLOT_PADDING, y1: y, y2: y, class: 'plot-grid'}));
      const label = svgNode('text', {x: 8, y: y - 8, class: 'plot-label'});
      label.textContent = `${(yMax - index * (yMax - yMin) / 4).toFixed(2)}°`;
      this.plot.append(label);
    }
    for (const feature of collection.features) {
      const properties = feature.properties ?? {};
      if (feature.geometry.type === 'LineString') {
        const path = feature.geometry.coordinates.map(point => project(point).join(',')).join(' ');
        this.plot.append(svgNode('polyline', {points: path, fill: 'none',
          stroke: properties.kind === 'gate' ? GATE_COLOR : properties.kind === 'displacement' ? FAULT_COLOR : POINT_COLOR,
          'stroke-width': properties.kind === 'gate' ? 3 : 1.5,
          ...(properties.kind === 'displacement' ? {'marker-end': 'url(#offset-arrow)', 'stroke-dasharray': '4 3'} : {})}));
      } else if (feature.geometry.type === 'Point') {
        const [x, y] = project(feature.geometry.coordinates);
        const hollow = properties.kind === 'latest' || properties.kind === 'original';
        const circle = svgNode('circle', {cx: x, cy: y, r: properties.kind === 'latest' ? 9 : 4.5,
          fill: hollow ? 'none' : properties.altered ? FAULT_COLOR : POINT_COLOR,
          stroke: properties.kind === 'latest' ? '#fff' : POINT_COLOR, 'stroke-width': hollow ? 2 : 0});
        if (properties.kind === 'report') {
          const report = this.snapshot.received_history.find(item => item.record_id === properties.record_id);
          const title = svgNode('title', {});
          title.textContent = `${clock(report?.time, true)} UTC · ${properties.altered ? 'known simulated offset' : 'received report'}`;
          circle.append(title);
          circle.setAttribute('role', 'button');
          circle.setAttribute('tabindex', '0');
          circle.setAttribute('aria-label', title.textContent);
          circle.addEventListener('click', () => this.onSelect(String(properties.record_id)));
          circle.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); this.onSelect(String(properties.record_id));}
          });
        }
        this.plot.append(circle);
      }
    }
    const label = svgNode('text', {x: PLOT_PADDING, y: PLOT_HEIGHT - 12, class: 'plot-label'});
    label.textContent = `Longitude ${xMin.toFixed(3)}° to ${xMax.toFixed(3)}° · local coordinate plot; no shoreline`;
    this.plot.append(label);
  }

  destroy() {
    this.useCoordinates();
    this.resizeObserver.disconnect();
  }
}

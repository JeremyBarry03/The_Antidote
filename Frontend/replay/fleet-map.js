/** @import {FleetFrame,FleetShip} from './fleet-types.js' */
/** @import {Gate,SystemName} from './types.js' */
/** @import {FeatureCollection,Geometry} from 'geojson' */
import { loadMapbox } from "./map.js";
import { utcClock } from "./fleet-charts.js";
import { FleetMotion } from "./fleet-motion.js";
const COLORS = { A: "#e5bb75", B: "#8cb6f3", C: "#89d9bc" };
/** @param {string} text */
const escape = (text) =>
  text.replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ] ?? character,
  );

export class FleetMap {
  /** @type {import('mapbox-gl').Map|null} */ map = null;
  /** @type {Map<string,import('mapbox-gl').Marker>} */ markers = new Map();
  /** @type {typeof import('mapbox-gl')|null} */ sdk = null;
  /** @type {FleetFrame|null} */ frame = null;
  /** @type {SystemName} */ model = "C";
  selected = "";
  ready = false;
  lastWidth = 0;
  motion = new FleetMotion();
  reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  lastTrailPaint = 0;
  visualClock = 0;
  /** @type {FeatureCollection<Geometry>|null} */ trailData = null;
  /** @type {Map<string,{x:number,y:number}>} */ fallbackAnchors = new Map();
  /** @type {((point:[number,number])=>{x:number,y:number})|null} */ fallbackProject =
    null;
  /** @param {HTMLElement} surface @param {SVGSVGElement} plot @param {Gate} gate @param {(id:string)=>void} onSelect */
  constructor(surface, plot, gate, onSelect) {
    this.surface = surface;
    this.plot = plot;
    this.gate = gate;
    this.onSelect = onSelect;
    this.resizeObserver = new ResizeObserver(() => {
      this.map?.resize();
      if (this.ready && this.surface.clientWidth !== this.lastWidth) {
        this.lastWidth = this.surface.clientWidth;
        this.fit();
      } else if (!this.ready) this.render();
    });
    this.resizeObserver.observe(surface);
    this.resizeObserver.observe(plot);
    this.reducedMotion.addEventListener("change", () => {
      if (this.frame) this.motion.update(this.frame.ships, false);
      this.render();
    });
  }
  /** @param {string|null} token */
  async connect(token) {
    if (!token) {
      this.plot.setAttribute(
        "aria-label",
        "Coordinate plot of delivered reports; no geographic basemap configured.",
      );
      return;
    }
    try {
      const sdk = await loadMapbox();
      this.sdk = sdk;
      this.surface.hidden = false;
      const map = new sdk.Map({
        container: this.surface,
        accessToken: token,
        style: "mapbox://styles/mapbox/dark-v11",
        center: [-76.14, 37.005],
        zoom: 9.6,
        attributionControl: true,
      });
      this.map = map;
      map.on("load", () => {
        this.ready = true;
        this.plot.toggleAttribute("hidden", true);
        map.addSource("fleet", {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });
        map.addLayer({
          id: "fleet-tracks",
          type: "line",
          source: "fleet",
          filter: ["==", ["get", "kind"], "track"],
          paint: {
            "line-color": ["get", "color"],
            "line-width": ["case", ["get", "selected"], 2.8, 1.5],
            "line-opacity": ["get", "opacity"],
          },
        });
        map.addLayer({
          id: "fleet-gate",
          type: "line",
          source: "fleet",
          filter: ["==", ["get", "kind"], "gate"],
          paint: {
            "line-color": "#e5bb75",
            "line-width": 2,
            "line-dasharray": [3, 2],
          },
        });
        this.render();
        this.fit();
      });
      map.on("moveend", () => this.render());
      map.on("move", () => this.paintMarkers());
      map.on("error", (event) => {
        const status = "status" in event.error ? event.error.status : null;
        if (!this.ready || status === 401 || status === 403) {
          this.ready = false;
          this.surface.hidden = true;
          this.plot.toggleAttribute("hidden", false);
          this.render();
        }
      });
    } catch {
      this.surface.hidden = true;
      this.plot.toggleAttribute("hidden", false);
      this.render();
    }
  }
  /** @param {FleetFrame} frame @param {SystemName} model @param {string} selected
   * @param {boolean} [continuous] */
  update(frame, model, selected, continuous = false) {
    if (frame !== this.frame) {
      this.motion.update(
        frame.ships,
        continuous && !this.reducedMotion.matches,
      );
      this.visualClock = continuous
        ? Math.max(this.visualClock, frame.time)
        : frame.time;
    }
    this.frame = frame;
    this.model = model;
    this.selected = selected;
    this.render();
  }
  /** @param {FleetShip} ship @returns {[number,number][]} */
  track(ship) {
    return this.motion.track(ship.id);
  }
  /** @param {FleetShip} ship */
  label(ship) {
    const prediction = ship.predictions[this.model];
    const error = prediction.error;
    return `<svg class="ship-connector" viewBox="0 0 26 34" aria-hidden="true"><path/></svg><span class="ship-hull"><svg viewBox="0 0 26 34" aria-hidden="true" style="transform:rotate(${this.motion.pose(ship.id)?.heading ?? 270}deg)"><path d="M13 2 22 25l-9-4-9 4z"/></svg></span><span class="ship-label"><strong>${escape(ship.name)}</strong><span class="ship-eta">${ship.arrived ? "Crossed" : prediction.eta === null ? "No estimate" : utcClock(prediction.eta) + " UTC"}</span><br><span class="ship-error ${error !== null && Math.abs(error) > 15 ? "large-error" : ""}">${error === null ? "Insufficient delivered history" : Math.abs(error).toFixed(1) + " min " + (error < 0 ? "early" : "late") + " · scored"}</span></span>`;
  }
  /** Keep forecast labels distinct without moving the vessel coordinates.
   * @param {FleetShip[]} ships
   * @param {((point:[number,number])=>{x:number,y:number})=} project
   * @param {number=} width
   * @param {number=} height */
  labelPositions(
    ships,
    project,
    width = this.surface.clientWidth,
    height = this.surface.clientHeight,
  ) {
    /** @type {{x:number,y:number,w:number,h:number}[]} */ const occupied = [];
    /** @type {Map<string,{x:number,y:number,px:number,py:number}>} */ const positions =
      new Map();
    if (!this.map && !project) return positions;
    const ordered = [...ships].sort(
      (a, b) => Number(b.id === this.selected) - Number(a.id === this.selected),
    );
    for (const ship of ordered) {
      const location = this.track(ship).at(-1) ?? [0, 0];
      const point = project
        ? project(location)
        : (this.map?.project(location) ?? { x: 0, y: 0 });
      const w = 150,
        h = 67;
      const candidates = [
        point.x + 22,
        point.x - w - 22,
        10,
        width - w - 10,
      ].flatMap((left) =>
        [-25, -100, 50, -175, 125].map((dy) => ({
          x: Math.max(10, Math.min(width - w - 10, left)),
          y: Math.max(75, Math.min(height - h - 48, point.y + dy)),
          w,
          h,
        })),
      );
      const cost = /** @param {{x:number,y:number,w:number,h:number}} rect */ (
        rect,
      ) =>
        occupied.reduce(
          (sum, other) =>
            sum +
            Math.max(
              0,
              Math.min(rect.x + w, other.x + other.w) -
                Math.max(rect.x, other.x),
            ) *
              Math.max(
                0,
                Math.min(rect.y + h, other.y + other.h) -
                  Math.max(rect.y, other.y),
              ) *
              20,
          0,
        ) +
        Math.abs(rect.x - point.x) * 0.15 +
        Math.abs(rect.y - point.y) * 0.3;
      candidates.sort((a, b) => cost(a) - cost(b));
      const rect = candidates[0];
      occupied.push(rect);
      positions.set(ship.id, {
        x: rect.x,
        y: rect.y,
        px: point.x,
        py: point.y,
      });
    }
    return positions;
  }
  render() {
    if (!this.frame) return;
    const color = COLORS[this.model];
    const ships = this.frame.ships.filter((ship) => ship.reports.length > 0);
    if (this.ready && this.map && this.sdk) {
      /** @type {FeatureCollection<Geometry>} */ const data = {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { kind: "gate" },
            geometry: {
              type: "LineString",
              coordinates: [
                [this.gate.longitude, this.gate.south],
                [this.gate.longitude, this.gate.north],
              ],
            },
          },
        ],
      };
      const visible = new Set();
      const labels = this.labelPositions(ships);
      for (const ship of ships) {
        const points = this.track(ship);
        if (points.length > 1)
          data.features.push({
            type: "Feature",
            properties: {
              kind: "track",
              id: ship.id,
              color,
              selected: ship.id === this.selected,
              opacity: ship.fade * (ship.id === this.selected ? 0.95 : 0.48),
            },
            geometry: { type: "LineString", coordinates: points },
          });
        visible.add(ship.id);
        let marker = this.markers.get(ship.id);
        if (!marker) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "ship-marker";
          button.addEventListener("click", () => this.onSelect(ship.id));
          marker = new this.sdk.Marker({ element: button, anchor: "center" })
            .setLngLat(points.at(-1) ?? [0, 0])
            .addTo(this.map);
          this.markers.set(ship.id, marker);
        }
        const button = marker.getElement();
        button.innerHTML = this.label(ship);
        button.classList.toggle("selected", ship.id === this.selected);
        const position = labels.get(ship.id);
        if (position) {
          const label = /** @type {HTMLElement} */ (
            button.querySelector(".ship-label")
          );
          const left = position.x - position.px + 13,
            top = position.y - position.py + 17;
          label.style.left = `${left}px`;
          label.style.top = `${top}px`;
          const edge = left > 13 ? left : left + 150;
          button
            .querySelector(".ship-connector path")
            ?.setAttribute("d", `M13 17L${edge} ${top + 33}`);
        }
        button.setAttribute("role", "button");
        button.style.color = color;
        button.setAttribute(
          "aria-label",
          `Inspect ${ship.name}, ${this.model} forecast`,
        );
        button.setAttribute("aria-pressed", String(ship.id === this.selected));
        marker.setLngLat(points.at(-1) ?? [0, 0]);
      }
      for (const [id, marker] of this.markers)
        if (!visible.has(id)) {
          marker.remove();
          this.markers.delete(id);
        }
      this.trailData = data;
      this.paintMarkers();
      /** @type {import('mapbox-gl').GeoJSONSource} */ (
        this.map.getSource("fleet")
      ).setData(data);
      return;
    }
    // SVG units follow screen pixels so labels stay readable at phone widths.
    const width = this.plot.clientWidth || 1000,
      height = this.plot.clientHeight || 560;
    this.plot.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const points = ships.flatMap((ship) => this.track(ship));
    points.push(
      [this.gate.longitude, this.gate.south],
      [this.gate.longitude, this.gate.north],
    );
    const longitudes = points.map((point) => point[0]),
      latitudes = points.map((point) => point[1]);
    const west = Math.min(...longitudes) - 0.015,
      east = Math.max(...longitudes) + 0.015,
      south = Math.min(...latitudes) - 0.015,
      north = Math.max(...latitudes) + 0.015;
    const x = /** @param {number} longitude */ (longitude) =>
      24 + ((longitude - west) / (east - west)) * (width - 48);
    const y = /** @param {number} latitude */ (latitude) =>
      height - 70 - ((latitude - south) / (north - south)) * (height - 150);
    this.fallbackProject = ([longitude, latitude]) => ({
      x: x(longitude),
      y: y(latitude),
    });
    this.fallbackAnchors.clear();
    const labels = this.labelPositions(
      ships,
      ([longitude, latitude]) => ({ x: x(longitude), y: y(latitude) }),
      width,
      height,
    );
    const paths = ships
      .map(
        (ship) =>
          `<g data-trail="${escape(ship.id)}" opacity="${ship.fade}"><path d="${this.track(
            ship,
          )
            .map(
              ([lon, lat], index) => `${index ? "L" : "M"}${x(lon)},${y(lat)}`,
            )
            .join(
              " ",
            )}" fill="none" stroke="${color}" stroke-width="${ship.id === this.selected ? 2.5 : 1.3}" opacity=".7"/></g>`,
      )
      .join("");
    const longitudeTicks = Array.from(
      { length: width < 650 ? 3 : 5 },
      (_, index) => west + ((east - west) * index) / (width < 650 ? 2 : 4),
    );
    const latitudeTicks = Array.from(
      { length: 3 },
      (_, index) => south + ((north - south) * index) / 2,
    );
    this.plot.innerHTML = `<g stroke="#294a56" stroke-width=".6">${longitudeTicks.map((lon) => `<path d="M${x(lon)} 75V${height - 65}"/><text x="${x(lon)}" y="${height - 68}" text-anchor="middle">${lon.toFixed(2)}°</text>`).join("")}${latitudeTicks.map((lat) => `<path d="M24 ${y(lat)}H${width - 24}"/><text x="28" y="${y(lat) - 5}">${lat.toFixed(2)}°</text>`).join("")}</g><path d="M${x(this.gate.longitude)} ${y(this.gate.south)}V${y(this.gate.north)}" stroke="#e5bb75" stroke-width="2" stroke-dasharray="6 5"/>${paths}${ships
      .map((ship) => {
        const point = this.track(ship).at(-1) ?? [0, 0],
          prediction = ship.predictions[this.model];
        const px = x(point[0]),
          py = y(point[1]);
        this.fallbackAnchors.set(ship.id, { x: px, y: py });
        const label = labels.get(ship.id) ?? { x: px + 16, y: py - 25 },
          lx = label.x,
          ly = label.y;
        const edge = Math.max(lx, Math.min(lx + 150, px));
        return `<g data-ship="${escape(ship.id)}" tabindex="0" role="button" aria-label="Inspect ${escape(ship.name)}" aria-pressed="${ship.id === this.selected}" style="cursor:pointer" opacity="${ship.fade}"><path d="M${px} ${py}L${edge} ${ly + 33}" stroke="${color}" opacity=".6"/><circle cx="${px}" cy="${py}" r="6" fill="${color}" stroke="#d9efdf"/><rect x="${lx}" y="${ly}" width="150" height="67" rx="4" fill="#102e38" stroke="${ship.id === this.selected ? "#8cd1b4" : "#4c7377"}"/><text x="${lx + 10}" y="${ly + 18}" style="fill:#e1f0e6;font-size:10px">${escape(ship.name.slice(0, 20))}</text><text x="${lx + 10}" y="${ly + 37}" style="fill:#f0f7ed;font-size:14px">${ship.arrived ? "Crossed" : prediction.eta === null ? "No estimate" : utcClock(prediction.eta) + " UTC"}</text><text x="${lx + 10}" y="${ly + 53}" style="font-size:10px">${prediction.error === null ? "Insufficient history" : Math.abs(prediction.error).toFixed(1) + " min error · scored"}</text></g>`;
      })
      .join(
        "",
      )}<text x="24" y="${height - 12}">Coordinate view · basemap unavailable</text>`;
    for (const element of this.plot.querySelectorAll("[data-ship]")) {
      const select = () =>
        this.onSelect(element.getAttribute("data-ship") ?? "");
      element.addEventListener("click", select);
      element.addEventListener("keydown", (event) => {
        if (
          event instanceof KeyboardEvent &&
          ["Enter", " "].includes(event.key)
        ) {
          event.preventDefault();
          select();
        }
      });
    }
  }
  paintMarkers() {
    if (!this.frame || !this.map) return;
    for (const ship of this.frame.ships) {
      const pose = this.motion.pose(ship.id),
        marker = this.markers.get(ship.id);
      if (!pose || !marker) continue;
      marker.setLngLat(pose.position);
      const point = this.map.project(pose.position),
        button = marker.getElement();
      // Keep subpixel positioning and arrival opacity stable across SDK repaint.
      button.style.setProperty(
        "--ship-transform",
        `translate(${point.x}px, ${point.y}px) translate(-50%, -50%)`,
      );
      button.style.setProperty(
        "--ship-opacity",
        String(
          ship.arrived
            ? Math.max(
                0,
                1 - Math.max(0, this.visualClock - ship.arrival) / 480,
              )
            : 1,
        ),
      );
      const hull = /** @type {SVGSVGElement|null} */ (
        button.querySelector(".ship-hull svg")
      );
      if (hull) hull.style.transform = `rotate(${pose.heading}deg)`;
    }
  }
  /** Paint moving hulls each animation frame and batch trail uploads at 10 Hz.
   * @param {number} seconds @param {number} clock */
  advance(seconds, clock) {
    if (!this.frame || this.reducedMotion.matches) return;
    this.motion.advance(seconds);
    this.visualClock = clock;
    const fade = /** @param {FleetShip} ship */ (ship) =>
      ship.arrived
        ? Math.max(0, 1 - Math.max(0, clock - ship.arrival) / 480)
        : 1;
    if (this.ready && this.map) {
      this.paintMarkers();
    } else if (this.fallbackProject) {
      const project = this.fallbackProject;
      for (const element of this.plot.querySelectorAll("[data-ship]")) {
        const id = element.getAttribute("data-ship") ?? "";
        const pose = this.motion.pose(id),
          origin = this.fallbackAnchors.get(id);
        const ship = this.frame.ships.find((item) => item.id === id);
        if (!pose || !origin || !ship) continue;
        const point = project(pose.position);
        element.setAttribute(
          "transform",
          `translate(${point.x - origin.x} ${point.y - origin.y})`,
        );
        element.setAttribute("opacity", String(fade(ship)));
      }
    }
    const now = performance.now();
    if (now - this.lastTrailPaint < 100) return;
    this.lastTrailPaint = now;
    if (this.ready && this.map && this.trailData) {
      for (const feature of this.trailData.features) {
        if (
          feature.properties?.kind !== "track" ||
          feature.geometry.type !== "LineString"
        )
          continue;
        const ship = this.frame.ships.find(
          (item) => item.id === feature.properties?.id,
        );
        if (!ship) continue;
        feature.geometry.coordinates = this.track(ship);
        feature.properties.opacity =
          fade(ship) * (ship.id === this.selected ? 0.95 : 0.48);
      }
      /** @type {import('mapbox-gl').GeoJSONSource} */ (
        this.map.getSource("fleet")
      ).setData(this.trailData);
    } else if (this.fallbackProject) {
      const project = this.fallbackProject;
      for (const element of this.plot.querySelectorAll("[data-trail]")) {
        const ship = this.frame.ships.find(
          (item) => item.id === element.getAttribute("data-trail"),
        );
        if (!ship) continue;
        element.setAttribute("opacity", String(fade(ship)));
        element.querySelector("path")?.setAttribute(
          "d",
          this.track(ship)
            .map((position, index) => {
              const point = project(position);
              return `${index ? "L" : "M"}${point.x},${point.y}`;
            })
            .join(" "),
        );
      }
    }
  }
  fit() {
    if (!this.ready || !this.map) {
      this.render();
      return;
    }
    if (!this.frame) return;
    const points = this.frame.ships.flatMap((ship) => this.track(ship));
    if (!points.length) return;
    const xs = points.map((point) => point[0]),
      ys = points.map((point) => point[1]);
    this.map.fitBounds(
      [
        [Math.min(...xs) - 0.015, Math.min(...ys) - 0.015],
        [Math.max(...xs) + 0.015, Math.max(...ys) + 0.015],
      ],
      {
        padding: {
          top: 85,
          bottom: 65,
          left: 50,
          right: this.surface.clientWidth < 650 ? 110 : 170,
        },
        maxZoom: 11.2,
        duration: 600,
      },
    );
  }
  resize() {
    this.map?.resize();
    this.fit();
  }
}

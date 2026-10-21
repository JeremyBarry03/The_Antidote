/** @import {FleetCatalog,FleetFrame,FleetShip,Metric,ScoreSample} from './fleet-types.js' */
/** @import {SystemName,Metrics,PublicConfig} from './types.js' */
import { FleetMap } from "./fleet-map.js";
import { FleetCharts, MODELS, utcClock } from "./fleet-charts.js";
/** @param {string} id */
function node(id) {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing page element: ${id}`);
  return element;
}
/** @param {string} id */ const input = (id) =>
  /** @type {HTMLInputElement} */ (node(id));
/** @param {string} id */ const select = (id) =>
  /** @type {HTMLSelectElement} */ (node(id));
/** @param {string} text */ const escape = (text) =>
  text.replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ] ?? char,
  );
/** @template T @param {string} path @param {AbortSignal} [signal] @returns {Promise<T>} */
async function get(path, signal) {
  const response = await fetch(path, { signal });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      result.error ?? `Replay request failed (${response.status}).`,
    );
  return result;
}

export class FleetApp {
  /** @type {FleetCatalog|null} */ catalog = null;
  /** @type {FleetFrame|null} */ frame = null;
  /** @type {FleetMap|null} */ map = null;
  /** @type {SystemName} */ model = "C";
  selected = "";
  clock = 0;
  playing = false;
  speed = 60;
  delay = 0;
  fraction = 0;
  offset = 0.5;
  guard = true;
  pending = false;
  version = 0;
  lastTick = 0;
  lastMinute = -1;
  controller = new AbortController();
  historyController = new AbortController();
  comparisonRevision = 0;
  /** @type {ReturnType<typeof setTimeout>|undefined} */ debounce;
  charts = new FleetCharts(node("comparison-charts"));
  constructor() {
    this.bind();
  }
  bind() {
    for (const button of document.querySelectorAll("[data-model]"))
      button.addEventListener("click", () =>
        this.setModel(
          /** @type {SystemName} */ (button.getAttribute("data-model")),
        ),
      );
    node("fleet-console")
      .querySelector("[role=tablist]")
      ?.addEventListener("keydown", (event) => {
        if (!(event instanceof KeyboardEvent)) return;
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
          return;
        event.preventDefault();
        const index = MODELS.findIndex((item) => item.id === this.model);
        const next =
          event.key === "Home"
            ? 0
            : event.key === "End"
              ? 2
              : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3;
        this.setModel(MODELS[next].id);
        node(`model-${MODELS[next].id.toLowerCase()}`).focus();
      });
    node("play").addEventListener("click", () =>
      this.setPlaying(!this.playing),
    );
    select("speed").addEventListener("change", () => {
      this.speed = Number(select("speed").value);
    });
    input("month-slider").addEventListener("input", () => {
      this.setPlaying(false);
      this.clock = Number(input("month-slider").value);
      this.resetComparison();
      this.renderClock();
      clearTimeout(this.debounce);
      this.debounce = setTimeout(() => this.refresh(true), 100);
    });
    for (const button of document.querySelectorAll(".next-traffic"))
      button.addEventListener("click", () => this.nextTraffic());
    for (const id of [
      "delay-slider",
      "quality-slider",
      "offset",
      "guard-toggle",
    ])
      node(id).addEventListener(
        id === "offset" || id === "guard-toggle" ? "change" : "input",
        () => this.changeControls(),
      );
    node("reset-faults").addEventListener("click", () => this.preset("clean"));
    for (const button of document.querySelectorAll("[data-preset]"))
      button.addEventListener("click", () =>
        this.preset(button.getAttribute("data-preset") ?? "clean"),
      );
    select("metric").addEventListener("change", () => {
      this.charts.metric = /** @type {Metric} */ (select("metric").value);
      this.charts.render();
    });
    node("fullscreen").addEventListener("click", () => this.fullscreen());
    document.addEventListener("fullscreenchange", () => {
      this.map?.resize();
      this.fullscreenLabel();
    });
    document.addEventListener("keydown", (event) => {
      if (
        event.key === "Escape" &&
        node("fleet-console").classList.contains("expanded")
      ) {
        node("fleet-console").classList.remove("expanded");
        document.body.classList.remove("fullscreen-open");
        this.fullscreenLabel();
        this.map?.resize();
      }
    });
    node("fit-fleet").addEventListener("click", () => this.map?.fit());
    node("inspect-alert").addEventListener("click", () => {
      const ship =
        this.frame?.ships.find((item) => item.diagnostics.state === "review") ??
        this.frame?.ships.find((item) => item.diagnostics.state === "handled");
      if (ship) this.selectShip(ship.id);
      node("feed-title").scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    });
    node("ship-list").addEventListener("click", (event) => {
      if (event.target instanceof Element) {
        const row = event.target.closest("[data-id]");
        if (row) this.selectShip(row.getAttribute("data-id") ?? "");
      }
    });
    this.setModel("C");
  }
  async start() {
    try {
      const [catalog, config] = await Promise.all([
        get("/api/fleet/catalog"),
        get("/api/config"),
      ]);
      this.catalog = /** @type {FleetCatalog} */ (catalog);
      const settings = /** @type {PublicConfig} */ (config);
      this.clock = this.catalog.initial_time;
      const slider = input("month-slider");
      slider.min = String(this.catalog.start);
      slider.max = String(this.catalog.end);
      slider.disabled = false;
      node("cohort-note").textContent =
        `${this.catalog.approaches} supported cargo/tanker approaches from ${this.catalog.vessels} vessels in March 2024, using the public NOAA Marine Cadastre AIS archive. This is the supported arrival cohort, not all harbor traffic.`;
      this.map = new FleetMap(
        node("fleet-geography"),
        /** @type {SVGSVGElement} */ (
          /** @type {unknown} */ (node("fleet-coordinates"))
        ),
        this.catalog.gate,
        (id) => this.selectShip(id),
      );
      void this.map.connect(settings.mapbox_public_token);
      this.renderClock();
      await this.refresh(true);
      node("loading-status").hidden = true;
      /** @type {HTMLButtonElement} */ (node("play")).disabled = false;
      this.lastTick = performance.now();
      requestAnimationFrame((time) => this.tick(time));
      void this.loadSavedMetrics();
    } catch (error) {
      this.showError(error);
      node("loading-status").textContent =
        "The fleet replay could not load. Start the local replay server and refresh this page.";
    }
  }
  /** @param {SystemName} model */
  setModel(model) {
    this.model = model;
    for (const button of document.querySelectorAll("[data-model]")) {
      const active = button.getAttribute("data-model") === model;
      button.setAttribute("aria-selected", String(active));
      /** @type {HTMLButtonElement} */ (button).tabIndex = active ? 0 : -1;
    }
    const panel = node("fleet-console").querySelector(".fleet-workspace");
    panel?.setAttribute("role", "tabpanel");
    panel?.setAttribute("aria-labelledby", `model-${model.toLowerCase()}`);
    node("antidote-alert").hidden = model !== "C";
    this.render();
  }
  /** @param {boolean} playing */
  setPlaying(playing) {
    this.playing = playing;
    const button = node("play");
    button.setAttribute("aria-label", playing ? "Pause replay" : "Play replay");
    button.innerHTML = playing
      ? '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 4h3v12H5zM12 4h3v12h-3z"/></svg><span>Pause</span>'
      : '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 9 6-9 6z"/></svg><span>Play</span>';
    this.lastTick = performance.now();
  }
  /** @param {number} time */
  tick(time) {
    const elapsed = Math.min((time - this.lastTick) / 1000, 0.5);
    this.lastTick = time;
    if (this.playing && this.catalog && !document.hidden) {
      const previous = this.clock;
      this.clock = Math.min(
        this.catalog.end,
        this.clock + elapsed * this.speed,
      );
      this.map?.advance(this.clock - previous, this.clock);
      this.renderClock();
      if (this.clock >= this.catalog.end) this.setPlaying(false);
      if (Math.floor(this.clock / 60) !== this.lastMinute && !this.pending)
        void this.refresh();
    }
    requestAnimationFrame((next) => this.tick(next));
  }
  renderClock() {
    if (!this.clock) return;
    node("replay-clock").textContent = utcClock(this.clock, true);
    node("replay-date").textContent =
      new Date(this.clock * 1000)
        .toLocaleDateString("en-GB", {
          timeZone: "UTC",
          day: "2-digit",
          month: "short",
          year: "numeric",
        })
        .toUpperCase() + " · UTC";
    input("month-slider").value = String(this.clock);
  }
  nextTraffic() {
    if (!this.catalog) return;
    const next = this.catalog.windows.find(
      (window) => window.start > this.clock + 60,
    );
    this.clock = next?.start ?? this.catalog.initial_time;
    this.resetComparison();
    this.renderClock();
    void this.refresh(true);
  }
  /** @param {string} preset */
  preset(preset) {
    input("delay-slider").value = ["stale", "combined"].includes(preset)
      ? "15"
      : "0";
    input("quality-slider").value = ["quality", "combined"].includes(preset)
      ? "25"
      : "0";
    select("offset").value = "0.5";
    this.changeControls();
  }
  changeControls() {
    this.delay = Number(input("delay-slider").value);
    this.fraction = Number(input("quality-slider").value) / 100;
    this.offset = Number(select("offset").value);
    this.guard = input("guard-toggle").checked;
    node("delay-value").textContent = `${this.delay} min delay`;
    node("quality-value").textContent =
      `${Math.round(this.fraction * 100)}% affected`;
    const condition =
      this.delay && this.fraction
        ? "Combined faults"
        : this.delay
          ? "Stale reports only"
          : this.fraction
            ? "Incorrect positions only"
            : "Clean reports";
    node("condition-label").textContent =
      `${condition} · guard ${this.guard ? "on" : "off"}`;
    for (const button of document.querySelectorAll("[data-preset]")) {
      const preset = button.getAttribute("data-preset");
      const active =
        preset === "clean"
          ? !this.delay && !this.fraction
          : preset === "stale"
            ? this.delay === 15 && !this.fraction
            : preset === "quality"
              ? !this.delay && this.fraction === 0.25 && this.offset === 0.5
              : this.delay === 15 &&
                this.fraction === 0.25 &&
                this.offset === 0.5;
      button.setAttribute("aria-pressed", String(active));
    }
    this.resetComparison();
    node("frame-status").textContent =
      "Recomputing all three models from the changed feed…";
    clearTimeout(this.debounce);
    this.controller.abort();
    this.version += 1;
    this.pending = false;
    this.debounce = setTimeout(() => this.refresh(true), 180);
  }
  /** @param {boolean} [force] */
  async refresh(force = false) {
    if (!this.catalog || (this.pending && !force)) return;
    if (force) this.controller.abort();
    this.controller = new AbortController();
    const version = ++this.version;
    this.pending = true;
    const requested = Math.floor(this.clock / 60) * 60;
    const continuous = !force && this.playing;
    const params = new URLSearchParams({
      time: String(requested),
      delay: String(this.delay),
      fraction: String(this.fraction),
      offset: String(this.offset),
      guard: String(this.guard),
    });
    try {
      const frame = /** @type {FleetFrame} */ (
        await get(`/api/fleet/frame?${params}`, this.controller.signal)
      );
      if (version !== this.version) return;
      this.frame = frame;
      this.lastMinute = Math.floor(requested / 60);
      if (!frame.ships.some((ship) => ship.id === this.selected))
        this.selected =
          frame.ships.find((ship) => !ship.arrived)?.id ??
          frame.ships[0]?.id ??
          "";
      this.charts.update(frame);
      this.render(continuous);
      if (force) void this.warmHistory(params, this.comparisonRevision);
      node("frame-status").textContent =
        `Updated ${utcClock(frame.time)} UTC · seed ${frame.seed} · same delivered feed`;
      const matched = this.charts.samples.reduce(
        (sum, sample) => sum + sample.cases.length,
        0,
      );
      node("comparison-caption").textContent =
        `${matched} matched forecasts in this exploratory replay window. Scores reset when the faults or guard change.`;
      node("error-banner").hidden = true;
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;
      if (version === this.version) {
        this.showError(error);
        this.setPlaying(false);
      }
    } finally {
      if (version === this.version) this.pending = false;
    }
  }
  resetComparison() {
    this.comparisonRevision += 1;
    this.historyController.abort();
    this.charts.reset();
  }
  /** @param {URLSearchParams} params @param {number} revision */
  async warmHistory(params, revision) {
    this.historyController.abort();
    this.historyController = new AbortController();
    try {
      const result = /** @type {{samples:ScoreSample[]}} */ (
        await get(`/api/fleet/history?${params}`, this.historyController.signal)
      );
      if (revision !== this.comparisonRevision) return;
      const combined = new Map(
        [...result.samples, ...this.charts.samples].map((sample) => [
          sample.time,
          sample,
        ]),
      );
      this.charts.samples = [...combined.values()]
        .sort((a, b) => a.time - b.time)
        .slice(-120);
      this.charts.render();
      node("comparison-caption").textContent =
        `${this.charts.samples.reduce((sum, sample) => sum + sample.cases.length, 0)} matched forecasts · measured preceding 30 minutes plus live playback. Controls start a fresh comparison.`;
    } catch (error) {
      if (error instanceof Error && error.name !== "AbortError")
        node("comparison-caption").textContent =
          "Past comparison frames could not load. The live measured frames are still shown.";
    }
  }
  /** @param {unknown} error */
  showError(error) {
    const banner = node("error-banner");
    banner.hidden = false;
    banner.textContent = `${error instanceof Error ? error.message : String(error)} Use the served page at http://127.0.0.1:8765 and refresh to reconnect.`;
  }
  /** @param {string} id */
  selectShip(id) {
    this.selected = id;
    this.render();
  }
  /** @param {boolean} [continuous] */
  render(continuous = false) {
    if (!this.frame) return;
    this.map?.update(this.frame, this.model, this.selected, continuous);
    const active = this.frame.ships.filter((ship) => !ship.arrived).length;
    const fading = this.frame.ships.length - active;
    node("fleet-count").textContent =
      `${active} active ${active === 1 ? "vessel" : "vessels"}${fading ? ` · ${fading} crossing confirmed` : ""} · ${MODELS.find((model) => model.id === this.model)?.name}`;
    node("map-empty").hidden = this.frame.ships.length > 0;
    const list = node("ship-list");
    const focused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement.getAttribute("data-id")
        : null;
    list.innerHTML =
      this.frame.ships
        .map(
          (ship) =>
            `<button class="ship-row" type="button" data-id="${escape(ship.id)}" aria-pressed="${ship.id === this.selected}"><span class="ship-indicator"></span><strong>${escape(ship.name)}</strong><span>${ship.arrived ? "Crossed" : ship.predictions[this.model].eta === null ? "No ETA" : utcClock(/** @type {number} */ (ship.predictions[this.model].eta))}</span></button>`,
        )
        .join("") ||
      '<p class="vessel-subtitle">No vessel is in a supported arrival window. Jump forward to the next traffic window.</p>';
    if (focused)
      /** @type {HTMLButtonElement|null} */ (
        [...list.querySelectorAll("button")].find(
          (button) => button.getAttribute("data-id") === focused,
        ) ?? null
      )?.focus();
    this.renderShip(
      this.frame.ships.find((ship) => ship.id === this.selected) ?? null,
    );
    this.renderAlert();
  }
  /** @param {FleetShip|null} ship */
  renderShip(ship) {
    if (!ship) {
      node("vessel-detail").innerHTML =
        '<p class="vessel-subtitle">Choose a traffic window to inspect the delivered data.</p>';
      node("report-rows").innerHTML =
        '<tr><td colspan="3">No active received reports.</td></tr>';
      return;
    }
    const prediction = ship.predictions[this.model],
      error = prediction.error;
    node("vessel-detail").innerHTML =
      `<h3>${escape(ship.name)}</h3><p class="vessel-subtitle">${escape(ship.type)} · MMSI ${escape(ship.mmsi)} · ${ship.arrived ? "crossing confirmed" : escape(ship.split === "train" ? "training-period replay" : ship.split === "validation" ? "development-period replay" : "exploratory-period replay")}</p><dl class="vessel-facts"><div><dt>Predicted crossing</dt><dd>${prediction.eta === null ? "Unavailable" : utcClock(prediction.eta)}</dd></div><div><dt>Historical error</dt><dd>${error === null ? "—" : Math.abs(error).toFixed(1) + " min"}</dd></div><div><dt>Latest report age</dt><dd ${this.delay > 0 ? 'class="fault-field"' : ""}>${ship.age_minutes === null ? "No report" : ship.age_minutes.toFixed(1) + " min"}</dd></div><div><dt>Recorded crossing*</dt><dd>${utcClock(ship.arrival)}</dd></div></dl>`;
    node("report-rows").innerHTML =
      ship.reports
        .slice(-4)
        .reverse()
        .map(
          (report) =>
            `<tr><td ${report.delivered > report.time ? 'class="fault-field"' : ""}>${utcClock(report.time, true)}<small>${report.delivered > report.time ? `delivered ${utcClock(report.delivered)}` : "on time"}</small></td><td ${report.altered ? 'class="fault-field"' : ""} title="${report.altered ? `Original ${report.original_latitude.toFixed(5)}, ${report.original_longitude.toFixed(5)}` : "Unaltered archive position"}">${report.latitude.toFixed(5)}<br>${report.longitude.toFixed(5)}</td><td>${report.speed === null ? "—" : report.speed.toFixed(1)}</td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="3">No reports have been delivered by this time.</td></tr>';
  }
  renderAlert() {
    if (!this.frame) return;
    const banner = node("antidote-alert");
    banner.hidden = this.model !== "C";
    if (this.model !== "C") return;
    const active = this.frame.ships.filter((ship) => !ship.arrived),
      reviews = active.filter((ship) => ship.diagnostics.state === "review"),
      handled = active.filter((ship) => ship.diagnostics.state === "handled");
    banner.dataset.state = reviews.length
      ? "review"
      : handled.length
        ? "handled"
        : "clear";
    node("alert-mark").setAttribute(
      "d",
      reviews.length ? "M10 4v6M10 13v.5" : "m5 10 3 3 7-7",
    );
    node("alert-title").textContent = reviews.length
      ? `${reviews.length} ${reviews.length === 1 ? "vessel needs" : "vessels need"} a human check.`
      : handled.length
        ? "Inconsistent positions flagged. Guarded ETA recomputed."
        : active.length
          ? "No freshness or position-consistency flags right now."
          : "The Antidote is waiting for the next arrival window.";
    node("alert-copy").textContent = reviews.length
      ? `The observable checks found old or unsupported evidence${this.guard ? "" : ", or the guard is disabled"}. Verify the report before relying on this estimate. Alerts are provisional.`
      : handled.length
        ? "The guard flagged jumps or within-minute disagreement. Consolidation is not a count of proven faults; the forecast remains provisional."
        : "Checks use received timestamps and motion consistency. Known injected labels are audience-only; an unflagged forecast can still be wrong.";
    node("inspect-alert").hidden = !reviews.length && !handled.length;
  }
  fullscreen() {
    const console = node("fleet-console");
    const expanded = console.classList.toggle("expanded");
    document.body.classList.toggle("fullscreen-open", expanded);
    this.fullscreenLabel();
    this.map?.resize();
  }
  fullscreenLabel() {
    const expanded =
      !!document.fullscreenElement ||
      node("fleet-console").classList.contains("expanded");
    node("fullscreen").setAttribute(
      "aria-label",
      expanded ? "Exit expanded product view" : "Expand product view",
    );
    node("fullscreen").setAttribute(
      "title",
      expanded ? "Exit expanded product view" : "Expand product view",
    );
    node("fullscreen").setAttribute("aria-expanded", String(expanded));
  }
  async loadSavedMetrics() {
    try {
      const metrics = /** @type {Metrics} */ (await get("/api/metrics"));
      if (!metrics.available) {
        node("saved-metrics").textContent =
          metrics.message ??
          "No protected evaluation is available in this artifact bundle.";
        return;
      }
      const conditions = [
        ["nominal", "Normal"],
        ["stale_15", "Stale only"],
        ["quality_0.5nm_25pct", "Position only"],
        ["combined_15_0.5nm_25pct", "Combined"],
      ];
      node("saved-metrics").innerHTML =
        `<table><thead><tr><th scope="col">Condition</th><th scope="col">Regression MAE</th><th scope="col">XGBoost MAE</th><th scope="col">Antidote MAE</th><th scope="col">Output coverage A / B / C</th></tr></thead><tbody>${conditions
          .map(([condition, label]) => {
            const rows = MODELS.map((model) =>
              metrics.summary.find(
                (row) => row.system === model.id && row.scenario === condition,
              ),
            );
            return `<tr><th scope="row">${label}</th>${rows.map((row) => `<td>${row ? row.approach_weighted_mae_minutes.toFixed(2) + " min" : "—"}</td>`).join("")}<td>${rows.map((row) => (row ? (row.output_coverage * 100).toFixed(1) + "%" : "—")).join(" / ")}</td></tr>`;
          })
          .join("")}</tbody></table>`;
    } catch {
      node("saved-metrics").textContent =
        "The saved evaluation could not be loaded. The live replay scores above remain exploratory.";
    }
  }
}
const app = new FleetApp();
void app.start();

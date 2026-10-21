/** @import {Catalog, Failure, ReplaySelection, ScenarioOption, Snapshot} from './types.js' */
import {ReplayApi, RequestScope, revealVerifiedSnapshot} from './api.js';
import {renderTimeline} from './charts.js';
import {EvidenceView} from './evidence.js';
import {clock, dateLabel, node, number, setOptions} from './format.js';
import {ReplayMap} from './map.js';
import {FeedInspectorView, ModelCardsView, element, renderOutcome} from './views.js';

const PLAYBACK_DELAY_MS = 1500;
const INITIAL_DECISION_INDEX = 20;

export class ReplayApp {
  api = new ReplayApi();
  requests = new RequestScope();
  inspector = new FeedInspectorView();
  cards = new ModelCardsView(element('cards', HTMLElement));
  controls = {
    approach: element('approach', HTMLSelectElement), decision: element('decision', HTMLSelectElement),
    slider: element('decision-slider', HTMLInputElement), prevalence: element('prevalence', HTMLSelectElement),
    experiment: element('experiment', HTMLSelectElement), inspect: element('inspect-toggle', HTMLInputElement),
    play: element('play', HTMLButtonElement), previous: element('previous', HTMLButtonElement),
    next: element('next', HTMLButtonElement), reveal: element('reveal', HTMLButtonElement),
    verify: element('verify', HTMLButtonElement),
  };
  /** @type {Catalog | null} */
  catalog = null;
  /** @type {ReplayMap | null} */
  map = null;
  /** @type {EvidenceView | null} */
  evidence = null;
  /** @type {Snapshot | null} */
  current = null;
  /** @type {Snapshot | null} */
  normal = null;
  /** @type {ReturnType<typeof setTimeout> | undefined} */
  playbackTimer;
  playing = false;
  scenario = '';
  revealed = false;
  reviewStarted = performance.now();

  async start() {
    this.catalog = await this.api.catalog();
    if (!this.catalog.approaches.length) throw new Error('No replay approaches are available. Prepare the dataset first.');
    this.evidence = new EvidenceView(this.catalog, failure => this.inspectFailure(failure));
    this.map = new ReplayMap(element('coordinate-map', SVGSVGElement), element('basemap', HTMLElement),
      element('map-status', HTMLElement), this.catalog.gate, identity => this.inspector.select(identity));
    this.scenario = this.catalog.scenarios[0];
    setOptions(this.controls.approach, this.catalog.approaches.map(approach => ({value: approach.id,
      label: `Vessel ${approach.mmsi} · ${dateLabel(approach.decisions[0].time)} · ${clock(approach.decisions[0].time)} UTC`})));
    this.buildScenarioControls();
    this.bindEvents();
    this.setApproach();
    this.controls.approach.disabled = false;
    this.controls.prevalence.disabled = false;
    this.controls.experiment.disabled = false;
    void this.loadEvidence();
    void this.configureMap();
    await this.load();
  }

  async loadEvidence() {
    try { this.evidence?.render(await this.api.metrics()); this.evidence?.highlight(this.scenario); }
    catch { element('cohort-summary', HTMLElement).textContent = 'Saved evaluation could not load. Replay remains available.'; }
  }

  async configureMap() {
    try {
      const config = await this.api.config();
      if (config.mapbox_public_token) await this.connectMap(config.mapbox_public_token);
    } catch { element('map-status', HTMLElement).textContent = 'Map settings could not load. Coordinate map is active.'; }
  }

  buildScenarioControls() {
    if (!this.catalog) return;
    const buttons = element('scenario-buttons', HTMLElement);
    const primary = this.catalog.scenario_options.filter(choice => choice.group === 'primary' && !choice.drift);
    const descriptions = ['No added faults', 'Original timestamps, late delivery', '926 m offsets in 25% of reports', '15-minute delay + 926 m offsets'];
    buttons.replaceChildren(...primary.map((choice, index) => {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'scenario-button'; button.dataset.scenario = choice.name;
      button.textContent = choice.label;
      button.append(node('span', descriptions[index]));
      button.addEventListener('click', () => this.chooseScenario(choice.name));
      return button;
    }));
    setOptions(this.controls.prevalence, [{value: '', label: 'Choose a fixed-volume prevalence'},
      ...this.catalog.scenario_options.filter(choice => choice.group === 'prevalence')
        .map(choice => ({value: choice.name, label: choice.label}))]);
    setOptions(this.controls.experiment, [{value: '', label: 'Choose an additional experiment'},
      ...this.catalog.scenario_options.filter(choice => choice.group === 'volume' || choice.drift)
        .map(choice => ({value: choice.name, label: choice.label}))]);
    this.syncScenario();
  }

  syncScenario() {
    const choice = this.catalog?.scenario_options.find(item => item.name === this.scenario);
    if (!choice) return;
    for (const button of document.querySelectorAll('button[data-scenario]')) {
      if (button instanceof HTMLButtonElement) button.setAttribute('aria-pressed', String(button.dataset.scenario === this.scenario));
    }
    this.controls.prevalence.value = choice.group === 'prevalence' ? choice.name : '';
    this.controls.experiment.value = choice.group === 'volume' || choice.drift ? choice.name : '';
    element('map-condition', HTMLElement).textContent = choice.label.toUpperCase();
    element('scenario-description', HTMLElement).textContent = this.describeScenario(choice);
    this.evidence?.highlight(this.scenario);
  }

  /** @param {ScenarioOption} choice */
  describeScenario(choice) {
    if (choice.drift) return 'Reserved test: position bias grows along past movement, up to 1 nautical mile over an hour.';
    const parts = [];
    if (choice.delay_minutes) parts.push(`Reports arrive ${choice.delay_minutes} minutes late.`);
    if (choice.affected_fraction) parts.push(`${number(choice.affected_fraction * 100, 0)}% of original reports selected for ${number(choice.offset_nautical_miles * 1852, 0)} m position offsets.`);
    if (choice.repetition > 1) parts.push(`Affected reports repeated ×${choice.repetition}.`);
    if (choice.total_repetition > 1) parts.push(`All reports repeated ×${choice.total_repetition}.`);
    return parts.join(' ') || 'Original reports with no added reporting faults.';
  }

  /** @param {string} [decisionId] */
  setApproach(decisionId) {
    const approach = this.catalog?.approaches.find(item => item.id === this.controls.approach.value);
    if (!approach) throw new Error('The selected approach is unavailable.');
    setOptions(this.controls.decision, approach.decisions.map(decision => ({value: decision.id, label: `${clock(decision.time, true)} UTC`})));
    const midpoint = Math.floor((approach.decisions.length - 1) / 2);
    this.controls.decision.selectedIndex = Math.min(INITIAL_DECISION_INDEX, midpoint);
    if (decisionId) this.controls.decision.value = decisionId;
    this.controls.slider.max = String(approach.decisions.length - 1);
    this.updateDecisionControls();
  }

  updateDecisionControls() {
    const index = this.controls.decision.selectedIndex;
    this.controls.slider.value = String(index);
    element('decision-position', HTMLElement).textContent = `${index + 1} / ${this.controls.decision.options.length}`;
  }

  /** @returns {ReplaySelection} */
  selection() {
    return {decision: this.controls.decision.value, scenario: this.scenario,
      reveal: this.revealed, inspect: this.controls.inspect.checked};
  }

  /** @param {boolean} busy */
  setBusy(busy) {
    document.body.classList.toggle('is-loading', busy);
    element('cards', HTMLElement).setAttribute('aria-busy', String(busy));
    this.controls.reveal.disabled = busy || !this.current;
    this.controls.verify.disabled = busy || !this.current || !!this.current.human_assisted;
    this.controls.inspect.disabled = busy || !!this.current?.human_assisted;
    this.controls.play.disabled = busy || this.controls.decision.options.length < 2;
    this.controls.previous.disabled = busy || this.controls.decision.selectedIndex <= 0;
    this.controls.next.disabled = busy || this.controls.decision.selectedIndex >= this.controls.decision.options.length - 1;
    this.controls.slider.disabled = busy;
    this.controls.decision.disabled = busy;
  }

  hideOutcome() {
    element('outcome', HTMLElement).hidden = true;
    for (const old of document.querySelectorAll('.revealed-error')) old.remove();
    element('eta-timeline', HTMLElement).replaceChildren(node('p', 'Loading forecast history for this selection…', 'empty-state'));
  }

  /** @param {ReplaySelection} selection @param {AbortSignal} signal @param {number} version */
  async loadTimeline(selection, signal, version) {
    try {
      const timeline = await this.api.timeline(selection, signal);
      if (!this.requests.isCurrent(version) || !this.current) return;
      renderTimeline(element('eta-timeline', HTMLElement), timeline, this.current);
      element('timeline-note', HTMLElement).textContent = `Saved unattended evaluation forecasts · seed ${timeline.seed} · verification does not rewrite this comparison.`;
    } catch {
      if (!signal.aborted && this.requests.isCurrent(version)) element('eta-timeline', HTMLElement)
        .replaceChildren(node('p', 'Forecast history could not load. Current ETA cards remain available.', 'empty-state'));
    }
  }

  async load() {
    const {version, signal} = this.requests.begin();
    const selection = this.selection();
    const verified = this.current?.human_assisted && this.current.decision_id === selection.decision
      && this.current.scenario === selection.scenario && selection.reveal ? this.current : null;
    this.setBusy(true);
    this.hideOutcome();
    element('error-banner', HTMLElement).hidden = true;
    try {
      const normalName = this.catalog?.scenarios[0] ?? 'nominal';
      const [snapshot, normal] = await Promise.all([this.api.snapshot(selection, signal),
        selection.scenario === normalName ? Promise.resolve(null) : this.api.snapshot(
          {...selection, scenario: normalName, reveal: false, inspect: false}, signal)]);
      if (!this.requests.isCurrent(version)) return;
      this.normal = normal ?? snapshot;
      this.render(verified ? revealVerifiedSnapshot(verified, snapshot) : snapshot);
      await this.loadTimeline(selection, signal, version);
    } catch (error) {
      if (!signal.aborted && this.requests.isCurrent(version)) {
        this.stop(); this.current = null; this.normal = null;
        element('workspace', HTMLElement).hidden = true;
        element('inspection-panel', HTMLElement).hidden = true;
        element('cards', HTMLElement).replaceChildren(node('p', 'Forecasts unavailable for this selection. Choose a condition or time to retry.', 'empty-state'));
        element('replay-clock', HTMLElement).textContent = 'Unavailable';
        this.showError(error);
      }
    } finally {
      if (this.requests.isCurrent(version)) this.setBusy(false);
    }
  }

  /** @param {Snapshot} snapshot */
  render(snapshot) {
    this.current = snapshot;
    if (!this.normal) return;
    element('workspace', HTMLElement).hidden = false;
    this.cards.render(snapshot, this.normal);
    this.inspector.render(snapshot);
    this.map?.render(snapshot, this.controls.approach.value);
    renderOutcome(snapshot);
    element('fault-legend', HTMLElement).hidden = !snapshot.inspection;
    element('replay-clock', HTMLElement).textContent = clock(snapshot.decision_time, true);
    element('replay-date', HTMLElement).textContent = dateLabel(snapshot.decision_time);
    element('run-mode', HTMLElement).textContent = snapshot.human_assisted ? 'HUMAN ASSISTED' : 'UNATTENDED';
    element('run-seed', HTMLElement).textContent = `Seed ${snapshot.seed} · ${this.catalog?.split} replay`;
    element('status', HTMLElement).textContent = `${clock(snapshot.decision_time)} UTC. ${snapshot.human_assisted ? 'Human-assisted' : 'Unattended'} forecasts loaded.`;
    this.controls.reveal.textContent = snapshot.reference_arrival ? 'Crossing revealed' : 'Reveal crossing & errors';
    element('verification-note', HTMLElement).textContent = snapshot.human_assisted
      ? `Human-assisted result. Verified report: ${clock(snapshot.verified_observation_time, true)} UTC. Change time or condition to return to unattended replay. The inspector is fixed to this verified input.`
      : 'Verification supplies a historical report measured by this replay time. It is logged as human assisted. Walkthrough time is not a validated operator-workload measure.';
  }

  /** @param {string} name */
  chooseScenario(name) {
    if (!name || !this.catalog?.scenario_options.some(choice => choice.name === name)) return;
    this.stop(); this.scenario = name; this.revealed = false; this.reviewStarted = performance.now();
    this.syncScenario(); void this.load();
  }

  /** @param {number} delta */
  async step(delta) {
    const next = this.controls.decision.selectedIndex + delta;
    if (next < 0 || next >= this.controls.decision.options.length) {this.stop(); return;}
    this.controls.decision.selectedIndex = next;
    this.updateDecisionControls(); this.revealed = false; this.reviewStarted = performance.now();
    await this.load();
  }

  schedulePlayback() {
    this.playbackTimer = setTimeout(async () => {
      if (!this.playing) return;
      await this.step(1);
      if (this.playing) this.schedulePlayback();
    }, PLAYBACK_DELAY_MS);
  }

  async togglePlayback() {
    if (this.playing) {this.stop(); return;}
    if (this.controls.decision.selectedIndex === this.controls.decision.options.length - 1) {
      await this.step(-this.controls.decision.selectedIndex);
      if (!this.current) return;
    }
    this.playing = true;
    this.controls.play.textContent = 'Pause replay';
    this.schedulePlayback();
  }

  stop() {
    this.playing = false; clearTimeout(this.playbackTimer);
    this.controls.play.textContent = 'Play replay';
  }

  async verify() {
    this.stop();
    const {version, signal} = this.requests.begin();
    this.setBusy(true); this.revealed = false;
    this.hideOutcome();
    try {
      const snapshot = await this.api.verify(this.selection(), (performance.now() - this.reviewStarted) / 1000, signal);
      if (this.requests.isCurrent(version)) {
        this.render(snapshot);
        await this.loadTimeline(this.selection(), signal, version);
      }
    } catch (error) {if (!signal.aborted) this.showError(error);}
    finally {if (this.requests.isCurrent(version)) this.setBusy(false);}
  }

  /** @param {Failure} failure */
  inspectFailure(failure) {
    this.stop();
    this.controls.approach.value = failure.approach_id;
    this.setApproach(failure.decision_id);
    this.scenario = failure.scenario; this.revealed = true;
    this.syncScenario(); void this.load();
    element('forecasts-title', HTMLElement).scrollIntoView({block: 'start'});
  }

  /** @param {string} token */
  async connectMap(token) {
    const connect = element('connect-map', HTMLButtonElement);
    connect.disabled = true;
    try {await this.map?.connect(token);}
    catch (error) {element('map-status', HTMLElement).textContent = error instanceof Error ? error.message : 'Mapbox is unavailable.';}
    finally {connect.disabled = false;}
  }

  /** @param {unknown} error */
  showError(error) {
    const banner = element('error-banner', HTMLElement);
    banner.textContent = error instanceof Error ? error.message : 'The replay could not load. Please try again.';
    banner.hidden = false;
  }

  bindEvents() {
    this.controls.approach.addEventListener('change', () => {this.stop(); this.revealed = false; this.setApproach(); this.reviewStarted = performance.now(); void this.load();});
    this.controls.prevalence.addEventListener('change', () => this.chooseScenario(this.controls.prevalence.value));
    this.controls.experiment.addEventListener('change', () => this.chooseScenario(this.controls.experiment.value));
    this.controls.inspect.addEventListener('change', () => {this.stop(); void this.load();});
    this.controls.decision.addEventListener('change', () => {this.stop(); this.updateDecisionControls(); this.revealed = false; this.reviewStarted = performance.now(); void this.load();});
    this.controls.slider.addEventListener('input', () => {
      this.stop(); this.controls.decision.selectedIndex = Number(this.controls.slider.value); this.updateDecisionControls();
    });
    this.controls.slider.addEventListener('change', () => {this.revealed = false; this.reviewStarted = performance.now(); void this.load();});
    this.controls.previous.addEventListener('click', () => {this.stop(); void this.step(-1);});
    this.controls.next.addEventListener('click', () => {this.stop(); void this.step(1);});
    this.controls.play.addEventListener('click', () => void this.togglePlayback());
    this.controls.reveal.addEventListener('click', () => {this.stop(); this.revealed = true; void this.load();});
    this.controls.verify.addEventListener('click', () => void this.verify());
    element('fit-map', HTMLButtonElement).addEventListener('click', () => this.map?.fit());
    element('open-map-settings', HTMLButtonElement).addEventListener('click', () => {
      element('map-settings', HTMLDetailsElement).open = true;
      element('mapbox-token', HTMLInputElement).focus();
    });
    element('map-settings-form', HTMLFormElement).addEventListener('submit', event => {
      event.preventDefault(); const field = element('mapbox-token', HTMLInputElement);
      const token = field.value.trim(); field.value = ''; void this.connectMap(token);
    });
    element('use-coordinates', HTMLButtonElement).addEventListener('click', () => this.map?.useCoordinates());
    window.addEventListener('pagehide', () => this.destroy(), {once: true});
  }

  destroy() {this.stop(); this.requests.controller.abort(); this.map?.destroy();}
}

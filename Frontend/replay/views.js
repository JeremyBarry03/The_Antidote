/** @import {Snapshot} from './types.js' */
import {MODEL_NAMES, clock, dateLabel, minutesBetween, node, number, setOptions, signedMinutes} from './format.js';

const REASON_LABELS = Object.freeze({implausible_position_jump: 'Implausible position jump',
  conflicting_bin_positions: 'Conflicting positions within a time bin',
  bounded_repeated_report_weight: 'Repeated-report influence bounded', no_reports: 'No delivered reports'});

/** @template {Element} T @param {string} id @param {{new(): T}} constructor @returns {T} */
export function element(id, constructor) {
  const match = document.getElementById(id);
  if (!(match instanceof constructor)) throw new Error(`Required page element is missing: ${id}`);
  return match;
}

export class ModelCardsView {
  /** @param {HTMLElement} container */
  constructor(container) { this.container = container; }

  /** @param {Snapshot} snapshot @param {Snapshot} normal */
  render(snapshot, normal) {
    this.container.replaceChildren();
    for (const card of snapshot.cards) {
      const article = node('article', '', `model-card model-${card.system.toLowerCase()}`);
      const header = node('div', '', 'model-heading');
      header.append(node('span', card.system, 'model-letter'), node('h3', MODEL_NAMES[card.system]));
      article.append(header, node('p', 'PREDICTED CROSSING · UTC', 'eyebrow'));
      article.append(node('p', card.available ? clock(card.predicted_arrival_time) : 'Unavailable', 'eta'));
      const remaining = card.predicted_remaining_minutes;
      article.append(node('p', remaining == null ? 'No supported forecast from the delivered history.'
        : remaining < 0 ? `Forecast is ${number(-remaining)} min before the replay clock.`
          : `${number(remaining)} min from the replay clock`, 'muted'));
      const reference = normal.cards.find(item => item.system === card.system);
      const shift = minutesBetween(card.predicted_arrival_time, reference?.predicted_arrival_time ?? null);
      article.append(node('p', `Shift vs normal replay: ${signedMinutes(shift)}`, 'card-comparison'));
      article.append(node('p', `Usable evidence age: ${number(card.report_age_minutes)} min`, 'muted'));
      if (snapshot.reference_arrival) {
        const error = card.error_minutes;
        article.append(node('p', error == null ? 'No forecast to score' : `Absolute error: ${number(Math.abs(error))} min`, 'error-result revealed-error'));
        if (error != null) article.append(node('p', `${signedMinutes(error)} · positive means late`, 'muted revealed-error'));
      }
      this.container.append(article);
    }
  }
}

export class FeedInspectorView {
  /** @type {Snapshot | null} */
  snapshot = null;
  selectedId = '';

  constructor() {
    this.age = element('report-age', HTMLElement);
    this.counts = element('feed-counts', HTMLElement);
    this.signals = element('observable-signals', HTMLElement);
    this.panel = element('inspection-panel', HTMLElement);
    this.summary = element('injection-summary', HTMLElement);
    this.reports = element('report-select', HTMLSelectElement);
    this.detail = element('report-detail', HTMLElement);
    this.reports.addEventListener('change', () => this.select(this.reports.value));
  }

  /** @param {Snapshot} snapshot */
  render(snapshot) {
    this.snapshot = snapshot;
    const diagnostics = snapshot.observable_diagnostics;
    const latest = snapshot.received_history.at(-1);
    const age = latest ? minutesBetween(snapshot.decision_time, latest.time) : null;
    this.age.textContent = latest ? `${number(age)} min old` : 'No report yet';
    element('observed-clock', HTMLElement).textContent = `${clock(latest?.time, true)} UTC`;
    element('delivered-clock', HTMLElement).textContent = `${clock(latest?.delivered_time, true)} UTC`;
    const counts = snapshot.feed_counts;
    element('window-description', HTMLElement).textContent = `Last ${counts.history_minutes} min of received evidence · ${counts.received_total} reports delivered in this approach`;
    this.counts.replaceChildren();
    const retained = diagnostics.guard_received_count - diagnostics.guard_removed_count;
    for (const [label, value] of [['Received messages', counts.received_in_window],
      ['Unique reports', counts.unique_in_window], ['Occupied time bins', counts.occupied_bins], ['C retained summaries', retained]]) {
      const item = node('div');
      item.append(node('dt', String(label)), node('dd', String(value)));
      this.counts.append(item);
    }
    this.signals.replaceChildren();
    const reasons = (diagnostics.reasons ?? '').split('|').filter(Boolean);
    this.signals.append(node('p', reasons.length ? reasons.map(reason =>
      REASON_LABELS[/** @type {keyof typeof REASON_LABELS} */ (reason)] ?? reason.replaceAll('_', ' ')).join(' · ')
      : 'No guard warning triggered. This does not prove the reports are correct.', 'signal-summary'));
    this.signals.append(node('p', `Largest bin spread: ${number(diagnostics.maximum_bin_spread_meters, 0)} m · speed disagreement: ${number(diagnostics.velocity_disagreement_mps)} m/s`, 'muted'));
    this.panel.hidden = !snapshot.inspection;
    if (!snapshot.inspection) return;
    const inspection = snapshot.inspection;
    this.summary.textContent = `${inspection.affected_in_window} of ${counts.received_in_window} received messages carry the main position bias (${number(
      inspection.actual_affected_share == null ? null : inspection.actual_affected_share * 100)}%). Counts include copies.`;
    setOptions(this.reports, inspection.records.map(report => ({value: report.record_id,
      label: `${clock(report.time, true)} · ${report.fault_applied ? 'altered' : 'no main position bias'}${report.record_id.includes('repeat-') || report.record_id.includes('volume-') ? ' · copy' : ''}`})));
    const selected = inspection.records.find(report => report.record_id === this.selectedId)
      ?? inspection.records.findLast(report => report.fault_applied) ?? inspection.records.at(-1);
    this.select(selected?.record_id ?? '');
    element('visible-report-note', HTMLElement).textContent = `Map and selector show up to ${inspection.visible_limit} recent records. Counts cover the full evidence window.`;
  }

  /** @param {string} identity */
  select(identity) {
    this.selectedId = identity;
    const report = this.snapshot?.inspection?.records.find(item => item.record_id === identity);
    this.detail.replaceChildren();
    if (!report) {
      this.detail.append(node('p', this.snapshot?.inspection ? 'No delivered record is available in this window.'
        : 'Enable the simulation inspector to inspect known injected changes.', 'muted'));
      return;
    }
    this.reports.value = identity;
    const fields = [['Generated', `${clock(report.time, true)} UTC`], ['Delivered', `${clock(report.delivered_time, true)} UTC`],
      ['Original archive position', `${number(report.original_latitude, 5)}, ${number(report.original_longitude, 5)}`],
      ['Delivered position', `${number(report.latitude, 5)}, ${number(report.longitude, 5)}`],
      ['Injected displacement', `${number(report.offset_meters, 1)} metres`]];
    for (const [label, value] of fields) {
      const row = node('div', '', 'detail-row');
      row.append(node('dt', label), node('dd', value));
      this.detail.append(row);
    }
  }
}

/** @param {Snapshot} snapshot */
export function renderOutcome(snapshot) {
  const outcome = element('outcome', HTMLElement);
  outcome.hidden = !snapshot.reference_arrival;
  outcome.replaceChildren();
  if (!snapshot.reference_arrival) return;
  outcome.append(node('strong', `Recorded crossing: ${clock(snapshot.reference_arrival, true)} UTC`));
  const bracket = snapshot.reference_bracket?.map(value => clock(value, true)).join('–');
  outcome.append(node('span', ` · ${dateLabel(snapshot.reference_arrival)} · ${bracket ? `bracket ${bracket} UTC` : 'crossing bracket unavailable'}`));
}

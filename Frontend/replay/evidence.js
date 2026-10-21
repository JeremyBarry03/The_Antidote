/** @import {Catalog, Failure, MetricRow, Metrics} from './types.js' */
import {clock, dateLabel, number} from './format.js';
import {element} from './views.js';

export class EvidenceView {
  /** @param {Catalog} catalog @param {(failure: Failure) => void} onFailure */
  constructor(catalog, onFailure) {
    this.catalog = catalog;
    this.onFailure = onFailure;
  }

  /** @param {MetricRow[]} rows @param {HTMLElement} container */
  table(rows, container) {
    const table = document.createElement('table');
    const head = table.createTHead().insertRow();
    for (const text of ['Input condition', 'A · MAE', 'B · MAE', 'C · MAE', 'Output coverage¹']) {
      const cell = document.createElement('th');
      cell.scope = 'col';
      cell.textContent = text;
      head.append(cell);
    }
    const body = table.createTBody();
    const names = [...new Set(rows.map(row => row.scenario))];
    for (const name of names) {
      const tr = body.insertRow();
      tr.dataset.scenario = name;
      const title = document.createElement('th');
      title.scope = 'row';
      title.textContent = this.catalog.scenario_options.find(choice => choice.name === name)?.label ?? name;
      tr.append(title);
      for (const system of ['A', 'B', 'C']) {
        const row = rows.find(item => item.scenario === name && item.system === system);
        tr.insertCell().textContent = row ? `${number(row.approach_weighted_mae_minutes, 2)} min` : '—';
      }
      const cases = rows.filter(row => row.scenario === name && ['A', 'B', 'C'].includes(row.system));
      const sameCoverage = cases.every(row => row.output_coverage === cases[0]?.output_coverage);
      tr.insertCell().textContent = sameCoverage ? `${number((cases[0]?.output_coverage ?? 0) * 100)}%`
        : cases.map(row => `${row.system}: ${number(row.output_coverage * 100)}%`).join(' / ');
    }
    container.replaceChildren(table);
  }

  /** @param {Metrics} metrics */
  render(metrics) {
    if (!metrics.available) {
      element('cohort-summary', HTMLElement).textContent = metrics.message ?? 'Evaluation evidence is unavailable.';
      return;
    }
    const example = metrics.summary[0];
    element('cohort-summary', HTMLElement).textContent = example
      ? `${example.scheduled_approaches} approaches · ${example.vessels} vessels · ${example.seeds} paired seeds · April evaluation`
      : 'Saved evaluation results';
    this.table(metrics.summary.filter(row => ['A', 'B', 'C'].includes(row.system)), element('primary-metrics', HTMLElement));
    this.table(metrics.volume_summary.filter(row => ['A', 'B', 'C'].includes(row.system)), element('volume-metrics', HTMLElement));
    const failures = element('failure-examples', HTMLElement);
    failures.replaceChildren();
    for (const failure of metrics.failures) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'failure-button';
      button.textContent = `Inspect C failure · ${number(Math.abs(failure.error_minutes))} min error · ${dateLabel(failure.decision_time)} ${clock(failure.decision_time)} UTC`;
      button.addEventListener('click', () => this.onFailure(failure));
      failures.append(button);
    }
    const policy = metrics.review_policy;
    element('review-policy-note', HTMLElement).textContent = policy?.scheduled
      ? `The predeclared ±${number(policy.tolerance_minutes, 0)}-minute review policy accepted ${policy.accepted.toLocaleString()} of ${policy.scheduled.toLocaleString()} C forecasts across conditions and seeds. Broad empirical envelopes can create an impractical review burden. Acceptance is not a validated safety guarantee.`
      : 'Acceptance-policy evidence is unavailable. This demo makes no operational safety guarantee.';
  }

  /** @param {string} name */
  highlight(name) {
    for (const row of document.querySelectorAll('tr[data-scenario]')) {
      if (row instanceof HTMLTableRowElement) row.classList.toggle('selected-row', row.dataset.scenario === name);
    }
  }
}

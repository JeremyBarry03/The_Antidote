/** @import {Catalog, Metrics, PublicConfig, ReplaySelection, Snapshot, Timeline} from './types.js' */
import {minutesBetween} from './format.js';

/** Keep the verified forecasts when revealing their original reference outcome.
 * @param {Snapshot} verified @param {Snapshot} revealed @returns {Snapshot}
 */
export function revealVerifiedSnapshot(verified, revealed) {
  return {...verified, reference_arrival: revealed.reference_arrival, reference_bracket: revealed.reference_bracket,
    cards: verified.cards.map(card => ({...card,
      error_minutes: minutesBetween(card.predicted_arrival_time, revealed.reference_arrival)}))};
}

/** Latest user selection owns the screen, including errors and timeline responses. */
export class RequestScope {
  controller = new AbortController();
  version = 0;

  begin() {
    this.controller.abort();
    this.controller = new AbortController();
    this.version += 1;
    return {version: this.version, signal: this.controller.signal};
  }

  /** @param {number} version */
  isCurrent(version) { return this.version === version; }
}

export class ReplayApi {
  /** @template T @param {string} path @param {RequestInit} [options] @returns {Promise<T>} */
  async request(path, options) {
    const response = await fetch(path, options);
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Replay request failed (${response.status}).`);
    return result;
  }

  /** @returns {Promise<Catalog>} */
  catalog() { return this.request('/api/catalog'); }

  /** @returns {Promise<Metrics>} */
  metrics() { return this.request('/api/metrics'); }

  /** @returns {Promise<PublicConfig>} */
  config() { return this.request('/api/config'); }

  /** @param {ReplaySelection} selection @param {AbortSignal} signal @returns {Promise<Snapshot>} */
  snapshot(selection, signal) {
    const query = new URLSearchParams(Object.entries(selection).map(([key, value]) => [key, String(value)]));
    return this.request(`/api/replay?${query}`, {signal});
  }

  /** @param {ReplaySelection} selection @param {AbortSignal} signal @returns {Promise<Timeline>} */
  timeline(selection, signal) {
    const query = new URLSearchParams({decision: selection.decision, scenario: selection.scenario,
      reveal: String(selection.reveal)});
    return this.request(`/api/timeline?${query}`, {signal});
  }

  /** @param {ReplaySelection} selection @param {number} reviewSeconds @param {AbortSignal} signal @returns {Promise<Snapshot>} */
  verify(selection, reviewSeconds, signal) {
    return this.request('/api/verify', {method: 'POST', signal, headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({decision: selection.decision, scenario: selection.scenario,
        inspect: selection.inspect, review_seconds: reviewSeconds})});
  }
}

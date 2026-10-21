// @vitest-environment jsdom
/** @import {Catalog, Snapshot} from '../types.js' */
import {readFileSync} from 'node:fs';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {ReplayApp} from '../app.js';
import {revealVerifiedSnapshot} from '../api.js';
import {clock, minutesBetween, utcDate} from '../format.js';
import {mapFeatures} from '../map.js';
import {ModelCardsView} from '../views.js';

const PAGE_HTML = readFileSync('replay/tests/fixtures/single-replay.html', 'utf8');
const GATE = {longitude: -76.3, south: 36.95, north: 37.05};

/** @param {Partial<Snapshot>} [overrides] @returns {Snapshot} */
function snapshot(overrides = {}) {
  return {
    decision_id: 'decision-2', decision_time: '2024-04-08T12:16:00', scenario: 'nominal', seed: 4201,
    cards: ['A', 'B', 'C'].map(system => ({system: /** @type {'A' | 'B' | 'C'} */ (system), available: true,
      predicted_arrival_time: '2024-04-08T12:30:00', predicted_remaining_minutes: 14,
      report_age_minutes: 1, interval_half_width_minutes: 40, calibration_approaches: 50,
      review_reason: 'interval_too_wide', accepted: false, reasons: ''})),
    received_history: [{record_id: 'one', time: '2024-04-08T12:15:00', delivered_time: '2024-04-08T12:15:00',
      longitude: -76.2, latitude: 37, sog: 10}],
    feed_counts: {received_total: 1, received_in_window: 1, unique_in_window: 1,
      exact_duplicates_in_window: 0, occupied_bins: 1, history_minutes: 30, bin_seconds: 60},
    observable_diagnostics: {latest_received_age_minutes: 1, latest_usable_age_minutes: 1,
      maximum_bin_spread_meters: 0, velocity_disagreement_mps: null, maximum_gap_seconds: null,
      occupied_minute_bins: 1, guard_received_count: 1, guard_removed_count: 0, reasons: ''},
    inspection: null, human_assisted: false, verified_observation_time: null,
    reference_arrival: null, reference_bracket: null, ...overrides,
  };
}

/** @returns {Catalog} */
function catalog() {
  const base = {delay_minutes: 0, offset_nautical_miles: 0, affected_fraction: 0,
    repetition: 1, total_repetition: 1, repetition_jitter_meters: 0, drift: false};
  return {approaches: [{id: 'voyage', mmsi: '123456789', decisions: [
    {id: 'decision-1', time: '2024-04-08T12:15:00'}, {id: 'decision-2', time: '2024-04-08T12:16:00'}]}],
    scenarios: ['nominal', 'stale_15', 'quality', 'combined'], scenario_options: [
      {...base, name: 'nominal', label: 'Normal reports', group: 'primary', condition: 'nominal'},
      {...base, name: 'stale_15', label: 'Delayed 15 minutes', group: 'primary', condition: 'stale', delay_minutes: 15},
      {...base, name: 'quality', label: 'Incorrect positions', group: 'primary', condition: 'quality', affected_fraction: .25, offset_nautical_miles: .5},
      {...base, name: 'combined', label: 'Combined', group: 'primary', condition: 'combined', delay_minutes: 15, affected_fraction: .25, offset_nautical_miles: .5},
    ], replay_seed: 4201, split: 'evaluation', calibrated: true, gate: GATE};
}

/** @type {ReplayApp | null} */
let app = null;

beforeEach(() => {
  document.documentElement.innerHTML = PAGE_HTML.replace(/<!doctype html>/i, '').replace(/<\/?html[^>]*>/gi, '');
  vi.stubGlobal('ResizeObserver', class {observe() {} disconnect() {}});
});

afterEach(() => {app?.destroy(); app = null; vi.restoreAllMocks(); vi.unstubAllGlobals();});

async function startApp() {
  const instance = new ReplayApp();
  app = instance;
  vi.spyOn(instance.api, 'catalog').mockResolvedValue(catalog());
  vi.spyOn(instance.api, 'config').mockResolvedValue({mapbox_public_token: null});
  vi.spyOn(instance.api, 'metrics').mockResolvedValue({available: false, summary: [], volume_summary: [], failures: []});
  vi.spyOn(instance.api, 'timeline').mockResolvedValue({available: false, points: [], seed: 4201});
  vi.spyOn(instance.api, 'snapshot').mockImplementation(async selection => snapshot({decision_id: selection.decision,
    scenario: selection.scenario, ...(selection.reveal ? {reference_arrival: '2024-04-08T12:35:00',
      reference_bracket: ['2024-04-08T12:34:00', '2024-04-08T12:36:00'],
      cards: snapshot().cards.map(card => ({...card, error_minutes: -5}))} : {})}));
  await instance.start();
  return instance;
}

describe('causal audience presentation', () => {
  it('treats archive times as UTC and handles midnight differences', () => {
    expect(utcDate('2024-04-08T12:00:00').toISOString()).toBe('2024-04-08T12:00:00.000Z');
    expect(clock('2024-04-08T08:00:00-04:00')).toBe('12:00');
    expect(minutesBetween('2024-04-09T00:05:00', '2024-04-08T23:55:00')).toBe(10);
    expect(minutesBetween(null, '2024-04-08T12:00:00')).toBeNull();
  });

  it('hides errors until reference reveal and displays unavailable forecasts honestly', () => {
    const container = document.createElement('div');
    const view = new ModelCardsView(container);
    const original = snapshot();
    view.render(original, original);
    expect(container.textContent).not.toContain('Absolute error');
    const revealed = snapshot({reference_arrival: '2024-04-08T12:35:00',
      cards: original.cards.map(card => ({...card, error_minutes: -5}))});
    view.render(revealed, original);
    expect(container.textContent).toContain('Absolute error: 5.0 min');
    view.render(snapshot({cards: original.cards.map(card => ({...card, available: false,
      predicted_arrival_time: null, predicted_remaining_minutes: null}))}), original);
    expect(container.textContent).toContain('Unavailable');
    expect(container.textContent).not.toContain('Absolute error');
  });

  it('adds original positions and known-fault colors only in the audience inspection layer', () => {
    const original = snapshot();
    const hidden = mapFeatures(original, GATE);
    expect(hidden.features.some(feature => feature.properties?.kind === 'original')).toBe(false);
    expect(hidden.features.some(feature => feature.properties?.altered)).toBe(false);
    const shown = mapFeatures(snapshot({inspection: {audience_only: true, affected_in_window: 1,
      actual_affected_share: 1, visible_limit: 150, records: [{...original.received_history[0],
        fault_applied: true, original_longitude: -76.21, original_latitude: 37, offset_meters: 926}]}}), GATE);
    expect(shown.features.some(feature => feature.properties?.kind === 'displacement')).toBe(true);
    expect(shown.features.find(feature => feature.properties?.kind === 'report')?.properties?.altered).toBe(true);
    expect(original.received_history[0].longitude).toBe(-76.2);
  });

  it('preserves a verified forecast when reference truth is revealed', () => {
    const verified = snapshot({human_assisted: true,
      cards: snapshot().cards.map(card => ({...card, predicted_arrival_time: '2024-04-08T12:34:00'}))});
    const result = revealVerifiedSnapshot(verified, snapshot({reference_arrival: '2024-04-08T12:35:00'}));
    expect(result.human_assisted).toBe(true);
    expect(result.cards[0].predicted_arrival_time).toBe('2024-04-08T12:34:00');
    expect(result.cards[0].error_minutes).toBe(-1);
  });
});

describe('replay interactions', () => {
  it('clears revealed truth immediately when the condition changes', async () => {
    const instance = await startApp();
    instance.revealed = true;
    await instance.load();
    expect(document.getElementById('outcome')?.hidden).toBe(false);
    instance.chooseScenario('stale_15');
    expect(document.getElementById('outcome')?.hidden).toBe(true);
    expect(document.querySelectorAll('.error-result')).toHaveLength(0);
    expect(document.getElementById('cards')?.textContent).not.toContain('positive means late');
    await vi.waitFor(() => expect(instance.current?.scenario).toBe('stale_15'));
    expect(instance.current?.reference_arrival).toBeNull();
  });

  it('does not let an older response overwrite a newer condition', async () => {
    const instance = await startApp();
    /** @type {(value: Snapshot) => void} */
    let finishOld = () => {};
    const old = new Promise(resolve => {finishOld = resolve;});
    vi.mocked(instance.api.snapshot).mockImplementation(async selection => selection.scenario === 'quality'
      ? /** @type {Promise<Snapshot>} */ (old) : snapshot({scenario: selection.scenario}));
    instance.chooseScenario('quality');
    instance.chooseScenario('stale_15');
    await vi.waitFor(() => expect(instance.current?.scenario).toBe('stale_15'));
    finishOld(snapshot({scenario: 'quality'}));
    await old;
    await Promise.resolve();
    expect(instance.current?.scenario).toBe('stale_15');
    expect(document.getElementById('map-condition')?.textContent).toBe('DELAYED 15 MINUTES');
  });

  it('keeps human-assisted estimates through reveal and resets on condition change', async () => {
    const instance = await startApp();
    vi.spyOn(instance.api, 'verify').mockImplementation(async selection => snapshot({decision_id: selection.decision, human_assisted: true,
      verified_observation_time: '2024-04-08T12:16:00',
      cards: snapshot().cards.map(card => ({...card, predicted_arrival_time: '2024-04-08T12:34:00'}))}));
    await instance.verify();
    expect(instance.controls.inspect.disabled).toBe(true);
    instance.revealed = true;
    await instance.load();
    expect(instance.current?.human_assisted).toBe(true);
    expect(instance.current?.cards[0].error_minutes).toBe(-1);
    expect(instance.api.verify).toHaveBeenCalledTimes(1);
    instance.chooseScenario('stale_15');
    await vi.waitFor(() => expect(instance.current?.scenario).toBe('stale_15'));
    expect(instance.current?.human_assisted).toBe(false);
  });

  it('rejects secret map tokens and leaves the coordinate plot usable', async () => {
    const instance = await startApp();
    await instance.connectMap('sk.not-a-public-token');
    expect(document.getElementById('map-status')?.textContent).toContain('public Mapbox token');
    expect(document.getElementById('coordinate-map')?.hasAttribute('hidden')).toBe(false);
  });

  it('removes stale forecasts after a failed request and recovers on the next selection', async () => {
    const instance = await startApp();
    vi.mocked(instance.api.snapshot).mockRejectedValueOnce(new Error('The selected replay could not load.'));
    instance.chooseScenario('quality');
    await vi.waitFor(() => expect(instance.current).toBeNull());
    expect(document.getElementById('workspace')?.hidden).toBe(true);
    expect(document.getElementById('cards')?.textContent).toContain('Forecasts unavailable');
    expect(document.getElementById('error-banner')?.textContent).toContain('could not load');
    instance.chooseScenario('nominal');
    await vi.waitFor(() => expect(instance.current?.scenario).toBe('nominal'));
    expect(document.getElementById('workspace')?.hidden).toBe(false);
    expect(document.getElementById('error-banner')?.hidden).toBe(true);
  });

  it('starts with room to play and restarts playback after the final decision', async () => {
    const instance = await startApp();
    expect(instance.controls.next.disabled).toBe(false);
    instance.controls.decision.selectedIndex = 1;
    await instance.load();
    await instance.togglePlayback();
    expect(instance.controls.decision.selectedIndex).toBe(0);
    expect(instance.playing).toBe(true);
    instance.stop();
    expect(instance.playing).toBe(false);
  });
});

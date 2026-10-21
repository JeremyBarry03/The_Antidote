export type SystemName = "A" | "B" | "C";
export interface Decision { id: string; time: string; }
export interface Approach { id: string; mmsi: string; decisions: Decision[]; }
export interface Gate { longitude: number; south: number; north: number; }
export interface ScenarioOption {
  name: string;
  label: string;
  group: "primary" | "prevalence" | "volume";
  condition: "nominal" | "stale" | "quality" | "combined";
  delay_minutes: number;
  offset_nautical_miles: number;
  affected_fraction: number;
  repetition: number;
  total_repetition: number;
  repetition_jitter_meters: number;
  drift: boolean;
}
export interface Catalog {
  approaches: Approach[];
  scenarios: string[];
  scenario_options: ScenarioOption[];
  replay_seed: number;
  split: string;
  calibrated: boolean;
  gate: Gate;
}
export interface ModelCard {
  system: SystemName;
  available: boolean;
  predicted_arrival_time: string | null;
  predicted_remaining_minutes: number | null;
  report_age_minutes: number | null;
  interval_half_width_minutes: number | null;
  calibration_approaches: number | null;
  review_reason: string | null;
  accepted: boolean;
  reasons: string | null;
  error_minutes?: number | null;
}
export interface Report {
  record_id: string;
  time: string;
  delivered_time: string;
  longitude: number;
  latitude: number;
  sog: number | null;
}
export interface InspectedReport extends Report {
  fault_applied: boolean;
  original_longitude: number;
  original_latitude: number;
  offset_meters: number;
}
export interface FeedCounts {
  received_total: number;
  received_in_window: number;
  unique_in_window: number;
  exact_duplicates_in_window: number;
  occupied_bins: number;
  history_minutes: number;
  bin_seconds: number;
}
export interface Diagnostics {
  latest_received_age_minutes: number | null;
  latest_usable_age_minutes: number | null;
  maximum_bin_spread_meters: number | null;
  velocity_disagreement_mps: number | null;
  maximum_gap_seconds: number | null;
  occupied_minute_bins: number | null;
  guard_received_count: number;
  guard_removed_count: number;
  reasons: string | null;
}
export interface Inspection {
  audience_only: boolean;
  affected_in_window: number;
  actual_affected_share: number | null;
  records: InspectedReport[];
  visible_limit: number;
}
export interface Snapshot {
  decision_id: string;
  decision_time: string;
  scenario: string;
  seed: number;
  cards: ModelCard[];
  received_history: Report[];
  feed_counts: FeedCounts;
  observable_diagnostics: Diagnostics;
  inspection: Inspection | null;
  human_assisted: boolean;
  verified_observation_time: string | null;
  reference_arrival: string | null;
  reference_bracket: [string, string] | null;
}
export interface TimelinePoint {
  decision_id: string;
  decision_time: string;
  system: SystemName;
  available: boolean;
  predicted_arrival_time: string | null;
  error_minutes?: number | null;
}
export interface Timeline {
  available: boolean;
  points: TimelinePoint[];
  seed: number;
  human_assisted?: boolean;
  source?: string;
}
export interface MetricRow {
  system: string;
  scenario: string;
  approach_weighted_mae_minutes: number;
  scheduled_approaches: number;
  vessels: number;
  seeds: number;
  output_coverage: number;
}
export interface Failure {
  approach_id: string;
  decision_id: string;
  scenario: string;
  error_minutes: number;
  decision_time: string;
  seed: number;
}
export interface Metrics {
  available: boolean;
  message?: string;
  summary: MetricRow[];
  volume_summary: MetricRow[];
  failures: Failure[];
  review_policy?: {tolerance_minutes: number; scheduled: number; accepted: number};
}
export interface ReplaySelection { decision: string; scenario: string; reveal: boolean; inspect: boolean; }
export interface PublicConfig { mapbox_public_token: string | null; }
export interface WindowWithMapbox extends Window { mapboxgl?: typeof import("mapbox-gl"); }

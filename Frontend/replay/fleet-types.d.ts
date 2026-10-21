import type { Gate, SystemName } from "./types.js";
export interface FleetCatalog {
  start: number;
  end: number;
  initial_time: number;
  approaches: number;
  vessels: number;
  seed: number;
  gate: Gate;
  windows: { id: string; start: number; arrival: number }[];
  note: string;
}
export interface FleetReport {
  time: number;
  delivered: number;
  longitude: number;
  latitude: number;
  speed: number | null;
  course: number | null;
  altered: boolean;
  original_longitude: number;
  original_latitude: number;
}
export interface FleetPrediction {
  available: boolean;
  eta: number | null;
  error: number | null;
}
export interface FleetShip {
  id: string;
  name: string;
  mmsi: string;
  type: string;
  arrival: number;
  split: string;
  arrived: boolean;
  fade: number;
  crossing_position: [number, number] | null;
  reports: FleetReport[];
  predictions: Record<SystemName, FleetPrediction>;
  age_minutes: number | null;
  diagnostics: {
    state: "clear" | "handled" | "review";
    reasons: string[];
    received: number;
    consolidated_or_removed: number;
    guard_enabled: boolean;
  };
}
export interface FleetFrame {
  time: number;
  ships: FleetShip[];
  condition: string;
  delay_minutes: number;
  affected_fraction: number;
  offset_nm: number;
  guard: boolean;
  seed: number;
}
export type Metric = "mae" | "rmse" | "mse";
export interface ScoreSample {
  time: number;
  cases: { id: string; errors: Record<SystemName, number> }[];
}

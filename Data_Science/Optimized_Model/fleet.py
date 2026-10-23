"""Fleet dashboard adapter over frozen models and causal historical reports."""

from functools import lru_cache
import math

import numpy as np
import pandas as pd

from attacks import (BaseAttack, MissingCourseAttack, MissingCourseConfig,
                     MissingSpeedAttack, MissingSpeedConfig, MissingVesselClassAttack,
                     MissingVesselClassConfig, PositionJumpAttack, PositionJumpConfig,
                     ReportingGapAttack, ReportingGapConfig, SensorDeteriorationAttack,
                     SensorDeteriorationConfig, SensorDriftAttack, SensorDriftConfig,
                     LocationDriftAttack, LocationDriftConfig)
from eta_baselines.observations import load_observations
from mitigation.location_drift_mitigation import PositionAnchor

from .configuration import OptimizedConfig
from .dataset import ReplayDataset
from .evaluation import PredictionSystem, predict_systems
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from .fleet_mitigations import FleetMitigations, FleetPolicy, position_anchors
from .replay import Scenario, create_stream
from .views import view_row

ARRIVAL_RETENTION_SECONDS = 600  # UI needs 480 seconds plus its terminal-frame lookup.
REPORT_FIELDS = {"longitude": "longitude", "latitude": "latitude", "sog": "speed",
                 "cog": "course", "vessel_type": "vessel_type"}
ATTACK_CONTROLS = (
    {"id": "reporting_gap", "label": "Reporting gap", "maximum": 60, "unit": "min",
     "description": "Simulated disruption: withhold reports for this many minutes, starting ten minutes after each approach begins. Reports resume after the fixed outage."},
    {"id": "missing_speed", "label": "Missing speed", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: remove speed from this percentage of reports; retain positions and timestamps."},
    {"id": "missing_course", "label": "Missing course", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: remove course from this percentage of reports; retain positions and timestamps."},
    {"id": "missing_vessel_class", "label": "Missing vessel class", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: remove vessel type from this percentage of reports. Unknown remains distinct from cargo and tanker."},
    {"id": "sensor_drift", "label": "Sensor drift", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: smoothly bias reported speed in the selected direction, up to 0.1 knots per minute and a 3-knot bias at full strength. Positions and timestamps are preserved."},
    {"id": "location_drift", "label": "Location drift", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: gradually bias coordinates in a seeded direction, up to 20 metres per minute and 1,852 metres at full strength. Correction needs independently verified positions and trusted speed/course; optional simulated fixes add those reference assumptions."},
    {"id": "sensor_deterioration", "label": "Sensor deterioration", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: add Gaussian speed and course noise, up to standard deviations of 2 knots and 10 degrees at full strength."},
    {"id": "position_jump", "label": "Position jump", "maximum": 100, "unit": "%",
     "description": "Simulated disruption: displace this percentage of position reports by a seeded Gaussian distance (2,000 m mean, 200 m standard deviation)."},
)


def poisoning_settings(payload: object) -> tuple[float, ...]:
    """Validate before inference; omission always means an unmodified stream."""
    if not isinstance(payload, dict):
        raise ValueError("poisoning must be a JSON object.")
    unknown = set(payload) - {control["id"] for control in ATTACK_CONTROLS}
    if unknown:
        raise ValueError(f"Unknown poisoning controls: {sorted(unknown)}.")
    values = []
    for control in ATTACK_CONTROLS:
        value = payload.get(control["id"], 0)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= control["maximum"]):
            raise ValueError(f"{control['id']} must be a finite number from 0 to {control['maximum']}.")
        values.append(float(value))
    return tuple(values)


def unix_seconds(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).value / 1e9


class FleetService:
    """Adapt existing feature/inference code without changing trained contracts.

    A/B use raw views; C adds conditional repairs to its trained input guard.
    Mixed position/navigation faults request verification. No simulation labels
    enter any predictor's feature table; extra verified fixes are explicit.
    """

    def __init__(self, config: OptimizedConfig, dataset: ReplayDataset,
                 systems: list[PredictionSystem], extractor: OptimizedFeatures) -> None:
        self.config, self.dataset, self.extractor = config, dataset, extractor
        self.systems = [system for system in systems if system.name in ("A", "B", "C")]
        if {system.name for system in self.systems} != {"A", "B", "C"}:
            raise ValueError("The fleet dashboard requires frozen models A, B and C.")
        self.split = "evaluation" if len(dataset.partition("evaluation")) else "exploratory"
        selected = dataset.partition(self.split).sort_values("decision_time")
        if selected.empty:
            raise ValueError("No evaluation or exploratory approaches are available for fleet replay.")
        self.approaches = selected.drop_duplicates("approach_id").set_index("approach_id")
        self.starts = {identity: dataset.histories[identity].time.min() for identity in self.approaches.index}
        self.start = min(self.starts.values()).floor("min")
        self.end = (self.approaches.arrival_time.max() + pd.Timedelta(seconds=ARRIVAL_RETENTION_SECONDS)).ceil("min")
        self.initial_time = selected.decision_time.iloc[0]
        self._crossings: dict[str, list[float]] | None = None
        self.mitigations = FleetMitigations(extractor)

    def catalog(self) -> dict[str, object]:
        return {"start": unix_seconds(self.start), "end": unix_seconds(self.end),
                "initial_time": unix_seconds(self.initial_time), "split": self.split,
                "windows": [{"id": identity, "start": unix_seconds(self.starts[identity]),
                             "arrival": unix_seconds(row.arrival_time)}
                            for identity, row in self.approaches.iterrows()],
                "attack_controls": list(ATTACK_CONTROLS),
                "mitigation_defaults": {"enabled": True, "trusted_fixes": False, "drift_direction": "under"},
                "models": {"A": "Poly", "B": "XGBoost", "C": "Antidote"},
                "arrival_reference": "Original analytical harbor crossing, not docking.",
                "seed": self.config.evaluation_seeds[0]}

    def _attacks(self, identity: str, settings: tuple[float, ...], drift_direction: str = "under") -> list[BaseAttack]:
        gap, speed, course, vessel_class, drift, location, noise, jump = settings
        seed = self.config.evaluation_seeds[0]
        attacks: list[BaseAttack] = []
        if gap:
            start = self.starts[identity] + pd.Timedelta(minutes=10)
            attacks.append(ReportingGapAttack(ReportingGapConfig(start, start + pd.Timedelta(minutes=gap))))
        if drift:
            attacks.append(SensorDriftAttack(SensorDriftConfig(
                drift_rate_knots_per_minute=(.1 if drift_direction == "over" else -.1) * drift / 100,
                maximum_bias_knots=3 * drift / 100, seed=seed,
                start_time=self.starts[identity])))
        if location:
            attacks.append(LocationDriftAttack(LocationDriftConfig(
                drift_rate_meters_per_minute=20 * location / 100,
                maximum_bias_meters=1852 * location / 100, seed=seed,
                start_time=self.starts[identity])))
        if noise:
            attacks.append(SensorDeteriorationAttack(SensorDeteriorationConfig(
                sog_sigma_knots=2 * noise / 100, cog_sigma_degrees=10 * noise / 100, seed=seed)))
        if jump:
            attacks.append(PositionJumpAttack(PositionJumpConfig(affected_fraction=jump / 100, seed=seed)))
        for fraction, attack_type, config_type in (
            (speed, MissingSpeedAttack, MissingSpeedConfig),
            (course, MissingCourseAttack, MissingCourseConfig),
            (vessel_class, MissingVesselClassAttack, MissingVesselClassConfig),
        ):
            if fraction:
                attacks.append(attack_type(config_type(affected_fraction=fraction / 100, seed=seed)))
        return attacks

    @lru_cache(maxsize=64)
    def _stream(self, identity: str, settings: tuple[float, ...], drift_direction: str = "under") -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]]]:
        nominal = create_stream(self.dataset.histories[identity], Scenario("nominal"),
                                self.config.evaluation_seeds[0], self.config.baseline.gate).reports
        changed = nominal
        names: dict[str, list[str]] = {}
        for attack in self._attacks(identity, settings, drift_direction):
            stream = attack.apply(changed)
            changed = stream.reports
            for record in stream.modification_log.loc[stream.modification_log.fault_applied].itertuples():
                names.setdefault(record.record_id, []).append(attack.name)
        return nominal, changed, names

    def _predict(self, reports: pd.DataFrame, decision: pd.Series, policy: FleetPolicy = FleetPolicy(), *,
                 anchors: tuple[PositionAnchor, ...] = ()) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        row = decision.to_dict()
        row.update(view_row(reports, decision, self.extractor))
        patch, mitigation = self.mitigations.apply(reports, decision.decision_time, policy, anchors=anchors)
        row.update(patch)
        row.update(scenario="fleet", condition="nominal", seed=self.config.evaluation_seeds[0])
        frame = pd.DataFrame([row])
        for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
            if column not in frame:
                frame[column] = np.nan
        for column in ("observation_time", "raw_observation_time"):
            if column not in frame:
                frame[column] = pd.NaT
        predictions = {}
        for result in predict_systems(frame, self.systems).itertuples():
            eta = unix_seconds(result.predicted_arrival_time) if result.available else None
            available = eta is not None and math.isfinite(eta)
            predictions[result.system] = {"available": available, "eta": eta if available else None,
                                          "error": float(result.error_minutes) if available else None}
        reasons = list(filter(None, row["reasons"].split("|")))
        for strategy in mitigation["strategies"]:
            if strategy["detected"] or strategy["requires_review"]:
                reasons.append(strategy["id"])
        diagnostics = {"state": "review" if reasons or not predictions["C"]["available"] else "ok",
                       "reasons": reasons, "guard_received_count": row["guard_received_count"],
                       "guard_removed_count": row["guard_removed_count"]}
        return predictions, diagnostics, mitigation

    def _crossing_positions(self) -> dict[str, list[float]]:
        """Recover the original reference bracket for terminal display only."""
        if self._crossings is None:
            source = self.config.later_csv if self.split == "evaluation" else self.config.baseline.input_csv
            observations, _ = load_observations(source)
            fixes = observations.set_index(["mmsi", "time"]).sort_index()
            self._crossings = {}
            for identity, row in self.approaches.iterrows():
                history = self.dataset.histories[identity]
                before = history.loc[history.time.eq(row.crossing_before)]
                key = (str(row.mmsi), row.crossing_after)
                if before.empty or key not in fixes.index:
                    continue
                after = fixes.loc[key]
                first = before.iloc[-1]
                fraction = (row.arrival_time - row.crossing_before) / (row.crossing_after - row.crossing_before)
                latitude = first.latitude + fraction * (after.latitude - first.latitude)
                self._crossings[identity] = [self.config.baseline.gate.longitude, float(latitude)]
        return self._crossings

    def frame(self, time: float, poisoning: object, *, mitigate: bool = True,
              trusted_fixes: bool = False, drift_direction: str = "under") -> dict[str, object]:
        settings = poisoning_settings(poisoning)
        if type(mitigate) is not bool or type(trusted_fixes) is not bool:
            raise ValueError("mitigate and trusted_fixes must be boolean.")
        if drift_direction not in ("under", "over"):
            raise ValueError("drift_direction must be under or over.")
        selected = dict(zip((control["id"] for control in ATTACK_CONTROLS), settings))
        navigation_faults = any(selected[name] for name in ("missing_speed", "missing_course", "sensor_drift", "sensor_deterioration"))
        if trusted_fixes and (not mitigate or not selected["location_drift"] or navigation_faults or selected["position_jump"]):
            raise ValueError("Simulated verified fixes require mitigations and location drift, with no navigation or position-jump attacks.")
        policy = FleetPolicy(mitigate, bool(selected["location_drift"] or selected["position_jump"]),
                             bool(selected["sensor_deterioration"]), bool(selected["sensor_drift"]), trusted_fixes)
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time):
            raise ValueError("time must be finite UTC Unix seconds.")
        if not unix_seconds(self.start) <= time <= unix_seconds(self.end):
            raise ValueError("time is outside the fleet catalog bounds.")
        clock = pd.Timestamp(time, unit="s")
        ships = []
        for identity, template in self.approaches.iterrows():
            if clock < self.starts[identity] or clock >= template.arrival_time + pd.Timedelta(seconds=ARRIVAL_RETENTION_SECONDS):
                continue
            nominal, changed, names = self._stream(identity, settings, drift_direction)
            normal = nominal.loc[nominal.time.le(clock) & nominal.delivered_time.le(clock)]
            received = changed.loc[changed.time.le(clock) & changed.delivered_time.le(clock)]
            decision = template.copy()
            decision["approach_id"], decision["decision_time"] = identity, clock
            decision["decision_id"] = f"{identity}:{clock.isoformat()}"
            clean_predictions, clean_diagnostics, clean_mitigation = self._predict(normal, decision, FleetPolicy(enabled=mitigate))
            active = any(settings)
            anchors = position_anchors(normal) if trusted_fixes else ()
            predictions, diagnostics, mitigation = self._predict(received, decision, policy, anchors=anchors) if active else (clean_predictions, clean_diagnostics, clean_mitigation)
            # Audience-only annotations are constructed strictly after inference.
            original = normal.set_index("record_id")
            records = []
            modified = 0
            for report in received.itertuples():
                baseline = original.loc[report.record_id]
                values = {field: getattr(report, source) for source, field in REPORT_FIELDS.items()}
                fields = [field for source, field in REPORT_FIELDS.items()
                          if not _same_value(getattr(report, source), baseline[source])]
                modified += bool(fields)
                records.append({"record_id": report.record_id, "time": unix_seconds(report.time),
                                "delivered": unix_seconds(report.delivered_time), **values,
                                "poisoned_fields": fields, "attack_names": names.get(report.record_id, []),
                                "estimated_values": mitigation["estimated_values"].get(report.record_id, {}),
                                "original_values": {field: baseline[source] for source, field in REPORT_FIELDS.items() if field in fields},
                                "original_longitude": baseline.longitude if "longitude" in fields else None,
                                "original_latitude": baseline.latitude if "latitude" in fields else None})
            withheld = normal.loc[~normal.record_id.isin(received.record_id)]
            audit = [{"record_id": report.record_id, "time": unix_seconds(report.time),
                      "delivered": unix_seconds(report.delivered_time), "withheld": True,
                      **dict.fromkeys(REPORT_FIELDS.values()), "poisoned_fields": ["time", *REPORT_FIELDS.values()],
                      "attack_names": names.get(report.record_id, [])} for report in withheld.itertuples()]
            history_minutes = self.config.baseline.features.history_minutes
            latest = normal.time.max()
            recent = normal.loc[normal.time.ge(latest - pd.Timedelta(minutes=history_minutes))]
            attacked_recent = received.loc[received.time.ge(latest - pd.Timedelta(minutes=history_minutes))]
            arrived = clock >= template.arrival_time
            crossings = self._crossing_positions() if arrived else {}
            ships.append({"id": identity, "mmsi": str(template.mmsi), "name": f"MMSI {template.mmsi}",
                          "arrival": unix_seconds(template.arrival_time), "arrived": arrived,
                          "crossing_position": crossings.get(identity), "reports": records, "audit_events": audit,
                          "predictions": predictions, "nominal_predictions": clean_predictions,
                          "poisoned_predictions": predictions if active else None, "prediction_time": time,
                          "age_minutes": (clock - received.time.max()).total_seconds() / 60 if len(received) else None,
                          "diagnostics": diagnostics,
                          "mitigation": mitigation,
                          "comparison_inputs": {"normal_reports": len(normal), "poisoned_reports": len(received),
                              "withheld_reports": len(withheld), "modified_reports": modified,
                              "history_minutes": history_minutes, "normal_recent_reports": len(recent),
                              "poisoned_recent_reports": len(attacked_recent),
                              "recent_inputs_differ": not recent[list(REPORT_FIELDS)].reset_index(drop=True).equals(
                                  attacked_recent[list(REPORT_FIELDS)].reset_index(drop=True))}})
        return {"time": time, "ships": ships,
                "mitigations": {"enabled": mitigate, "trusted_fixes": trusted_fixes, "drift_direction": drift_direction},
                "poisoning": {control["id"]: value for control, value in zip(ATTACK_CONTROLS, settings)},
                "poisoning_active": any(settings), "source": "Historical AIS replay",
                "scenario_label": "Simulated disruption" if any(settings) else "Original records"}

def _same_value(first: object, second: object) -> bool:
    return bool((pd.isna(first) and pd.isna(second)) or first == second)

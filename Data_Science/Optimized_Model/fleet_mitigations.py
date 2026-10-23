"""Causal adapters for the fleet demo's existing mitigation strategies.

Experiment settings select permitted reference assumptions, never detection.
Only observed reports reach a strategy. Extra position anchors are an explicit
simulation supplied separately by the caller, never inferred from an audit log.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mitigation import (GapMitigation, LocationDriftMitigation, MitigationResult, MissingCourseMitigation,
                        MissingSpeedMitigation, MissingVesselClassMitigation,
                        PositionAnchor, PositionJumpMitigation, SensorDriftMitigation,
                        SensorNoiseMitigation)
from mitigation.missing_vessel_class_mitigation.optimized_model import vessel_class_snapshot
from mitigation.navigation_features import repaired_navigation_features

from .features import QUALITY_COLUMNS, RICH_COLUMNS, OptimizedFeatures


@dataclass(frozen=True)
class FleetPolicy:
    enabled: bool = True
    position_faults: bool = False
    noise: bool = False
    speed_drift: bool = False
    trusted_fixes: bool = False


def position_anchors(nominal: pd.DataFrame) -> tuple[PositionAnchor, ...]:
    """SIMULATED extra fixes: first original observation in each five-minute bin.

    This is an oracle-reference experiment, not a deployed independent feed.
    Callers must opt in; every anchor retains its real availability time.
    """
    if nominal.empty:
        return ()
    bins = ((nominal.time - nominal.time.min()).dt.total_seconds() // 300).astype(int)
    selected = nominal.loc[~bins.duplicated()]
    return tuple(PositionAnchor(mmsi=str(row.mmsi), time=row.time,
                 received_time=row.delivered_time, longitude=float(row.longitude),
                 latitude=float(row.latitude), source="SIMULATED independent fix from original AIS")
                 for row in selected.itertuples())


def available_anchor(anchors: tuple[PositionAnchor, ...], measured: pd.Timestamp,
                     clock: pd.Timestamp) -> PositionAnchor | None:
    due = [anchor for anchor in anchors if anchor.time <= measured and anchor.received_time <= clock]
    return max(due, key=lambda anchor: anchor.time) if due else None


def changed_fields(original: pd.DataFrame, derived: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Derived values for the audience, separate from actual received readings."""
    values = {}
    for before, after in zip(original.itertuples(), derived.itertuples()):
        fields = {}
        for column, field in (("sog", "speed"), ("cog", "course"),
                              ("longitude", "longitude"), ("latitude", "latitude")):
            left, right = getattr(before, column), getattr(after, column)
            if np.isfinite(right) and not np.isclose(left, right, equal_nan=True, rtol=0, atol=1e-10):
                fields[field] = float(right)
        if fields:
            values[before.record_id] = fields
    return values


class FleetMitigations:
    def __init__(self, extractor: OptimizedFeatures) -> None:
        self.extractor = extractor
        gate = extractor.baseline.gate
        self.gap = GapMitigation(gate)
        self.position = PositionJumpMitigation()
        self.speed = MissingSpeedMitigation(gate)
        self.course = MissingCourseMitigation(gate)
        self.vessel_class = MissingVesselClassMitigation()
        self.noise = SensorNoiseMitigation(gate)
        self.drift = SensorDriftMitigation(gate)
        self.location = LocationDriftMitigation(gate)

    def apply(self, reports: pd.DataFrame, clock: pd.Timestamp, policy: FleetPolicy, *,
              anchors: tuple[PositionAnchor, ...] = ()) -> tuple[dict[str, object], dict[str, object]]:
        metadata = {"enabled": policy.enabled, "strategies": [], "features_changed": False,
                    "estimated_values": {}, "reference_simulated": policy.trusted_fixes,
                    "eta_policy_calibrated": False, "combination_policy": "conditional_references"}
        if not policy.enabled:
            return {}, metadata
        strategies = metadata["strategies"]

        def record(key: str, label: str, result: MitigationResult, count: int = 0, *,
                   message: str | None = None, blocked: bool = False) -> None:
            data = result.to_dict()
            detected = bool(data.get("anomaly_detected", False))
            review = blocked or bool(data.get("requires_review", False)) or (
                key in ("missing_speed", "missing_course", "missing_vessel_class") and not result.can_predict)
            status = "requires_review" if blocked else "estimated" if count else data.get("status", "monitoring")
            strategies.append({"id": key, "label": label, "status": status,
                "detected": detected, "applied": count > 0, "reconstructed_reports": count,
                "requires_review": review or (detected and not count),
                "message": message or (f"{count} readings estimated" if count else
                    "Measurements disagree; review needed" if detected else
                    "Insufficient reliable evidence; review needed" if review else "Monitoring received reports"),
                "diagnostics": data})

        gap = self.gap.apply(reports, clock)
        position = self.position.apply(reports, clock)
        drift = self.drift.apply(reports, clock)
        anchor = available_anchor(anchors, reports.time.max(), clock) if len(reports) else None
        location = self.location.apply(reports, clock, anchor=anchor,
                                       navigation_trusted=policy.trusted_fixes)
        record("reporting_gap", "Reporting gap", gap,
               message="Reports stopped; waiting for new reports" if gap.anomaly_detected else None)
        record("position_jump", "Navigation consistency", position,
               message="Navigation measurements disagree; verify position and motion" if position.anomaly_detected else None)
        original, guard = self.extractor.snapshot(reports, clock, guarded=True)
        patch = {}
        effective = guard.reports.copy(deep=True).reset_index(drop=True)
        blocked = policy.position_faults
        reference_message = "Position and navigation faults selected; independent verification needed"

        # Missing navigation fields have disjoint targets. Both fits use the same
        # unmodified positions, so neither reconstruction becomes another's evidence.
        for key, label, strategy, column in (
            ("missing_speed", "Missing speed", self.speed, "sog"),
            ("missing_course", "Missing course", self.course, "cog"),
        ):
            result = strategy.apply(reports, clock)
            count = 0
            if not blocked and not effective.empty:
                warmup = reports.loc[reports.time.ge(reports.time.max() - pd.Timedelta(
                    minutes=self.extractor.baseline.features.history_minutes + strategy.config.history_minutes))]
                repair = strategy.repair_reports(warmup, clock)
                estimates = repair.reports.set_index("record_id")[column]
                current = effective[column].to_numpy(dtype=float)
                invalid = ~np.isfinite(current) | (current < 0) | (current > 102.2 if column == "sog" else current >= 360)
                replacement = effective.record_id.map(estimates).to_numpy(dtype=float)
                selected = invalid & np.isfinite(replacement)
                effective.loc[selected, column] = replacement[selected]
                count = int(selected.sum())
            unavailable = result.to_dict().get("status") not in ("observed", "reported")
            record(key, label, result, count, blocked=blocked and unavailable,
                   message=reference_message if blocked and unavailable else None)

        conflict = policy.noise and policy.speed_drift
        # Detection remains on received reports. Corrections never use earlier
        # derived sensor readings as supporting evidence.
        for key, label, strategy, selected, columns in (
            ("sensor_noise", "Sensor noise", self.noise, policy.noise, ("sog", "cog")),
            ("sensor_drift", "Speed drift", self.drift, policy.speed_drift, ("sog",)),
        ):
            result = strategy.apply(reports, clock) if key == "sensor_noise" else drift
            count = 0
            if selected and not blocked and not conflict and not effective.empty and result.can_predict:
                for index, row in effective.iterrows():
                    delivery = row.get("delivered_time", row.time)
                    history = reports.loc[reports.time.le(row.time) & reports.delivered_time.le(delivery)]
                    reading = strategy.apply(history, delivery)
                    if not reading.can_predict:
                        continue
                    changed = False
                    for column in columns:
                        field = "speed" if column == "sog" else "course"
                        if getattr(reading, f"{field}_source") == "estimated":
                            value = getattr(reading, "speed_knots" if column == "sog" else "course_degrees")
                            effective.at[index, column] = value
                            changed = True
                    count += changed
            if selected or key == "sensor_drift":
                paused = selected and (blocked or conflict)
                message = (reference_message if blocked else "Noise and drift selected together; sensor correction paused") if paused else None
                record(key, label, result, count, blocked=paused, message=message)

        # C's original quality evidence, clock, support and guard diagnostics stay
        # intact. Only motion/base features are derived from private estimates.
        if not original.empty and not effective.empty:
            columns = tuple(column for column in RICH_COLUMNS if column not in QUALITY_COLUMNS)
            derived = repaired_navigation_features(original, effective, self.extractor, columns)
            estimates = changed_fields(guard.reports.reset_index(drop=True), effective)
            if estimates:
                patch.update({column: derived.iloc[0][column] for column in columns})
                metadata["estimated_values"].update(estimates)

        class_view = vessel_class_snapshot(reports, clock, self.extractor, self.vessel_class)
        class_changed = not class_view.original_features.equals(class_view.mitigated_features)
        if class_changed:
            for column in ("is_cargo", "is_tanker", "vessel_class_unknown"):
                patch[column] = class_view.mitigated_features.iloc[0][column]
        record("missing_vessel_class", "Vessel class", class_view.mitigation,
               int(class_changed and class_view.mitigation.can_predict),
               message=f"Broad class recovered as {class_view.mitigation.recovered_class} from received metadata" if class_changed and class_view.mitigation.can_predict else None)

        count = 0
        if policy.trusted_fixes and location.can_predict and location.correction_applied and not effective.empty:
            corrected = guard.reports.copy(deep=True).reset_index(drop=True)
            for index, row in corrected.iterrows():
                delivery = row.get("delivered_time", row.time)
                history = reports.loc[reports.time.le(row.time) & reports.delivered_time.le(delivery)]
                fix = available_anchor(anchors, row.time, delivery)
                reading = self.location.apply(history, delivery, anchor=fix, navigation_trusted=True)
                if reading.correction_applied:
                    corrected.loc[index, ["longitude", "latitude"]] = [reading.longitude, reading.latitude]
            estimates = changed_fields(guard.reports.reset_index(drop=True), corrected)
            features, _ = self.extractor.snapshot(corrected, clock, guarded=True)
            if estimates and not features.empty and features.iloc[0].observation_time == original.iloc[0].observation_time:
                for column in RICH_COLUMNS:
                    if column not in QUALITY_COLUMNS and column not in ("is_cargo", "is_tanker", "vessel_class_unknown"):
                        patch[column] = features.iloc[0][column]
                metadata["estimated_values"].update(estimates)
                count = len(estimates)
        record("location_drift", "Location drift", location, count,
               message=(f"{count} positions estimated using SIMULATED verified fixes" if count else
                        "Position/navigation disagreement; verified position and trusted motion needed" if location.anomaly_detected else None))
        metadata["features_changed"] = bool(patch)
        metadata["requires_review"] = any(row["requires_review"] for row in strategies)
        return patch, metadata

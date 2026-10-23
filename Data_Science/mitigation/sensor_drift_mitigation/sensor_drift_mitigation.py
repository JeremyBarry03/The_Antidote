"""Detect sustained speed bias against checked position history."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, history_velocity, local_positions
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult
from .._drift_helpers import angle_difference, ewma_fraction, finite, prepare, validate_config


class SensorDriftStatus(str, Enum):
    NO_REPORTS = "no_reports"
    WARMING_UP = "warming_up"
    NORMAL = "normal"
    RECONSTRUCTED = "reconstructed"
    REVIEW = "requires_review"


@dataclass(frozen=True)
class SensorDriftMitigationConfig:
    """Provisional research thresholds, not calibrated detection guarantees."""

    position_window_minutes: float = 5.
    detection_window_minutes: float = 15.
    minimum_reports: int = 3
    minimum_span_seconds: float = 60.
    maximum_gap_seconds: float = 180.
    maximum_report_age_minutes: float = 5.
    maximum_speed_knots: float = 60.
    maximum_fit_residual_meters: float = 50.
    maximum_segment_speed_difference_knots: float = 2.
    maximum_reference_acceleration_knots_per_minute: float = .2
    maximum_track_turn_degrees: float = 30.
    ewma_time_constant_minutes: float = 2.
    minimum_disagreement_knots: float = .2
    drift_threshold_knots: float = .5
    minimum_persistent_reports: int = 3
    minimum_persistence_minutes: float = 2.

    def __post_init__(self) -> None:
        validate_config(self, ("minimum_reports", "minimum_persistent_reports"))
        if self.minimum_span_seconds > self.position_window_minutes * 60:
            raise ValueError("The position window must cover minimum_span_seconds.")
        if self.minimum_persistence_minutes > self.detection_window_minutes:
            raise ValueError("The detection window must cover minimum_persistence_minutes.")
        if self.minimum_disagreement_knots > self.drift_threshold_knots or self.maximum_track_turn_degrees > 180:
            raise ValueError("Invalid drift or turning thresholds.")


@dataclass(frozen=True)
class SensorDriftMitigationResult(MitigationResult):
    status: SensorDriftStatus
    reported_speed_knots: float | None = None
    estimated_speed_knots: float | None = None
    speed_knots: float | None = None
    speed_source: str = "unavailable"
    disagreement_knots: float | None = None
    ewma_disagreement_knots: float | None = None
    persistent_report_count: int = 0
    persistent_minutes: float = 0.
    position_supported: bool = False
    fit_residual_meters: float | None = None
    anomaly_since: pd.Timestamp | None = None

    @property
    def anomaly_detected(self) -> bool:
        return self.status == SensorDriftStatus.RECONSTRUCTED

    @property
    def can_predict(self) -> bool:
        """Input support only; never calibrated forecast acceptance."""
        return self.status in (SensorDriftStatus.NORMAL, SensorDriftStatus.RECONSTRUCTED)

    @property
    def requires_review(self) -> bool:
        return not self.can_predict

    def to_dict(self) -> dict[str, object]:
        return {**super().to_dict(), "anomaly_detected": self.anomaly_detected, "requires_review": self.requires_review}


@dataclass(frozen=True)
class SensorDriftMitigation(BaseMitigation):
    """One vessel, received history and a clock; no attack settings or truth.

    Positions are a conditional reference for speed-only drift. This strategy
    cannot diagnose simultaneous coherent corruption of position and speed.
    """

    gate: GateConfig
    config: SensorDriftMitigationConfig = SensorDriftMitigationConfig()
    name: ClassVar[str] = "SensorDriftMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate), "scope": "speed_drift"}

    def _reference(self, recent: pd.DataFrame) -> tuple[float | None, float | None, str | None]:
        config = self.config
        if recent.time.duplicated().any():
            return None, None, "conflicting_same_time_reports"
        if len(recent) < config.minimum_reports:
            return None, None, "insufficient_position_history"
        if (recent.time.iloc[-1] - recent.time.iloc[0]).total_seconds() < config.minimum_span_seconds:
            return None, None, "short_position_history"
        valid = (np.isfinite(recent.longitude) & np.isfinite(recent.latitude)
                 & recent.longitude.between(-180, 180) & recent.latitude.between(-90, 90))
        if not valid.all():
            return None, None, "invalid_position"
        gaps = recent.time.diff().dt.total_seconds().dropna().to_numpy()
        if gaps.max() > config.maximum_gap_seconds:
            return None, None, "position_history_gap"
        segments = np.diff(local_positions(recent, self.gate), axis=0) / gaps[:, None]
        speeds = np.linalg.norm(segments, axis=1) / KNOTS_TO_METERS_PER_SECOND
        if speeds.max() > config.maximum_speed_knots:
            return None, None, "implausible_position_motion"
        east, north, residual = history_velocity(recent, self.gate)
        speed = float(np.hypot(east, north) / KNOTS_TO_METERS_PER_SECOND)
        if not np.isfinite([speed, residual]).all() or residual > config.maximum_fit_residual_meters:
            return None, finite(residual), "inconsistent_position_track"
        moving = speeds >= 1.
        course = np.rad2deg(np.arctan2(east, north)) % 360
        segment_courses = np.rad2deg(np.arctan2(segments[:, 0], segments[:, 1])) % 360
        elapsed = (recent.time - recent.time.iloc[0]).dt.total_seconds().to_numpy()
        midpoints_minutes = (elapsed[1:] + elapsed[:-1]) / 120
        acceleration = np.abs(np.diff(speeds) / np.diff(midpoints_minutes))
        if (np.max(np.abs(speeds - speed)) > config.maximum_segment_speed_difference_knots
                or (len(acceleration) and acceleration.max() > config.maximum_reference_acceleration_knots_per_minute)
                or (speed >= 1 and moving.any() and angle_difference(segment_courses[moving], course).max() > config.maximum_track_turn_degrees)):
            return None, residual, "maneuvering_position_track"
        return speed, residual, None

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> SensorDriftMitigationResult:
        received, clock = prepare(reports, decision_time, ("longitude", "latitude", "sog"))
        if received.empty:
            return SensorDriftMitigationResult(SensorDriftStatus.NO_REPORTS, decision_time=clock)
        config = self.config
        last = received.iloc[-1]
        latest = self._latest_received_time(received, clock, latest_received_time)
        valid_speed = finite(last.sog) is not None and 0 <= last.sog <= 102.2
        reported = float(last.sog) if valid_speed else None
        common = dict(decision_time=clock, mmsi=str(last.mmsi), observation_time=last.time,
            latest_received_time=latest, report_age_minutes=(clock - last.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - latest).total_seconds() / 60,
            reported_speed_knots=reported, speed_knots=reported,
            speed_source="reported" if valid_speed else "unavailable")
        if latest > last.time or common["report_age_minutes"] > config.maximum_report_age_minutes:
            return SensorDriftMitigationResult(SensorDriftStatus.REVIEW, **common, reasons=("stale_or_unusable_position_history",))
        start = last.time - pd.Timedelta(minutes=config.detection_window_minutes)
        history = received.loc[received.time >= start - pd.Timedelta(minutes=config.position_window_minutes)]
        ewma, count, sign = 0., 0, 0
        streak_start, detected_at = None, None
        valid_residuals = 0
        speed, residual, reason, disagreement = None, None, "insufficient_position_history", None
        latest_evidence_delivery = history.time.iloc[0]
        for index, row in enumerate(history.itertuples()):
            latest_evidence_delivery = max(latest_evidence_delivery, getattr(row, "delivered_time", row.time))
            if row.time < start:
                continue
            recent = history.loc[history.time.between(row.time - pd.Timedelta(minutes=config.position_window_minutes), row.time)]
            speed, residual, reason = self._reference(recent)
            if reason is None and (finite(row.sog) is None or not 0 <= row.sog <= 102.2):
                reason = "unavailable_speed_not_drift_repaired"
            if reason is not None:
                ewma, count, sign, valid_residuals, streak_start, detected_at = 0., 0, 0, 0, None, None
                continue
            disagreement = float(row.sog - speed)
            minutes = (row.time - history.time.iloc[index - 1]).total_seconds() / 60
            ewma += ewma_fraction(minutes, config.ewma_time_constant_minutes) * (disagreement - ewma)
            valid_residuals += 1
            direction = int(np.sign(disagreement)) if abs(disagreement) > config.minimum_disagreement_knots else 0
            if direction and direction == sign:
                count += 1
            else:
                count, streak_start, detected_at = (1 if direction else 0), row.time, None
            sign = direction
            duration = (row.time - streak_start).total_seconds() / 60
            detected = (count >= config.minimum_persistent_reports and duration >= config.minimum_persistence_minutes
                        and abs(ewma) > config.drift_threshold_knots and np.sign(ewma) == direction)
            if detected and detected_at is None:
                detected_at = latest_evidence_delivery
        if reason is not None:
            status = SensorDriftStatus.WARMING_UP if reason in ("insufficient_position_history", "short_position_history") else SensorDriftStatus.REVIEW
            return SensorDriftMitigationResult(status, **common, fit_residual_meters=finite(residual), reasons=(reason,))
        duration = (last.time - streak_start).total_seconds() / 60
        detected = (count >= config.minimum_persistent_reports and duration >= config.minimum_persistence_minutes
                    and abs(ewma) > config.drift_threshold_knots and np.sign(ewma) == sign)
        status = (SensorDriftStatus.RECONSTRUCTED if detected else SensorDriftStatus.NORMAL
                  if valid_residuals >= config.minimum_persistent_reports else SensorDriftStatus.WARMING_UP)
        if detected:
            common.update(speed_knots=speed, speed_source="estimated")
        return SensorDriftMitigationResult(status, **common, estimated_speed_knots=speed,
            disagreement_knots=disagreement, ewma_disagreement_knots=float(ewma), position_supported=True,
            persistent_report_count=count, persistent_minutes=duration, fit_residual_meters=residual,
            anomaly_since=detected_at if detected else None,
            reasons=("persistent_speed_position_disagreement",) if detected else ())

    def reconstruct_reports(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str
                            ) -> tuple[pd.DataFrame, SensorDriftMitigationResult]:
        received, _ = self._prepare_reports(reports, decision_time)
        result = self.apply(received, decision_time)
        derived = received.copy(deep=True).reset_index(drop=True)
        derived["sog"] = self._numeric_field(derived, "sog")
        delivered = received.get("delivered_time", received.time)
        for index, (_, row) in enumerate(received.iterrows()):
            at = row.get("delivered_time", row.time)
            history = received.loc[received.time.le(row.time) & delivered.le(at)]
            reading = self.apply(history, at)
            if reading.can_predict and reading.speed_source == "estimated":
                derived.at[index, "sog"] = reading.speed_knots
        return derived, result

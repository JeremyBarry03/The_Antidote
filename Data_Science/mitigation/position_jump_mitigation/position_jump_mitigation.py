"""Warn about received navigation inconsistencies; never repair or filter AIS."""

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult


@dataclass(frozen=True)
class PositionJumpMitigationConfig:
    """Effective innovation scales, not calibrated sensor specifications."""

    position_sigma_meters: float = 25.
    velocity_sigma_mps: float = .5
    # March vessel-balanced 99.5th percentile; see position_jump_anomaly/calibrate.py.
    distance_threshold_squared: float = 1.948477151551384
    maximum_pair_gap_seconds: float = 120.
    warning_window_minutes: float = 5.

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")


class PositionStatus(str, Enum):
    NO_REPORTS = "no_reports"
    UNASSESSED = "unassessed"
    NORMAL = "normal"
    INCONSISTENT = "inconsistent_navigation"


@dataclass(frozen=True)
class PositionJumpResult(MitigationResult):
    status: PositionStatus
    assessed_pairs: int = 0
    unassessed_reports: int = 0
    flagged_reports: int = 0
    maximum_residual_meters: float | None = None
    maximum_score: float | None = None
    anomaly_since: pd.Timestamp | None = None
    evidence: tuple[dict[str, object], ...] = ()

    @property
    def anomaly_detected(self) -> bool:
        return self.status == PositionStatus.INCONSISTENT

    @property
    def can_predict(self) -> bool:
        """Reliability recommendation only; this detector never controls a model."""
        return self.status == PositionStatus.NORMAL

    def to_dict(self) -> dict[str, object]:
        return {**super().to_dict(), "anomaly_detected": self.anomaly_detected, "forecast_modified": False}


def position_motion_pairs(reports: pd.DataFrame, config: PositionJumpMitigationConfig) -> pd.DataFrame:
    """Compare adjacent received fixes with trapezoidal SOG/COG displacement.

    This function reads only observable navigation. It fits no track, selects no
    trusted anchor and returns diagnostic rows, never replacement observations.
    Supply one vessel's causally prepared history, as enforced by the subclass.
    """
    frame = reports.copy(deep=True)
    for column in ("latitude", "longitude", "sog", "cog"):
        frame[column] = BaseMitigation._numeric_field(frame, column)
    if "delivered_time" not in frame:
        frame["delivered_time"] = frame.time
    frame = frame.sort_values(["time", "delivered_time", "latitude", "longitude", "sog", "cog"], kind="stable")
    conflicts = frame.groupby("time")[["latitude", "longitude"]].transform("nunique").gt(1).any(axis=1)
    frame["conflict"] = conflicts
    frame = frame.drop_duplicates("time", keep="first").reset_index(drop=True)
    if "record_id" not in frame:
        frame["record_id"] = [f"{row.mmsi}:{row.time.isoformat()}" for row in frame.itertuples()]
    latitude, longitude = np.deg2rad(frame.latitude.to_numpy()), np.deg2rad(frame.longitude.to_numpy())
    valid_position = (np.isfinite(latitude) & np.isfinite(longitude)
        & frame.latitude.between(-90, 90).to_numpy() & frame.longitude.between(-180, 180).to_numpy())
    speed, course = frame.sog.to_numpy(), frame.cog.to_numpy()
    valid_velocity = (np.isfinite(speed) & (speed >= 0) & (speed <= 102.2)
        & ((np.isfinite(course) & (course >= 0) & (course < 360)) | (speed == 0)))
    radians = np.deg2rad(np.where(speed == 0, 0., course))
    velocity = speed[:, None] * KNOTS_TO_METERS_PER_SECOND * np.column_stack([np.sin(radians), np.cos(radians)])
    dt = frame.time.diff().dt.total_seconds().to_numpy()
    eligible = valid_position & valid_velocity & ~frame.conflict.to_numpy()
    previous_eligible = np.r_[False, eligible[:-1]] if len(frame) else np.zeros(0, dtype=bool)
    assessed = eligible & previous_eligible & (dt > 0) & (dt <= config.maximum_pair_gap_seconds)
    residual = np.full(len(frame), np.nan)
    score = np.full(len(frame), np.nan)
    if len(frame) > 1:
        delta_lon = (np.diff(longitude) + np.pi) % (2 * np.pi) - np.pi
        displacement = 6_371_000. * np.column_stack([
            delta_lon * np.cos(.5 * (latitude[1:] + latitude[:-1])), np.diff(latitude)])
        expected = .5 * (velocity[1:] + velocity[:-1]) * dt[1:, None]
        residual[1:] = np.linalg.norm(displacement - expected, axis=1)
        # Independent endpoint position/velocity errors under a local motion model.
        variance = 2 * config.position_sigma_meters**2 + .5 * config.velocity_sigma_mps**2 * dt**2
        score[assessed] = residual[assessed]**2 / variance[assessed]
    reasons = np.where(~valid_position, "invalid_or_missing_position",
        np.where(frame.conflict, "conflicting_same_time_positions",
        np.where(assessed & (score > config.distance_threshold_squared), "position_motion_disagreement", "")))
    result = frame[["record_id", "mmsi", "time", "delivered_time"]].copy()
    result["previous_time"] = frame.time.shift()
    result["elapsed_seconds"], result["assessed"] = dt, assessed
    result["residual_meters"] = np.where(assessed, residual, np.nan)
    result["score"], result["reason"] = score, reasons
    result["flagged"] = reasons != ""
    return result


@dataclass(frozen=True)
class PositionJumpMitigation(BaseMitigation):
    """Anomaly-only mitigation; the historical class/API name remains compatible."""

    config: PositionJumpMitigationConfig = PositionJumpMitigationConfig()
    name: ClassVar[str] = "PositionJumpMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "mode": "anomaly_only", "forecast_modified": False}

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> PositionJumpResult:
        received, clock = self._prepare_reports(reports, decision_time)
        pairs = position_motion_pairs(received, self.config)
        if latest_received_time is not None:
            if received.empty or self._latest_received_time(received, clock, latest_received_time) != received.time.max():
                raise ValueError("Detection requires the complete received history and latest report time.")
        recent = pairs.loc[pairs.time.ge(clock - pd.Timedelta(minutes=self.config.warning_window_minutes))]
        flagged = recent.loc[recent.flagged]
        status = (PositionStatus.NO_REPORTS if received.empty else PositionStatus.INCONSISTENT if len(flagged)
                  else PositionStatus.NORMAL if recent.assessed.any() else PositionStatus.UNASSESSED)
        evidence = []
        for row in flagged.itertuples():
            evidence.append({"record_id": str(row.record_id), "time": row.time.isoformat(),
                "previous_time": row.previous_time.isoformat() if pd.notna(row.previous_time) else None,
                "delivered_time": row.delivered_time.isoformat(), "reason": row.reason,
                "elapsed_seconds": float(row.elapsed_seconds) if np.isfinite(row.elapsed_seconds) else None,
                "residual_meters": float(row.residual_meters) if np.isfinite(row.residual_meters) else None,
                "score": float(row.score) if np.isfinite(row.score) else None})
        latest = received.time.max() if len(received) else None
        return PositionJumpResult(status, decision_time=clock,
            mmsi=str(received.mmsi.iloc[0]) if len(received) else None,
            observation_time=latest, latest_received_time=latest,
            report_age_minutes=(clock - latest).total_seconds() / 60 if latest is not None else None,
            latest_received_age_minutes=(clock - latest).total_seconds() / 60 if latest is not None else None,
            assessed_pairs=int(recent.assessed.sum()), unassessed_reports=int((~recent.assessed).sum()),
            flagged_reports=len(flagged), evidence=tuple(evidence),
            maximum_residual_meters=float(recent.residual_meters.max()) if recent.assessed.any() else None,
            maximum_score=float(recent.score.max()) if recent.assessed.any() else None,
            anomaly_since=flagged.time.min() if len(flagged) else None,
            reasons=tuple(sorted(flagged.reason.unique())))

"""Reconstruct unavailable SOG from supported motion at that observation's time."""

from dataclasses import asdict, dataclass, replace
from enum import Enum
import math
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, history_velocity, local_positions
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult

MAXIMUM_AIS_SPEED_KNOTS = 102.2


class SpeedStatus(str, Enum):
    NO_REPORTS = "no_reports"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MissingSpeedConfig:
    """Fixed research defaults; not tuned on the evaluation outcomes."""

    history_minutes: float = 5.0
    minimum_reports: int = 3
    minimum_span_seconds: float = 60.0
    maximum_gap_seconds: float = 120.0
    maximum_speed_knots: float = 60.0
    maximum_fit_residual_meters: float = 50.0
    maximum_velocity_deviation_knots: float = 2.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "minimum_reports":
                if type(value) is not int or value < 3:
                    raise ValueError("minimum_reports must be an integer of at least three.")
            elif (isinstance(value, bool) or not isinstance(value, (int, float))
                  or not math.isfinite(value) or value <= 0):
                raise ValueError(f"{name} must be finite and positive.")
        if self.minimum_span_seconds > self.history_minutes * 60:
            raise ValueError("Minimum span cannot exceed history window.")
        if self.maximum_speed_knots > MAXIMUM_AIS_SPEED_KNOTS:
            raise ValueError("Maximum supported speed exceeds the valid AIS range.")


@dataclass(frozen=True)
class MissingSpeedResult(MitigationResult):
    status: SpeedStatus
    original_sog: float | None = None
    estimated_sog: float | None = None
    east_velocity_mps: float | None = None
    north_velocity_mps: float | None = None
    fit_residual_meters: float | None = None
    maximum_velocity_deviation_knots: float | None = None
    used_reports: int = 0
    history_span_seconds: float = 0.0

    @property
    def can_predict(self) -> bool:
        """Speed evidence supported; C can still predict without supported SOG."""
        return self.status in (SpeedStatus.OBSERVED, SpeedStatus.ESTIMATED)


@dataclass(frozen=True)
class SpeedRepair:
    """Private effective feed and per-missing-report audit; never model features."""

    reports: pd.DataFrame
    audit: tuple[MissingSpeedResult, ...]


@dataclass(frozen=True)
class MissingSpeedMitigation(BaseMitigation):
    gate: GateConfig
    config: MissingSpeedConfig = MissingSpeedConfig()
    name: ClassVar[str] = "MissingSpeedMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate)}

    def _prepare(self, reports: pd.DataFrame, clock: pd.Timestamp | str) -> tuple[pd.DataFrame, pd.Timestamp]:
        received, clock = self._prepare_reports(reports, clock)
        for name in ("latitude", "longitude", "sog"):
            self._numeric_field(received, name)
        return received, clock

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> MissingSpeedResult:
        """Assess the latest observation; never estimate present speed from old fixes."""
        received, clock = self._prepare(reports, decision_time)
        if received.empty:
            return MissingSpeedResult(SpeedStatus.NO_REPORTS, decision_time=clock)
        latest = self._latest_received_time(received, clock, latest_received_time)
        return self._estimate(received, received.iloc[-1], clock, latest)

    def repair_reports(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str) -> SpeedRepair:
        """Repair history causally per observation; unsupported speeds remain missing.

        A report's fit uses fixes no later than its measurement time and available
        at its own delivery time. Later fixes never retrospectively improve it.
        Only numeric SOG values in [0,102.2] count as observed; zero is not missing.
        """
        received, clock = self._prepare(reports, decision_time)
        effective = received.copy(deep=True)
        speeds = self._numeric_field(received, "sog")
        valid = np.isfinite(speeds) & (speeds >= 0) & (speeds <= MAXIMUM_AIS_SPEED_KNOTS)
        if valid.all():
            return SpeedRepair(effective, ())
        effective["sog"] = speeds
        audit = []
        for position in np.flatnonzero(~valid):
            target = received.iloc[position]
            delivery = target.get("delivered_time", target.time)
            preceding = received.loc[received.time.le(target.time)]
            if "delivered_time" in preceding:
                preceding = preceding.loc[preceding.delivered_time.le(delivery)]
            result = self._estimate(preceding, target, delivery, target.time)
            effective.iloc[position, effective.columns.get_loc("sog")] = (
                result.estimated_sog if result.status == SpeedStatus.ESTIMATED else np.nan)
            audit.append(result)
        return SpeedRepair(effective, tuple(audit))

    def _estimate(self, received: pd.DataFrame, target: pd.Series, clock: pd.Timestamp,
                  latest_received: pd.Timestamp) -> MissingSpeedResult:
        raw = float(target.sog) if pd.notna(target.sog) else float("nan")
        base = MissingSpeedResult(
            SpeedStatus.UNSUPPORTED, decision_time=clock, mmsi=str(target.mmsi),
            observation_time=target.time, latest_received_time=latest_received,
            report_age_minutes=(clock - target.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - latest_received).total_seconds() / 60,
            original_sog=raw if np.isfinite(raw) else None)
        if np.isfinite(raw) and 0 <= raw <= MAXIMUM_AIS_SPEED_KNOTS:
            return replace(base, status=SpeedStatus.OBSERVED)
        history = received.loc[received.time.between(
            target.time - pd.Timedelta(minutes=self.config.history_minutes), target.time)]
        points = history[["latitude", "longitude"]].to_numpy(dtype=float)
        if not (np.isfinite(points).all() and (abs(points[:, 0]) <= 90).all()
                and (abs(points[:, 1]) <= 180).all()):
            return replace(base, reasons=("invalid_positions",))
        history = history.drop_duplicates(["time", "latitude", "longitude"])
        span = (history.time.iloc[-1] - history.time.iloc[0]).total_seconds()
        base = replace(base, used_reports=len(history), history_span_seconds=span)
        if len(history) < self.config.minimum_reports or span < self.config.minimum_span_seconds:
            return replace(base, reasons=("insufficient_motion_history",))
        gaps = history.time.diff().dt.total_seconds().dropna().to_numpy()
        if (gaps <= 0).any() or (gaps > self.config.maximum_gap_seconds).any():
            return replace(base, reasons=("discontinuous_or_conflicting_positions",))
        east, north, residual = history_velocity(history, self.gate)
        pair_velocity = np.diff(local_positions(history, self.gate), axis=0) / gaps[:, None]
        deviation = float(np.linalg.norm(pair_velocity - np.array([east, north]), axis=1).max()
                          / KNOTS_TO_METERS_PER_SECOND)
        speed = float(np.hypot(east, north) / KNOTS_TO_METERS_PER_SECOND)
        pair_speed = np.linalg.norm(pair_velocity, axis=1) / KNOTS_TO_METERS_PER_SECOND
        if not np.isfinite([east, north, residual, speed, deviation]).all():
            return replace(base, reasons=("invalid_motion_fit",))
        base = replace(base, east_velocity_mps=east, north_velocity_mps=north,
                       fit_residual_meters=residual, maximum_velocity_deviation_knots=deviation)
        reasons = []
        if speed > self.config.maximum_speed_knots or (pair_speed > self.config.maximum_speed_knots).any():
            reasons.append("implausible_position_speed")
        if residual > self.config.maximum_fit_residual_meters:
            reasons.append("inconsistent_motion_fit")
        if deviation > self.config.maximum_velocity_deviation_knots:
            reasons.append("inconsistent_recent_velocity")
        if reasons:
            return replace(base, reasons=tuple(reasons))
        return replace(base, status=SpeedStatus.ESTIMATED, estimated_sog=speed)

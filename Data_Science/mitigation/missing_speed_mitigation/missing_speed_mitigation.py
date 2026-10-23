"""Reconstruct unavailable SOG from supported motion at that observation's time."""

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult
from ..trusted_motion import MAXIMUM_AIS_SPEED_KNOTS, MotionFitConfig, fit_recent_motion


class SpeedStatus(str, Enum):
    NO_REPORTS = "no_reports"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MissingSpeedConfig(MotionFitConfig):
    """Fixed research defaults; not tuned on the evaluation outcomes."""


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
        fit = fit_recent_motion(received, target.time, self.gate, self.config)
        base = replace(base, used_reports=fit.used_reports, history_span_seconds=fit.history_span_seconds,
            east_velocity_mps=fit.east_velocity_mps, north_velocity_mps=fit.north_velocity_mps,
            fit_residual_meters=fit.fit_residual_meters,
            maximum_velocity_deviation_knots=fit.maximum_velocity_deviation_knots, reasons=fit.reasons)
        return replace(base, status=SpeedStatus.ESTIMATED, estimated_sog=fit.speed_knots) if fit.supported else base

"""Reconstruct unavailable COG only when recent position-derived direction is supported."""

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult
from ..trusted_motion import MotionFitConfig, fit_recent_motion


class CourseStatus(str, Enum):
    NO_REPORTS = "no_reports"
    OBSERVED = "observed"
    ESTIMATED = "estimated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MissingCourseConfig(MotionFitConfig):
    """Speed's fixed fit checks plus movement/direction checks; research defaults."""

    minimum_speed_knots: float = 1.0
    minimum_displacement_meters: float = 30.0
    maximum_direction_deviation_degrees: float = 20.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.minimum_speed_knots >= self.maximum_speed_knots:
            raise ValueError("Minimum movement speed must be below maximum supported speed.")
        if self.maximum_direction_deviation_degrees > 180:
            raise ValueError("Circular direction disagreement cannot exceed 180 degrees.")


@dataclass(frozen=True)
class MissingCourseResult(MitigationResult):
    status: CourseStatus
    original_cog: float | None = None
    estimated_cog: float | None = None
    east_velocity_mps: float | None = None
    north_velocity_mps: float | None = None
    fit_residual_meters: float | None = None
    maximum_velocity_deviation_knots: float | None = None
    derived_speed_knots: float | None = None
    displacement_meters: float | None = None
    maximum_direction_deviation_degrees: float | None = None
    used_reports: int = 0
    history_span_seconds: float = 0.0

    @property
    def can_predict(self) -> bool:
        """Direction evidence supported; C can still predict with missing COG."""
        return self.status in (CourseStatus.OBSERVED, CourseStatus.ESTIMATED)


@dataclass(frozen=True)
class CourseRepair:
    reports: pd.DataFrame
    audit: tuple[MissingCourseResult, ...]


@dataclass(frozen=True)
class MissingCourseMitigation(BaseMitigation):
    gate: GateConfig
    config: MissingCourseConfig = MissingCourseConfig()
    name: ClassVar[str] = "MissingCourseMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate)}

    def _prepare(self, reports: pd.DataFrame, clock: pd.Timestamp | str) -> tuple[pd.DataFrame, pd.Timestamp]:
        received, clock = self._prepare_reports(reports, clock)
        for name in ("latitude", "longitude", "cog"):
            self._numeric_field(received, name)
        return received, clock

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> MissingCourseResult:
        """Assess course at the latest real observation, preserving its age."""
        received, clock = self._prepare(reports, decision_time)
        if received.empty:
            return MissingCourseResult(CourseStatus.NO_REPORTS, decision_time=clock)
        latest = self._latest_received_time(received, clock, latest_received_time)
        return self._estimate(received, received.iloc[-1], clock, latest)

    def repair_reports(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str) -> CourseRepair:
        """Repair only COG on a copy; fit each report using its own past and delivery clock."""
        received, _ = self._prepare(reports, decision_time)
        effective = received.copy(deep=True)
        courses = self._numeric_field(received, "cog")
        valid = np.isfinite(courses) & (courses >= 0) & (courses < 360)
        if valid.all():
            return CourseRepair(effective, ())
        effective["cog"] = courses
        audit = []
        for position in np.flatnonzero(~valid):
            target = received.iloc[position]
            delivery = target.get("delivered_time", target.time)
            preceding = received.loc[received.time.le(target.time)]
            if "delivered_time" in preceding:
                preceding = preceding.loc[preceding.delivered_time.le(delivery)]
            result = self._estimate(preceding, target, delivery, target.time)
            effective.iloc[position, effective.columns.get_loc("cog")] = (
                result.estimated_cog if result.status == CourseStatus.ESTIMATED else np.nan)
            audit.append(result)
        return CourseRepair(effective, tuple(audit))

    def _estimate(self, received: pd.DataFrame, target: pd.Series, clock: pd.Timestamp,
                  latest_received: pd.Timestamp) -> MissingCourseResult:
        raw = float(target.cog) if pd.notna(target.cog) else float("nan")
        base = MissingCourseResult(
            CourseStatus.UNSUPPORTED, decision_time=clock, mmsi=str(target.mmsi),
            observation_time=target.time, latest_received_time=latest_received,
            report_age_minutes=(clock - target.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - latest_received).total_seconds() / 60,
            original_cog=raw if np.isfinite(raw) else None)
        if np.isfinite(raw) and 0 <= raw < 360:
            return replace(base, status=CourseStatus.OBSERVED)
        fit = fit_recent_motion(received, target.time, self.gate, self.config)
        base = replace(base, used_reports=fit.used_reports, history_span_seconds=fit.history_span_seconds,
            east_velocity_mps=fit.east_velocity_mps, north_velocity_mps=fit.north_velocity_mps,
            fit_residual_meters=fit.fit_residual_meters, derived_speed_knots=fit.speed_knots,
            maximum_velocity_deviation_knots=fit.maximum_velocity_deviation_knots,
            displacement_meters=fit.displacement_meters,
            maximum_direction_deviation_degrees=fit.maximum_direction_deviation_degrees, reasons=fit.reasons)
        if not fit.supported:
            return base
        reasons = []
        if fit.speed_knots < self.config.minimum_speed_knots or fit.minimum_segment_speed_knots < self.config.minimum_speed_knots:
            reasons.append("insufficient_motion_for_course")
        if fit.displacement_meters < self.config.minimum_displacement_meters:
            reasons.append("insufficient_displacement_for_course")
        if fit.maximum_direction_deviation_degrees > self.config.maximum_direction_deviation_degrees:
            reasons.append("inconsistent_recent_direction")
        if reasons:
            return replace(base, reasons=tuple(reasons))
        direction = float(np.rad2deg(np.arctan2(fit.east_velocity_mps, fit.north_velocity_mps)) % 360)
        if direction >= 360:  # Floating-point wrapping immediately west of true north.
            direction = 0.0
        return replace(base, status=CourseStatus.ESTIMATED, estimated_cog=direction)

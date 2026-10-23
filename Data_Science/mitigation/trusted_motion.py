"""Pure causal position fitting shared by missing navigation measurements."""

from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, history_velocity, local_positions

MAXIMUM_AIS_SPEED_KNOTS = 102.2


@dataclass(frozen=True)
class MotionFitConfig:
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
class MotionFit:
    used_reports: int = 0
    history_span_seconds: float = 0.0
    east_velocity_mps: float | None = None
    north_velocity_mps: float | None = None
    fit_residual_meters: float | None = None
    maximum_velocity_deviation_knots: float | None = None
    speed_knots: float | None = None
    displacement_meters: float | None = None
    minimum_segment_speed_knots: float | None = None
    maximum_direction_deviation_degrees: float | None = None
    reasons: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return not self.reasons and self.speed_knots is not None


def fit_recent_motion(reports: pd.DataFrame, observation_time: pd.Timestamp,
                      gate: GateConfig, config: MotionFitConfig) -> MotionFit:
    """Fit only the sorted trailing positions; never read speed, course or labels."""
    history = reports.loc[reports.time.between(
        observation_time - pd.Timedelta(minutes=config.history_minutes), observation_time)]
    if history.empty:
        return MotionFit(reasons=("insufficient_motion_history",))
    points = history[["latitude", "longitude"]].to_numpy(dtype=float, na_value=np.nan)
    if not (np.isfinite(points).all() and (abs(points[:, 0]) <= 90).all()
            and (abs(points[:, 1]) <= 180).all()):
        return MotionFit(reasons=("invalid_positions",))
    history = history.drop_duplicates(["time", "latitude", "longitude"])
    span = (history.time.iloc[-1] - history.time.iloc[0]).total_seconds()
    diagnostic = {"used_reports": len(history), "history_span_seconds": span}
    if len(history) < config.minimum_reports or span < config.minimum_span_seconds:
        return MotionFit(**diagnostic, reasons=("insufficient_motion_history",))
    gaps = history.time.diff().dt.total_seconds().dropna().to_numpy()
    if (gaps <= 0).any() or (gaps > config.maximum_gap_seconds).any():
        return MotionFit(**diagnostic, reasons=("discontinuous_or_conflicting_positions",))
    east, north, residual = history_velocity(history, gate)
    positions = local_positions(history, gate)
    pair_velocity = np.diff(positions, axis=0) / gaps[:, None]
    deviation = float(np.linalg.norm(pair_velocity - np.array([east, north]), axis=1).max()
                      / KNOTS_TO_METERS_PER_SECOND)
    speed = float(np.hypot(east, north) / KNOTS_TO_METERS_PER_SECOND)
    pair_speed = np.linalg.norm(pair_velocity, axis=1) / KNOTS_TO_METERS_PER_SECOND
    if not np.isfinite([east, north, residual, speed, deviation]).all():
        return MotionFit(**diagnostic, reasons=("invalid_motion_fit",))
    direction = np.rad2deg(np.arctan2(east, north)) % 360
    pair_direction = np.rad2deg(np.arctan2(pair_velocity[:, 0], pair_velocity[:, 1])) % 360
    direction_deviation = float(np.abs((pair_direction - direction + 180) % 360 - 180).max())
    reasons = []
    if speed > config.maximum_speed_knots or (pair_speed > config.maximum_speed_knots).any():
        reasons.append("implausible_position_speed")
    if residual > config.maximum_fit_residual_meters:
        reasons.append("inconsistent_motion_fit")
    if deviation > config.maximum_velocity_deviation_knots:
        reasons.append("inconsistent_recent_velocity")
    return MotionFit(**diagnostic, east_velocity_mps=east, north_velocity_mps=north,
        fit_residual_meters=residual, maximum_velocity_deviation_knots=deviation, speed_knots=speed,
        displacement_meters=float(np.linalg.norm(positions[-1] - positions[0])),
        minimum_segment_speed_knots=float(pair_speed.min()),
        maximum_direction_deviation_degrees=direction_deviation, reasons=tuple(reasons))

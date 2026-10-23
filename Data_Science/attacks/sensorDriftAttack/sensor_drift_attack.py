"""Smooth speed bias with no changes to reports' motion, identity or timing."""

from dataclasses import dataclass
import math
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

from Optimized_Model.replay import Condition, ReportStream
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.drift_profile import smooth_bias

MAXIMUM_REPORTED_SPEED_KNOTS = 102.2


@dataclass(frozen=True)
class SensorDriftConfig:
    """A signed rate sets direction; rate variation never reverses that direction."""

    drift_rate_knots_per_minute: float = -.1
    rate_variation_fraction: float = .25
    variation_period_minutes: float = 20.
    maximum_bias_knots: float = 3.
    seed: int = 42
    target_mmsi: str | None = None
    start_time: pd.Timestamp | str | None = None

    def __post_init__(self) -> None:
        for name in ("drift_rate_knots_per_minute", "rate_variation_fraction",
                     "variation_period_minutes", "maximum_bias_knots"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number.")
        if not 0 <= self.rate_variation_fraction < 1:
            raise ValueError("rate_variation_fraction must be between 0 (inclusive) and 1 (exclusive).")
        if self.variation_period_minutes <= 0:
            raise ValueError("variation_period_minutes must be positive.")
        if self.maximum_bias_knots < 0:
            raise ValueError("maximum_bias_knots cannot be negative.")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer.")
        if self.target_mmsi is not None:
            if (not isinstance(self.target_mmsi, str) or not self.target_mmsi.isascii()
                    or not self.target_mmsi.isdigit() or len(self.target_mmsi) != 9):
                raise ValueError("target_mmsi must be a nine-digit string or None.")
        if self.start_time is not None:
            if not isinstance(self.start_time, (str, pd.Timestamp)):
                raise ValueError("start_time must be an ISO timestamp string, pandas Timestamp, or None.")
            try:
                start = pd.Timestamp(self.start_time)
            except (TypeError, ValueError) as error:
                raise ValueError("start_time must be a valid timestamp.") from error
            if pd.isna(start):
                raise ValueError("start_time cannot be missing.")
            object.__setattr__(self, "start_time", start)


@dataclass(frozen=True)
class SensorDriftAttack(BaseAttack):
    """Add simulated bias to original reported speed; never modify ETA directly."""

    config: SensorDriftConfig = SensorDriftConfig()
    name: ClassVar[str] = "SensorDriftAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return {
            "drift_rate_knots_per_minute": self.config.drift_rate_knots_per_minute,
            "rate_variation_fraction": self.config.rate_variation_fraction,
            "variation_period_minutes": self.config.variation_period_minutes,
            "maximum_bias_knots": self.config.maximum_bias_knots,
            "seed": self.config.seed, "target_mmsi": self.config.target_mmsi,
            "start_time": self.config.start_time.isoformat() if self.config.start_time is not None else None,
        }

    def _bias(self, elapsed_minutes: np.ndarray, mmsi: str) -> np.ndarray:
        """Integrate a smoothly varying signed rate, then smoothly bound the bias."""
        settings = self.config
        return smooth_bias(elapsed_minutes, rate=settings.drift_rate_knots_per_minute,
                           variation=settings.rate_variation_fraction, period_minutes=settings.variation_period_minutes,
                           maximum=settings.maximum_bias_knots, seed=settings.seed, identity=f"sensor-drift:{mmsi}")

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        if "sog" not in prepared:
            raise ValueError("Missing speed column: sog.")
        values = prepared["sog"]
        if not is_numeric_dtype(values) or is_bool_dtype(values) or is_complex_dtype(values):
            raise ValueError("sog must contain parsed real numeric speeds or missing values.")
        speeds = values.to_numpy(dtype=float, na_value=np.nan, copy=True)
        valid = ~np.isnan(speeds)
        if np.any(valid & (~np.isfinite(speeds) | (speeds < 0) | (speeds > MAXIMUM_REPORTED_SPEED_KNOTS))):
            raise ValueError("sog must be missing or finite speeds between 0 and 102.2 knots.")
        bias = np.zeros(len(prepared), dtype=float)
        # Positional indices support repeated DataFrame index labels and duplicate reports.
        for mmsi, positions in prepared.groupby(prepared["mmsi"].astype(str), sort=False).indices.items():
            if self.config.target_mmsi is not None and mmsi != self.config.target_mmsi:
                continue
            times = prepared["time"].iloc[positions]
            start = self.config.start_time if self.config.start_time is not None else times.min()
            try:
                elapsed = ((times-start).dt.total_seconds()/60).to_numpy().clip(min=0)
            except TypeError as error:
                raise ValueError("start_time and report times must use compatible timezones.") from error
            bias[positions] = self._bias(elapsed, mmsi)
        candidate = speeds+bias
        changed_speeds = np.clip(candidate, 0, MAXIMUM_REPORTED_SPEED_KNOTS)
        affected = valid & (changed_speeds != speeds)
        if affected.any():
            prepared["sog"] = changed_speeds
        audit = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        audit["original_sog"] = speeds
        audit["reported_sog"] = changed_speeds
        audit["requested_bias_knots"] = bias
        audit["applied_bias_knots"] = changed_speeds-speeds
        audit["clipped"] = valid & ((candidate < 0) | (candidate > MAXIMUM_REPORTED_SPEED_KNOTS))
        audit["fault_applied"] = affected
        audit["action"] = np.where(affected, "speed_drifted", "retained")
        audit["attack"], audit["seed"] = self.name, self.config.seed
        return ReportStream(prepared.sort_values("time", kind="stable"), audit)

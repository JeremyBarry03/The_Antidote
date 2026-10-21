"""Independent Gaussian SOG/COG fluctuations on stable selected report identities."""

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

from Optimized_Model.replay import Condition, ReportStream, seeded_generator
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.missing_field import MissingFieldConfig, select_reports

SEVERITY_LEVELS = MappingProxyType({
    "low": (.5, 2.), "medium": (1., 5.), "high": (2., 10.), "extreme": (4., 20.),
})
MAXIMUM_VALID_SOURCE_SOG = 102.2


@dataclass(frozen=True)
class SensorDeteriorationConfig:
    """Sigma zero disables a field; fractions select reports before either draw."""

    sog_sigma_knots: float = 1.
    cog_sigma_degrees: float = 5.
    affected_fraction: float = 1.
    seed: int = 42
    target_mmsi: str | None = None

    def __post_init__(self) -> None:
        for name in ("sog_sigma_knots", "cog_sigma_degrees"):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be a finite nonnegative number.")
        # Reuse selection validation without inheriting missing-field behavior.
        self.selection

    @property
    def selection(self) -> MissingFieldConfig:
        return MissingFieldConfig(self.affected_fraction, self.seed, self.target_mmsi)

    @classmethod
    def from_severity(cls, severity: str, *, affected_fraction: float = 1., seed: int = 42,
                      target_mmsi: str | None = None) -> "SensorDeteriorationConfig":
        if severity not in SEVERITY_LEVELS:
            raise ValueError(f"Unknown deterioration severity: {severity}.")
        sog, cog = SEVERITY_LEVELS[severity]
        return cls(sog, cog, affected_fraction, seed, target_mmsi)


def _measurements(reports: pd.DataFrame, field: str) -> np.ndarray:
    if field not in reports:
        raise ValueError(f"Missing measurement column: {field}.")
    values = reports[field]
    if not is_numeric_dtype(values) or is_bool_dtype(values) or is_complex_dtype(values):
        raise ValueError(f"{field} must contain parsed real numeric measurements or missing values.")
    return values.to_numpy(dtype=float, na_value=np.nan, copy=True)


@dataclass(frozen=True)
class SensorDeteriorationAttack(BaseAttack):
    """Change measurements only; do not load models, score ETAs or repair data."""

    config: SensorDeteriorationConfig = SensorDeteriorationConfig()
    name: ClassVar[str] = "SensorDeteriorationAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return {"sog_sigma_knots": self.config.sog_sigma_knots,
                "cog_sigma_degrees": self.config.cog_sigma_degrees,
                **self.config.selection.as_parameters()}

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        sog, cog = (_measurements(prepared, field) for field in ("sog", "cog"))
        valid_sog = np.isfinite(sog) & (sog >= 0) & (sog <= MAXIMUM_VALID_SOURCE_SOG)
        valid_cog = np.isfinite(cog) & (cog >= 0) & (cog < 360)
        enabled_sog = valid_sog & (self.config.sog_sigma_knots > 0)
        enabled_cog = valid_cog & (self.config.cog_sigma_degrees > 0)
        selected = select_reports(prepared, self.config.selection).to_numpy() & (enabled_sog | enabled_cog)
        noise = np.zeros((len(prepared), 2))
        draws: dict[str, np.ndarray] = {}
        # Identity-based draws are independent of ordering, duplicates, future
        # reports, enabled fields and sigma. Combined mode uses one selected set.
        for position in np.flatnonzero(selected):
            identity = f"sensor-deterioration:{prepared.mmsi.iloc[position]}:{prepared.time.iloc[position].isoformat()}"
            if identity not in draws:
                draws[identity] = seeded_generator(self.config.seed, identity).standard_normal(2)
            noise[position] = draws[identity]
        sog_mask, cog_mask = selected & enabled_sog, selected & enabled_cog
        sog_noise = np.zeros(len(prepared))
        cog_noise = np.zeros(len(prepared))
        with np.errstate(over="ignore", invalid="ignore"):
            sog_noise[sog_mask] = noise[sog_mask, 0]*self.config.sog_sigma_knots
            cog_noise[cog_mask] = noise[cog_mask, 1]*self.config.cog_sigma_degrees
            speed_candidates = sog[sog_mask]+sog_noise[sog_mask]
            course_candidates = cog[cog_mask]+cog_noise[cog_mask]
        if not np.isfinite(speed_candidates).all() or not np.isfinite(course_candidates).all():
            raise ValueError("Noise sigma is too large to produce finite measurements.")
        reported_sog, reported_cog = sog.copy(), cog.copy()
        reported_sog[sog_mask] = np.maximum(0, speed_candidates)
        reported_cog[cog_mask] = course_candidates % 360
        # Floating-point modulo can round a tiny negative result to exactly 360.
        reported_cog[cog_mask & (reported_cog >= 360)] = 0.
        speed_changed = sog_mask & (reported_sog != sog)
        course_changed = cog_mask & (reported_cog != cog)
        if speed_changed.any():
            prepared["sog"] = reported_sog
        if course_changed.any():
            prepared["cog"] = reported_cog
        audit = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        audit["selected"] = selected
        audit["eligible_sog"], audit["eligible_cog"] = valid_sog, valid_cog
        audit["original_sog"], audit["reported_sog"] = sog, reported_sog
        audit["original_cog"], audit["reported_cog"] = cog, reported_cog
        audit["requested_sog_noise_knots"], audit["requested_cog_noise_degrees"] = sog_noise, cog_noise
        applied_sog, applied_cog = np.zeros(len(prepared)), np.zeros(len(prepared))
        applied_sog[sog_mask] = reported_sog[sog_mask]-sog[sog_mask]
        applied_cog[cog_mask] = (reported_cog[cog_mask]-cog[cog_mask]+180) % 360-180
        audit["applied_sog_noise_knots"], audit["applied_cog_noise_degrees"] = applied_sog, applied_cog
        audit["sog_clipped"] = sog_mask & (sog+sog_noise < 0)
        audit["cog_wrapped"] = cog_mask & ((cog+cog_noise < 0) | (cog+cog_noise >= 360))
        audit["sog_changed"], audit["cog_changed"] = speed_changed, course_changed
        affected = speed_changed | course_changed
        audit["fault_applied"] = affected
        audit["action"] = np.where(affected, "navigation_noised", "retained")
        audit["attack"], audit["seed"] = self.name, self.config.seed
        return ReportStream(prepared, audit)

"""Shared deterministic masking for numeric report fields."""

from dataclasses import dataclass
import hashlib
import math
from typing import Literal

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from Optimized_Model.replay import ReportStream
from .base_attack import AttackParameters


@dataclass(frozen=True)
class MissingFieldConfig:
    """Select original reports without treating existing missingness as a new fault."""

    affected_fraction: float = .25
    seed: int = 42
    target_mmsi: str | None = None

    def __post_init__(self) -> None:
        if (isinstance(self.affected_fraction, bool) or not isinstance(self.affected_fraction, (int, float))
                or not math.isfinite(self.affected_fraction) or not 0 <= self.affected_fraction <= 1):
            raise ValueError("affected_fraction must be a finite number between 0 and 1.")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer.")
        if self.target_mmsi is not None:
            if (not isinstance(self.target_mmsi, str) or not self.target_mmsi.isascii()
                    or not self.target_mmsi.isdigit() or len(self.target_mmsi) != 9):
                raise ValueError("target_mmsi must be a nine-digit string or None.")

    def as_parameters(self) -> AttackParameters:
        return {"affected_fraction": self.affected_fraction, "seed": self.seed, "target_mmsi": self.target_mmsi}


def mask_field(
    prepared: pd.DataFrame, config: MissingFieldConfig, field: Literal['sog', 'cog', 'vessel_type'], attack_name: str,
    *, selection_unit: Literal['report', 'vessel'] = 'report',
) -> ReportStream:
    """Mask one numeric observation column in an already copied/validated stream."""
    label = {'sog': 'speed', 'cog': 'course', 'vessel_type': 'vessel_class'}[field]
    if selection_unit not in ('report', 'vessel'):
        raise ValueError("selection_unit must be 'report' or 'vessel'.")
    if field not in prepared:
        raise ValueError(f"Missing {label} column: {field}.")
    values = prepared[field]
    if not is_numeric_dtype(values) or is_bool_dtype(values):
        raise ValueError(f"{field} must contain parsed numeric {label} values or missing values.")
    affected = select_reports(prepared, config, selection_unit=selection_unit) & values.notna()
    log = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
    log[f"original_{field}"] = values
    log["fault_applied"] = affected.to_numpy()
    log["action"] = affected.map({True: f"{label}_removed", False: "retained"}).to_numpy()
    log["attack"] = attack_name
    log["seed"] = config.seed
    prepared[field] = values.mask(affected)
    return ReportStream(prepared.sort_values("time", kind="stable"), log)


def select_reports(
    prepared: pd.DataFrame, config: MissingFieldConfig, *, selection_unit: Literal['report', 'vessel'] = 'report',
) -> pd.Series:
    """Select reproducible report identities, independently of values and outcomes."""
    if selection_unit not in ('report', 'vessel'):
        raise ValueError("selection_unit must be 'report' or 'vessel'.")
    identities = [f"{config.seed}:{row.mmsi}:{row.time.isoformat()}" if selection_unit == 'report'
                  else f"{config.seed}:{row.mmsi}" for row in prepared.itertuples()]
    fractions = pd.Series([
        int.from_bytes(hashlib.sha256(identity.encode()).digest()[:8], "little") / 2**64
        for identity in identities
    ], index=prepared.index, dtype=float)
    selected = fractions.lt(config.affected_fraction)
    if config.target_mmsi is not None:
        selected &= prepared.mmsi.astype(str).eq(config.target_mmsi)
    return selected

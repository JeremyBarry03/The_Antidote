"""Mask selected measured speeds while retaining every report and its timing."""

from dataclasses import dataclass
import hashlib
import math
from typing import ClassVar

import pandas as pd
from pandas.api.types import is_numeric_dtype

from Optimized_Model.replay import Condition, ReportStream
from attacks.base_attack import AttackParameters, BaseAttack


@dataclass(frozen=True)
class MissingSpeedConfig:
    """Prevalence selects original reports; naturally missing speeds stay missing."""

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


@dataclass(frozen=True)
class MissingSpeedAttack(BaseAttack):
    """Remove speed evidence; never substitute zero or remove the vessel position."""

    config: MissingSpeedConfig
    name: ClassVar[str] = "MissingSpeedAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return {"affected_fraction": self.config.affected_fraction, "seed": self.config.seed,
                "target_mmsi": self.config.target_mmsi}

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        if "sog" not in prepared:
            raise ValueError("Missing speed column: sog.")
        if not is_numeric_dtype(prepared.sog) or prepared.sog.dtype == bool:
            raise ValueError("sog must contain parsed numeric speeds or missing values.")
        fractions = pd.Series([
            int.from_bytes(hashlib.sha256(f"{self.config.seed}:{row.mmsi}:{row.time.isoformat()}".encode()).digest()[:8], "little") / 2**64
            for row in prepared.itertuples()
        ], index=prepared.index, dtype=float)
        affected = fractions.lt(self.config.affected_fraction) & prepared.sog.notna()
        if self.config.target_mmsi is not None:
            affected &= prepared.mmsi.astype(str).eq(self.config.target_mmsi)
        log = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        log["original_sog"] = prepared.sog
        log["fault_applied"] = affected.to_numpy()
        log["action"] = affected.map({True: "speed_removed", False: "retained"}).to_numpy()
        log["attack"] = self.name
        log["seed"] = self.config.seed
        prepared["sog"] = prepared.sog.mask(affected)
        return ReportStream(prepared.sort_values("time", kind="stable"), log)

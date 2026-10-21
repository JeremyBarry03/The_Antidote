"""Amplify existing vessel representation imbalance in prepared training rows."""

from dataclasses import asdict, dataclass
import math
from numbers import Integral, Real
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

from ..base_attack import AttackParameters


@dataclass(frozen=True)
class UnequalVessellRecordConfig:
    """Multiply the rows of the busiest training vessels, including the original."""

    record_multiplier: int = 5
    vessel_fraction: float = .2

    def __post_init__(self) -> None:
        if (isinstance(self.record_multiplier, bool)
                or not isinstance(self.record_multiplier, Integral)
                or not 1 <= self.record_multiplier <= 100):
            raise ValueError("record_multiplier must be an integer from 1 to 100.")
        if (isinstance(self.vessel_fraction, bool)
                or not isinstance(self.vessel_fraction, Real)
                or not math.isfinite(self.vessel_fraction)
                or not 0 < self.vessel_fraction <= 1):
            raise ValueError("vessel_fraction must be finite and in (0, 1].")


@dataclass(frozen=True)
class TrainingAttackResult:
    """Copies for training, with replication truth kept outside model columns."""

    examples: pd.DataFrame
    modification_log: pd.DataFrame
    vessel_summary: pd.DataFrame


class UnequalVessellRecordAttack:
    """Repeat training examples for the vessels that already have most rows.

    Selection uses only training row counts, never errors, targets or evaluation
    vessels. This is a training attack, so it intentionally does not implement
    BaseAttack's report-stream interface. It performs no fitting or I/O.
    """

    name: ClassVar[str] = "UnequalVessellRecordAttack"
    stage: ClassVar[Literal["training"]] = "training"

    def __init__(self, config: UnequalVessellRecordConfig) -> None:
        self.config = config

    @property
    def parameters(self) -> AttackParameters:
        return {key: int(value) if key == "record_multiplier" else float(value)
                for key, value in asdict(self.config).items()}

    def apply(self, examples: pd.DataFrame) -> TrainingAttackResult:
        """Return unchanged-value replicas of explicit training-partition rows."""
        required = {"mmsi", "approach_id", "split"}
        missing = required - set(examples.columns)
        if missing:
            raise ValueError(f"Missing training columns: {sorted(missing)}.")
        if examples.columns.duplicated().any():
            raise ValueError("Training column names must be unique.")
        if examples.empty:
            raise ValueError("At least one training example is required.")
        if not examples["split"].eq("train").all():
            raise ValueError("Only split='train' rows may be oversampled; validation/evaluation stay untouched.")
        if (examples["mmsi"].isna().any()
                or not examples["mmsi"].astype(str).str.fullmatch(r"\d{9}").all()):
            raise ValueError("Training MMSI must contain nine digits.")
        if (examples["approach_id"].isna().any()
                or examples["approach_id"].astype(str).str.strip().eq("").any()):
            raise ValueError("Training approach_id cannot be missing or empty.")
        if examples.groupby("approach_id")["mmsi"].nunique().gt(1).any():
            raise ValueError("Each approach must belong to one MMSI.")

        # String identity breaks equal-count ties consistently, including after a shuffle.
        identities = examples["mmsi"].astype(str)
        counts = identities.value_counts().rename_axis("mmsi").reset_index(name="original_rows")
        counts = counts.sort_values(["original_rows", "mmsi"], ascending=[False, True]).reset_index(drop=True)
        selected_count = math.ceil(len(counts) * self.config.vessel_fraction)
        selected = set(counts["mmsi"].iloc[:selected_count])
        positions = np.flatnonzero(identities.isin(selected).to_numpy())
        extras = np.repeat(positions, self.config.record_multiplier - 1)
        source_positions = np.concatenate([np.arange(len(examples)), extras])
        attacked = examples.iloc[source_positions].copy(deep=True).reset_index(drop=True)
        replica = np.concatenate([
            np.zeros(len(examples), dtype=int),
            np.tile(np.arange(1, self.config.record_multiplier), len(positions)),
        ])
        audit = attacked[["mmsi", "approach_id"]].copy()
        audit["source_row"] = source_positions
        audit["replica"] = replica
        audit["fault_applied"] = replica > 0
        audit["action"] = np.where(replica > 0, "oversampled", "original")
        counts["selected"] = counts["mmsi"].isin(selected)
        counts["record_multiplier"] = np.where(counts["selected"], self.config.record_multiplier, 1)
        counts["attacked_rows"] = counts["original_rows"] * counts["record_multiplier"]
        counts["original_share"] = counts["original_rows"] / len(examples)
        counts["attacked_share"] = counts["attacked_rows"] / len(attacked)
        return TrainingAttackResult(attacked, audit, counts)

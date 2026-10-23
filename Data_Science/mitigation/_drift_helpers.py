"""Small shared helpers for causal drift checks; no learned or mutable state."""

from dataclasses import asdict
import math

import numpy as np
import pandas as pd

from .base_mitigation import BaseMitigation


def validate_config(config, integer_fields: tuple[str, ...]) -> None:
    for name, value in asdict(config).items():
        if name in integer_fields:
            if type(value) is not int or value < 3:
                raise ValueError(f"{name} must be an integer of at least three.")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive.")


def prepare(reports: pd.DataFrame, decision_time, fields: tuple[str, ...]) -> tuple[pd.DataFrame, pd.Timestamp]:
    received, clock = BaseMitigation._prepare_reports(reports, decision_time)
    for field in fields:
        received[field] = BaseMitigation._numeric_field(received, field)
    if "delivered_time" in received:
        received = received.sort_values(["time", "delivered_time"], kind="stable")
    # Audit columns and exact copies cannot create new evidence.
    return received.drop_duplicates(["mmsi", "time", *fields], keep="first").reset_index(drop=True), clock


def angle_difference(left, right):
    return np.abs((left - right + 180) % 360 - 180)


def ewma_fraction(minutes: float, time_constant: float) -> float:
    return float(-np.expm1(-minutes / time_constant))


def finite(value) -> float | None:
    return float(value) if pd.notna(value) and np.isfinite(value) else None

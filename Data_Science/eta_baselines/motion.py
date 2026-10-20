"""Causal geometry and circular statistics shared with optimized features."""

import numpy as np
import pandas as pd

from .configuration import GateConfig
from .features import METERS_PER_DEGREE

KNOTS_TO_METERS_PER_SECOND = 1852 / 3600


def local_positions(reports: pd.DataFrame, gate: GateConfig) -> np.ndarray:
    origin = (gate.south_latitude + gate.north_latitude) / 2
    east = (reports["longitude"].to_numpy() - gate.longitude) * METERS_PER_DEGREE * np.cos(np.deg2rad(origin))
    north = (reports["latitude"].to_numpy() - origin) * METERS_PER_DEGREE
    return np.column_stack([east, north])


def circular_summary(degrees: np.ndarray) -> tuple[float, float]:
    valid = degrees[np.isfinite(degrees)]
    if not len(valid):
        return float("nan"), float("nan")
    radians = np.deg2rad(valid)
    sine, cosine = np.sin(radians).mean(), np.cos(radians).mean()
    return float(np.rad2deg(np.arctan2(sine, cosine)) % 360), float(1 - np.hypot(sine, cosine))


def history_velocity(reports: pd.DataFrame, gate: GateConfig) -> tuple[float, float, float]:
    if len(reports) < 2:
        return float("nan"), float("nan"), float("nan")
    seconds = (reports["time"] - reports["time"].iloc[0]).dt.total_seconds().to_numpy()
    if seconds[-1] <= 0:
        return float("nan"), float("nan"), float("nan")
    positions = local_positions(reports, gate)
    coefficients = np.linalg.lstsq(np.column_stack([seconds, np.ones(len(seconds))]), positions, rcond=None)[0]
    residuals = positions - (seconds[:, None] * coefficients[0] + coefficients[1])
    return float(coefficients[0, 0]), float(coefficients[0, 1]), float(np.sqrt((residuals ** 2).sum(axis=1).mean()))

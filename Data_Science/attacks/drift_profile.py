"""Shared smooth bounded bias; no report selection or hidden measurement access."""

import numpy as np

from Optimized_Model.replay import seeded_generator


def smooth_bias(elapsed_minutes: np.ndarray, *, rate: float, variation: float,
                period_minutes: float, maximum: float, seed: int, identity: str) -> np.ndarray:
    if rate == 0 or maximum == 0:
        return np.zeros_like(elapsed_minutes)
    phase = seeded_generator(seed, identity).uniform(0, 2 * np.pi)
    with np.errstate(over="ignore", divide="ignore"):
        cycles = elapsed_minutes / period_minutes
        half_angle = np.pi * cycles
    if not np.isfinite(half_angle).all():
        raise ValueError("variation_period_minutes is too small for the supplied report times.")
    integral = elapsed_minutes * (1 + variation * np.sin(phase + half_angle) * np.sinc(cycles))
    with np.errstate(over="ignore", divide="ignore"):
        return maximum * np.tanh(rate * integral / maximum)

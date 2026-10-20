"""Shared metrics: equal approach contribution and explicit invalid outputs."""

import numpy as np
import pandas as pd


def approach_weights(examples: pd.DataFrame) -> np.ndarray:
    counts = examples.groupby("approach_id")["approach_id"].transform("size")
    weights = 1 / counts.to_numpy(dtype=float)
    return weights / weights.mean()


def score_predictions(predictions: pd.DataFrame) -> dict[str, float | int]:
    if predictions.empty:
        raise ValueError("Cannot evaluate an empty partition.")
    errors = predictions["error_minutes"]
    if not np.isfinite(errors).all():
        raise ValueError("Non-finite predictions cannot be silently excluded from metrics.")
    per_approach = predictions.assign(absolute_error=errors.abs()).groupby("approach_id").agg(
        mae=("absolute_error", "mean"), bias=("error_minutes", "mean"),
    )
    return {
        "snapshots": len(predictions),
        "approaches": len(per_approach),
        "vessels": predictions["mmsi"].nunique(),
        "approach_weighted_mae_minutes": float(per_approach["mae"].mean()),
        "approach_mae_p90_minutes": float(per_approach["mae"].quantile(.9)),
        "approach_weighted_bias_minutes": float(per_approach["bias"].mean()),
        "snapshot_median_absolute_error_minutes": float(errors.abs().median()),
        "snapshot_p90_absolute_error_minutes": float(errors.abs().quantile(.9)),
        "expired_predictions": int((predictions["predicted_remaining_minutes"] < 0).sum()),
        "negative_observation_duration_predictions": int(
            (predictions["predicted_observation_duration_minutes"] < 0).sum()
        ),
        "output_coverage": 1.0,
    }

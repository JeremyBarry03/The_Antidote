"""Paired accuracy must expose lost support instead of crediting absent forecasts."""

import numpy as np
import pandas as pd

from experiments.sensor_deterioration_attack.run import summarize


def test_summary_pairs_only_supported_original_and_attacked_decisions():
    frame = pd.DataFrame({"system": "C", "severity": "high", "mode": "both", "affected_fraction": 1.,
        "scenario": "high_both_1", "approach_id": ["a", "b"], "mmsi": ["111111111", "222222222"],
        "decision_id": ["one", "two"], "seed": 4201, "available": [True, False],
        "error_minutes": [2., np.nan], "original_error_minutes": [1., 100.],
        "absolute_error_change": [1., np.nan]})
    row = summarize(frame)
    assert row["coverage"] == .5 and row["paired_decisions"] == 1
    assert row["mae_minutes"] == 2. and row["mdae_minutes"] == 2.
    assert row["original_mae_minutes"] == 1. and row["mae_change_minutes"] == 1.
    assert row["mdae_change_minutes"] == 1.

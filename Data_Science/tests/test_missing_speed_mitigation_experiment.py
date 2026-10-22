"""Check paired scoring boundaries and equal-approach weighting."""

import numpy as np
import pandas as pd
import pytest

from experiments.missing_speed_mitigation.run import score, summarize
from Optimized_Model.features import OPTIMIZED_COLUMNS


def test_summary_weights_approaches_equally_and_reports_regressions():
    frame = pd.DataFrame({"split": "evaluation", "fraction": .5,
        "seed": [4201, 4201, 4201, 4201], "approach_id": ["a", "b", "b", "b"],
        "mmsi": ["1", "2", "2", "2"], "decision_id": ["a1", "b1", "b2", "b3"],
        "original_error": [2., 10., 10., 10.], "mitigated_error": [1., 8., 8., 8.],
        "missing_guarded_reports": 2, "estimated_reports": 1, "latest_speed_estimated": True})
    frame["absolute_error_change"] = frame.mitigated_error.abs() - frame.original_error.abs()
    summary = summarize(frame).iloc[0]
    assert summary.original_mae == 6 and summary.mitigated_mae == 4.5
    assert summary.original_mdae == 10 and summary.mitigated_mdae == 8
    assert summary.mae_change == pytest.approx(-1.5)
    assert summary.improved_approaches == 2 and summary.worsened_approaches == 0
    assert summary.original_coverage == summary.mitigated_coverage == 1
    assert summary.reconstruction_rate == .5


def test_scoring_never_passes_labels_or_audit_to_frozen_predictor():
    clock = pd.Timestamp("2024-04-09 12:00")
    rows = [{**dict.fromkeys(OPTIMIZED_COLUMNS, 0.), "observation_time": clock,
             "decision_time": clock, "arrival_time": "hidden", "audit_truth": "hidden"}] * 2
    metadata = pd.DataFrame({"supported": [True, False], "arrival_time": clock + pd.Timedelta(minutes=20)})

    class Predictor:
        def predict(self, inputs):
            assert set(inputs) == set(OPTIMIZED_COLUMNS) | {"observation_time", "decision_time"}
            assert len(inputs) == 1
            return pd.DataFrame({"predicted_arrival_time": inputs.decision_time + pd.Timedelta(minutes=10)})

    error = score(rows, metadata, Predictor())
    assert error[0] == -10 and np.isnan(error[1])

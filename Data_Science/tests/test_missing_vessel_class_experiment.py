"""Coverage loss cannot be hidden by conditional accuracy metrics."""

import numpy as np
import pandas as pd
import pytest

from experiments.missing_vessel_class_attack.run import score_inputs, summarize


def example_inputs() -> pd.DataFrame:
    return pd.DataFrame({
        "approach_id": ["a", "b"], "mmsi": ["111111111", "222222222"],
        "decision_id": ["one", "two"], "decision_time": pd.Timestamp("2024-04-10"),
        "arrival_time": pd.Timestamp("2024-04-10 00:30"),
        "observation_time": [pd.Timestamp("2024-04-10"), pd.NaT],
        "available": [True, False], "eligible_reports_so_far": [1, 0],
    })


class SupportedPredictor:
    def predict(self, frame: pd.DataFrame) -> pd.DataFrame:
        assert frame.available.all()
        return frame.assign(error_minutes=2.,
                            predicted_arrival_time=frame.arrival_time+pd.Timedelta(minutes=2),
                            report_age_minutes=0.)


def test_accuracy_compares_only_the_same_supported_decisions():
    reference = pd.Series({"one": 1., "two": 100.})
    result = score_inputs(SupportedPredictor(), example_inputs(), reference, "A", "vessel", .5, 4201)
    row = summarize(result)
    assert row["coverage"] == .5
    assert row["missing_forecasts"] == 1
    assert row["mae_minutes"] == 2.
    assert row["matched_original_mae_minutes"] == 1.
    assert row["full_original_mae_minutes"] == 50.5
    assert row["mae_change_on_supported_minutes"] == 1.
    assert pd.isna(result.loc[1, "error_minutes"])


def test_full_exclusion_has_undefined_error_and_never_calls_the_model():
    class ForbiddenPredictor:
        def predict(self, frame):
            pytest.fail("An empty eligible history must not be imputed into a forecast.")

    inputs = example_inputs().assign(available=False, eligible_reports_so_far=0, observation_time=pd.NaT)
    result = score_inputs(ForbiddenPredictor(), inputs, pd.Series({"one": 1., "two": 100.}),
                          "A", "vessel", 1., 4201)
    row = summarize(result)
    assert row["coverage"] == 0.
    assert row["missing_forecasts"] == 2
    assert np.isnan(row["mae_minutes"]) and np.isnan(row["mdae_minutes"])
    assert np.isnan(row["mae_change_on_supported_minutes"])
    assert result.predicted_arrival_time.isna().all()

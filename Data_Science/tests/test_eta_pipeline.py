"""Protect causal features, reference labels and fair ETA comparisons."""

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor
from sklearn.impute import SimpleImputer

from eta_baselines.approaches import ApproachBuilder, crossing_time
from eta_baselines.configuration import FeatureConfig, GateConfig, SplitConfig
from eta_baselines.dataset import assign_splits
from eta_baselines.evaluation import approach_weights
from eta_baselines.features import FEATURE_COLUMNS, FeatureBuilder
from eta_baselines.prediction import EtaPredictor


@pytest.fixture
def gate() -> GateConfig:
    return GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6)


def reports(longitudes: list[float], start: str = "2024-03-05 12:00") -> pd.DataFrame:
    return pd.DataFrame({
        "mmsi": "123456789",
        "time": pd.date_range(start, periods=len(longitudes), freq="1min"),
        "longitude": longitudes, "latitude": 37.0,
        "sog": 10.0, "cog": 270.0, "vessel_type": 70,
    })


def test_crossing_is_interpolated_only_for_inbound_short_brackets(gate: GateConfig) -> None:
    track = reports([-76.29, -76.31])
    arrival = crossing_time(track.iloc[0], track.iloc[1], gate)
    assert arrival is not None
    assert abs(arrival - pd.Timestamp("2024-03-05 12:00:30")) < pd.Timedelta(microseconds=1)
    assert crossing_time(track.iloc[1], track.iloc[0], gate) is None
    track.loc[1, "time"] += pd.Timedelta(minutes=10)
    assert crossing_time(track.iloc[0], track.iloc[1], gate) is None


def test_crossing_outside_gate_latitudes_is_not_an_arrival(gate: GateConfig) -> None:
    track = reports([-76.29, -76.31])
    track["latitude"] = 37.2
    assert crossing_time(track.iloc[0], track.iloc[1], gate) is None


def test_stationary_reports_are_not_arrivals(gate: GateConfig) -> None:
    track = reports([-76.2] * 20)
    track["sog"] = 0.0
    approaches, audit = ApproachBuilder(gate).build(track)
    assert not approaches
    assert audit["unresolved_episodes"] == 1


def test_future_report_cannot_change_earlier_features(gate: GateConfig) -> None:
    builder = FeatureBuilder(gate, FeatureConfig(10, 5, 10))
    track = reports([-76.2, -76.21, -76.22])
    decision = track["time"].iloc[1]
    earlier = builder.snapshot(track.iloc[:2], decision)
    track.loc[2, ["longitude", "sog"]] = [-75.0, 90.0]
    pd.testing.assert_frame_equal(earlier, builder.snapshot(track, decision))


def test_cross_partition_approach_is_purged_including_reference_bracket() -> None:
    examples = pd.DataFrame({
        "episode_start": pd.to_datetime(["2024-03-19 23:00", "2024-03-20 00:01"]),
        "crossing_after": pd.to_datetime(["2024-03-20 00:01", "2024-03-20 00:30"]),
    })
    config = SplitConfig("2024-03-01", "2024-03-20", "2024-03-25", "2024-04-01")
    assert assign_splits(examples, config)["split"].tolist() == ["purged", "validation"]


def test_each_approach_has_equal_total_weight() -> None:
    examples = pd.DataFrame({"approach_id": ["a", "a", "a", "b"]})
    weights = pd.Series(approach_weights(examples))
    totals = weights.groupby(examples["approach_id"]).sum()
    assert totals["a"] == pytest.approx(totals["b"])


def test_old_duration_is_anchored_to_observation_not_decision_clock() -> None:
    features = pd.DataFrame([{column: 1.0 for column in FEATURE_COLUMNS}])
    imputer = SimpleImputer().fit(features)
    regressor = DummyRegressor(strategy="constant", constant=40).fit(imputer.transform(features), [40])
    predictor = EtaPredictor("test", imputer, regressor)
    features["observation_time"] = pd.Timestamp("2024-03-05 11:50")
    features["decision_time"] = pd.Timestamp("2024-03-05 12:00")
    prediction = predictor.predict(features).iloc[0]
    assert prediction["predicted_arrival_time"] == pd.Timestamp("2024-03-05 12:30")
    assert prediction["predicted_remaining_minutes"] == 30
    features["observation_time"] = pd.Timestamp("2024-03-05 12:01")
    with pytest.raises(ValueError, match="later than decision"):
        predictor.predict(features)


def test_missing_motion_inputs_remain_missing_until_training_imputation(gate: GateConfig) -> None:
    track = reports([-76.2])
    track.loc[0, ["sog", "cog"]] = np.nan
    values = FeatureBuilder(gate, FeatureConfig(10, 5, 10)).summarize(track)
    assert np.isnan(values["speed_knots"])
    assert np.isnan(values["course_sin"])
    assert values["history_missing"] == 1

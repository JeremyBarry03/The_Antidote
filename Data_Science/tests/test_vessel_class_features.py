"""Unknown vessel class must remain distinct through saved-model preprocessing."""

import json
from dataclasses import replace
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor

from eta_baselines.configuration import ExperimentConfig
from eta_baselines.features import (FEATURE_COLUMNS, LEGACY_FEATURE_COLUMNS, VESSEL_CLASS_COLUMNS,
                                   FeatureBuilder, vessel_class_features)
from eta_baselines.fitting import fit_imputer
from eta_baselines.prediction import EtaPredictor
from eta_baselines.training import load_examples


@pytest.mark.parametrize("value, expected", [
    (70, (1., 0., 0.)), (79., (1., 0., 0.)),
    (80, (0., 1., 0.)), (89., (0., 1., 0.)),
    (np.nan, (0., 0., 1.)), (None, (0., 0., 1.)), (pd.NA, (0., 0., 1.)),
    (0, (0., 0., 1.)), (60, (0., 0., 1.)), (70.5, (0., 0., 1.)),
    (np.inf, (0., 0., 1.)), (True, (0., 0., 1.)),
])
def test_class_states_are_explicit_and_mutually_exclusive(value, expected):
    encoded = vessel_class_features(value)
    assert tuple(encoded[column] for column in VESSEL_CLASS_COLUMNS) == expected
    assert sum(encoded.values()) == 1.


def snapshots() -> pd.DataFrame:
    rows = []
    for value in (70., 80., np.nan):
        row = {column: 1. for column in FEATURE_COLUMNS}
        row.update(vessel_class_features(value))
        row.update(observation_time=pd.Timestamp("2024-04-10 12:00"),
                   decision_time=pd.Timestamp("2024-04-10 12:05"))
        rows.append(row)
    return pd.DataFrame(rows)


def test_unknown_remains_distinct_after_imputer_fitted_on_known_classes_only(tmp_path):
    frame = snapshots()
    imputer = fit_imputer(frame.iloc[:2], FEATURE_COLUMNS)
    transformed = imputer.transform(frame[list(FEATURE_COLUMNS)])
    positions = [FEATURE_COLUMNS.index(column) for column in VESSEL_CLASS_COLUMNS]
    np.testing.assert_array_equal(transformed[:, positions], np.eye(3))
    regressor = DummyRegressor().fit(transformed[:2], [20., 40.])
    predictor = EtaPredictor("test", imputer, regressor)
    path = tmp_path/"model.joblib"
    joblib.dump(predictor, path)
    restored = joblib.load(path)
    assert restored.feature_columns == FEATURE_COLUMNS
    assert len(restored.predict(frame)) == 3
    with pytest.raises(ValueError, match="vessel_class_unknown"):
        restored.predict(frame.drop(columns="vessel_class_unknown"))


def test_legacy_bundle_recovers_its_fitted_schema_instead_of_new_defaults(tmp_path):
    frame = snapshots()
    imputer = fit_imputer(frame, LEGACY_FEATURE_COLUMNS)
    regressor = DummyRegressor(strategy="constant", constant=20.).fit(
        imputer.transform(frame[list(LEGACY_FEATURE_COLUMNS)]), [20.] * len(frame))
    predictor = EtaPredictor("legacy", imputer, regressor, LEGACY_FEATURE_COLUMNS)
    del predictor.__dict__["feature_columns"]
    del predictor.__dict__["target_clock"]
    path = tmp_path/"legacy.joblib"
    joblib.dump(predictor, path)
    restored = joblib.load(path)
    assert restored.feature_columns == LEGACY_FEATURE_COLUMNS
    result = restored.predict(frame).iloc[0]
    assert result.predicted_arrival_time == pd.Timestamp("2024-04-10 12:20")
    assert result.predicted_remaining_minutes == 15.


def test_future_class_does_not_backfill_current_unknown_or_mutate_reports():
    config = ExperimentConfig.load(Path(__file__).resolve().parents[1]/"config.json")
    builder = FeatureBuilder(config.gate, config.features)
    reports = pd.DataFrame(dict(time=pd.date_range("2024-04-10", periods=2, freq="min"),
        longitude=-76.1, latitude=37., sog=10., cog=270., vessel_type=[np.nan, 80.]))
    original = reports.copy(deep=True)
    earlier = builder.snapshot(reports, reports.time.iloc[0]).iloc[0]
    assert earlier.vessel_class_unknown == 1. and earlier.is_cargo == earlier.is_tanker == 0.
    later = builder.snapshot(reports, reports.time.iloc[1]).iloc[0]
    assert later.vessel_class_unknown == 0. and later.is_tanker == 1.
    pd.testing.assert_frame_equal(reports, original)


def test_training_rejects_prepared_examples_with_the_old_feature_schema(tmp_path):
    config = ExperimentConfig.load(Path(__file__).resolve().parents[1]/"config.json")
    config = replace(config, output_directory=tmp_path)
    (tmp_path/"examples.csv").write_text("old_feature\n", encoding="utf-8")
    config.save(tmp_path/"config_snapshot.json")
    (tmp_path/"data_manifest.json").write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema is outdated"):
        load_examples(config)

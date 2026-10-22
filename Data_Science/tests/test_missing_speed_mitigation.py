"""Causal motion reconstruction and frozen-C feature contract tests."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from eta_baselines.configuration import GateConfig, FeatureConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import BaseMitigation
from mitigation.missing_speed_mitigation import MissingSpeedConfig, MissingSpeedMitigation, SpeedStatus
from mitigation.missing_speed_mitigation.optimized_model import SPEED_FEATURES, missing_speed_snapshot
from Optimized_Model.configuration import GuardConfig
from Optimized_Model.features import OptimizedFeatures


@pytest.fixture
def mitigation():
    return MissingSpeedMitigation(GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6))


@pytest.fixture
def reports():
    speed = 12 * KNOTS_TO_METERS_PER_SECOND
    east = np.arange(8) * 60 * speed
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-09 12:00", periods=8, freq="min"),
                         "latitude": 37., "longitude": -76.2 + east / (METERS_PER_DEGREE * np.cos(np.deg2rad(37))),
                         "sog": np.nan, "cog": 90., "vessel_type": 70})


@pytest.fixture
def extractor(mitigation):
    baseline = SimpleNamespace(gate=mitigation.gate, features=FeatureConfig(10, 5, 10))
    return OptimizedFeatures(baseline, GuardConfig(60, 60, 500, 300))


def test_linear_motion_recovers_twelve_knots_and_real_clock(mitigation, reports):
    assert isinstance(mitigation, BaseMitigation)
    result = mitigation.apply(reports, "2024-04-09 12:09")
    assert result.status == SpeedStatus.ESTIMATED and result.estimated_sog == pytest.approx(12)
    assert result.observation_time == reports.time.max() and result.report_age_minutes == 2
    assert result.used_reports == 6 and result.fit_residual_meters < 1e-6
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(mitigation.parameters, allow_nan=False)


def test_stationary_motion_can_estimate_zero(mitigation, reports):
    stationary = reports.assign(longitude=-76.2)
    result = mitigation.apply(stationary, reports.time.max())
    assert result.status == SpeedStatus.ESTIMATED and result.estimated_sog == pytest.approx(0, abs=1e-8)


@pytest.mark.parametrize("speed", [0., 12., 102.2])
def test_valid_speeds_including_zero_remain_observed(mitigation, reports, speed):
    reports = reports.assign(sog=speed)
    original = reports.copy(deep=True)
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == SpeedStatus.OBSERVED and result.original_sog == speed
    assert result.estimated_sog is None
    repair = mitigation.repair_reports(reports, reports.time.max())
    assert not repair.audit
    pd.testing.assert_frame_equal(repair.reports, original)
    pd.testing.assert_frame_equal(reports, original)


@pytest.mark.parametrize("speed", [102.3, -1., float("inf")])
def test_invalid_speed_is_not_treated_as_observed(mitigation, reports, speed):
    result = mitigation.apply(reports.assign(sog=speed), reports.time.max())
    assert result.status == SpeedStatus.ESTIMATED
    assert result.estimated_sog == pytest.approx(12)


def test_repairs_are_per_observation_and_only_sog_changes(mitigation, reports):
    original = reports.copy(deep=True)
    repair = mitigation.repair_reports(reports, reports.time.max())
    assert len(repair.audit) == len(reports)
    assert repair.reports.sog.iloc[:2].isna().all()
    assert np.allclose(repair.reports.sog.iloc[2:], 12)
    pd.testing.assert_frame_equal(repair.reports.drop(columns="sog"), original.drop(columns="sog"))
    pd.testing.assert_frame_equal(reports, original)


def test_future_reports_and_hidden_truth_cannot_change_estimates(mitigation, reports):
    clock = reports.time.iloc[4]
    expected = mitigation.repair_reports(reports.head(5), clock)
    changed = reports.assign(arrival_time="hidden", original_sog=1000, fault_applied=True)
    changed.loc[changed.time.gt(clock), "longitude"] += 10
    actual = mitigation.repair_reports(changed, clock)
    np.testing.assert_allclose(actual.reports.sog, expected.reports.sog, equal_nan=True)
    assert actual.audit == expected.audit


def test_later_fixes_never_backfill_earlier_speed(mitigation, reports):
    full = mitigation.repair_reports(reports, reports.time.max())
    short = mitigation.repair_reports(reports.head(4), reports.time.iloc[3])
    pd.testing.assert_series_equal(full.reports.sog.head(4), short.reports.sog)


def test_shuffle_and_exact_duplicates_do_not_change_speed(mitigation, reports):
    expected = mitigation.apply(reports, reports.time.max())
    repeated = pd.concat([reports, reports]).sample(frac=1, random_state=7)
    assert mitigation.apply(repeated, reports.time.max()) == expected


def test_conflicting_timestamp_rejects_fit(mitigation, reports):
    conflict = reports.tail(1).assign(longitude=-76.1)
    result = mitigation.apply(pd.concat([reports, conflict]), reports.time.max())
    assert result.status == SpeedStatus.UNSUPPORTED
    assert "discontinuous_or_conflicting_positions" in result.reasons


def test_short_sparse_missing_or_jumping_positions_are_unsupported(mitigation, reports):
    cases = [reports.head(2), reports.assign(latitude=np.nan),
             reports.assign(time=pd.date_range("2024-04-09 12:00", periods=8, freq="3min")),
             reports.assign(longitude=reports.longitude + np.r_[np.zeros(7), .1]),
             reports.assign(time=pd.date_range("2024-04-09 12:00", periods=8, freq="s"))]
    for frame in cases:
        result = mitigation.apply(frame, frame.time.max())
        assert result.status == SpeedStatus.UNSUPPORTED and result.estimated_sog is None


def test_turning_or_accelerating_track_is_rejected(mitigation, reports):
    changed = reports.copy()
    changed.loc[changed.index[-2:], "latitude"] += [.001, .003]
    assert mitigation.apply(changed, changed.time.max()).status == SpeedStatus.UNSUPPORTED


def test_late_positions_not_used_before_delivery(mitigation, reports):
    delayed = reports.assign(delivered_time=reports.time)
    delayed.loc[:4, "delivered_time"] = pd.Timestamp("2024-04-09 12:20")
    result = mitigation.repair_reports(delayed, "2024-04-09 12:06")
    assert result.reports.sog.isna().all()


def test_empty_input_nullable_speed_and_integer_speed(mitigation, reports):
    assert mitigation.apply(reports.iloc[:0], reports.time.max()).status == SpeedStatus.NO_REPORTS
    assert mitigation.repair_reports(reports.iloc[:0], reports.time.max()).reports.empty
    nullable = reports.assign(sog=pd.Series([pd.NA] * len(reports), dtype="Float64"))
    assert mitigation.apply(nullable, reports.time.max()).status == SpeedStatus.ESTIMATED
    assert mitigation.apply(reports.assign(sog=12), reports.time.max()).status == SpeedStatus.OBSERVED


def test_multiple_vessels_and_bad_clock_rejected(mitigation, reports):
    with pytest.raises(ValueError, match="one vessel"):
        mitigation.apply(pd.concat([reports, reports.assign(mmsi="other")]), reports.time.max())
    with pytest.raises(ValueError):
        mitigation.apply(reports, "invalid")


@pytest.mark.parametrize("configuration", [{"minimum_reports": 2}, {"maximum_gap_seconds": 0},
    {"history_minutes": float("nan")}, {"maximum_speed_knots": 103}, {"minimum_reports": True},
    {"minimum_span_seconds": 301}, {"maximum_velocity_deviation_knots": -1}])
def test_invalid_config_rejected(configuration):
    with pytest.raises(ValueError):
        MissingSpeedConfig(**configuration)


def test_adapter_changes_only_speed_features_preserving_missingness_and_clocks(mitigation, reports, extractor):
    snapshot = missing_speed_snapshot(reports, reports.time.max(), extractor, mitigation)
    assert snapshot.mitigated_features.speed_knots.iloc[0] == pytest.approx(12)
    assert snapshot.original_features.speed_knots.isna().all()
    assert snapshot.mitigated_features.missing_speed_fraction.iloc[0] == 1
    for name in snapshot.original_features:
        if name not in SPEED_FEATURES:
            pd.testing.assert_series_equal(snapshot.original_features[name], snapshot.mitigated_features[name])
    assert not {"estimated_sog", "fault_applied", "original_sog", "arrival_time"} & set(snapshot.mitigated_features)


def test_adapter_clean_feed_is_exact_identity(mitigation, reports, extractor):
    snapshot = missing_speed_snapshot(reports.assign(sog=12.), reports.time.max(), extractor, mitigation)
    pd.testing.assert_frame_equal(snapshot.original_features, snapshot.mitigated_features)


def test_adapter_unsupported_estimate_keeps_existing_imputation_path(mitigation, reports, extractor):
    snapshot = missing_speed_snapshot(reports.head(2), reports.time.iloc[1], extractor, mitigation)
    pd.testing.assert_frame_equal(snapshot.original_features, snapshot.mitigated_features)
    snapshot = missing_speed_snapshot(reports.iloc[:0], reports.time.max(), extractor, mitigation)
    assert snapshot.original_features.empty and snapshot.mitigated_features.empty


def test_adapter_gate_mismatch_rejected(mitigation, reports, extractor):
    with pytest.raises(ValueError, match="geographic"):
        missing_speed_snapshot(reports, reports.time.max(), extractor,
                               replace(mitigation, gate=replace(mitigation.gate, longitude=-76.4)))

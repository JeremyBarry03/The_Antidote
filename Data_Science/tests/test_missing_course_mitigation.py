"""Circular course reconstruction, causal repair, and frozen-C feature boundaries."""

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from eta_baselines.configuration import FeatureConfig, GateConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import BaseMitigation
from mitigation.missing_course_mitigation import CourseStatus, MissingCourseConfig, MissingCourseMitigation
from mitigation.missing_course_mitigation.optimized_model import COURSE_FEATURES, missing_course_snapshot
from Optimized_Model.configuration import GuardConfig
from Optimized_Model.features import OptimizedFeatures


def track(degrees=90., speed_knots=12., count=8):
    direction = np.broadcast_to(degrees, count - 1)
    step = speed_knots * KNOTS_TO_METERS_PER_SECOND * 60
    east = np.r_[0, np.cumsum(step * np.sin(np.deg2rad(direction)))]
    north = np.r_[0, np.cumsum(step * np.cos(np.deg2rad(direction)))]
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-09 12:00", periods=count, freq="min"),
        "latitude": 37. + north / METERS_PER_DEGREE,
        "longitude": -76.2 + east / (METERS_PER_DEGREE * np.cos(np.deg2rad(37))),
        "sog": speed_knots, "cog": np.nan, "vessel_type": 70})


@pytest.fixture
def mitigation():
    return MissingCourseMitigation(GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6))


@pytest.fixture
def extractor(mitigation):
    baseline = SimpleNamespace(gate=mitigation.gate, features=FeatureConfig(10, 5, 10))
    return OptimizedFeatures(baseline, GuardConfig(60, 60, 500, 300))


@pytest.mark.parametrize("degrees", [0., 45., 90., 180., 270., 359.])
def test_nautical_bearing_from_velocity(mitigation, degrees):
    reports = track(degrees)
    result = mitigation.apply(reports, "2024-04-09 12:09")
    assert isinstance(mitigation, BaseMitigation)
    assert result.status == CourseStatus.ESTIMATED
    assert 0 <= result.estimated_cog < 360
    assert abs((result.estimated_cog - degrees + 180) % 360 - 180) < 1e-6
    assert result.report_age_minutes == 2 and result.observation_time == reports.time.max()
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(mitigation.parameters, allow_nan=False)


def test_wraparound_north_does_not_become_south(mitigation):
    reports = track(np.array([359., 1., 359., 1., 359., 1., 359.]))
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == CourseStatus.ESTIMATED
    assert abs((result.estimated_cog + 180) % 360 - 180) < 1
    assert result.maximum_direction_deviation_degrees < 2


@pytest.mark.parametrize("degrees", [0., 1., 270., 359.9])
def test_valid_course_including_north_is_untouched(mitigation, degrees):
    reports = track().assign(cog=degrees)
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == CourseStatus.OBSERVED and result.estimated_cog is None
    pd.testing.assert_frame_equal(mitigation.repair_reports(reports, reports.time.max()).reports, reports)


@pytest.mark.parametrize("degrees", [360., 361., -1., float("inf")])
def test_unavailable_course_is_not_normalized_into_valid_north(mitigation, degrees):
    reports = track().assign(cog=degrees)
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == CourseStatus.ESTIMATED and result.estimated_cog == pytest.approx(90)


@pytest.mark.parametrize("speed", [0., .4])
def test_stationary_or_slow_track_stays_unknown(mitigation, speed):
    reports = track(speed_knots=speed)
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == CourseStatus.UNSUPPORTED and result.estimated_cog is None
    assert "insufficient_motion_for_course" in result.reasons
    assert mitigation.repair_reports(reports, reports.time.max()).reports.cog.isna().all()


def test_direction_consistency_adds_protection_beyond_speed_checks(mitigation):
    reports = track(np.array([25., 335., 25., 335., 25., 335., 25.]), speed_knots=1.5)
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == CourseStatus.UNSUPPORTED
    assert "inconsistent_recent_direction" in result.reasons


def test_minimum_displacement_is_independently_enforced(mitigation):
    reports = track()
    strict = replace(mitigation, config=MissingCourseConfig(minimum_displacement_meters=10000))
    assert "insufficient_displacement_for_course" in strict.apply(reports, reports.time.max()).reasons


def test_repair_only_changes_course_and_never_backfills_with_future_fixes(mitigation):
    reports = track()
    before = reports.copy(deep=True)
    full = mitigation.repair_reports(reports, reports.time.max())
    short = mitigation.repair_reports(reports.head(4), reports.time.iloc[3])
    assert full.reports.cog.iloc[:2].isna().all()
    assert np.allclose(full.reports.cog.iloc[2:], 90)
    pd.testing.assert_series_equal(full.reports.cog.head(4), short.reports.cog)
    pd.testing.assert_frame_equal(full.reports.drop(columns="cog"), reports.drop(columns="cog"))
    pd.testing.assert_frame_equal(reports, before)


def test_future_reports_audit_labels_shuffle_and_duplicates_are_irrelevant(mitigation):
    reports = track()
    expected = mitigation.apply(reports.head(5), reports.time.iloc[4])
    changed = pd.concat([reports, reports]).sample(frac=1, random_state=42)
    changed = changed.assign(original_cog=180., fault_applied=True, arrival_time="hidden")
    assert mitigation.apply(changed, reports.time.iloc[4]) == expected


def test_late_delivery_and_conflicting_positions_are_rejected(mitigation):
    reports = track()
    late = reports.assign(delivered_time=reports.time)
    late.loc[:4, "delivered_time"] = pd.Timestamp("2024-04-09 12:20")
    assert mitigation.repair_reports(late, "2024-04-09 12:06").reports.cog.isna().all()
    conflict = pd.concat([reports, reports.tail(1).assign(longitude=-76.1)])
    assert "discontinuous_or_conflicting_positions" in mitigation.apply(conflict, reports.time.max()).reasons


def test_invalid_sparse_gappy_and_jumping_positions_are_unsupported(mitigation):
    reports = track()
    frames = [reports.head(2), reports.assign(latitude=np.nan),
        reports.assign(latitude=pd.Series([pd.NA] * len(reports), dtype="Float64")),
        reports.assign(time=pd.date_range("2024-04-09 12:00", periods=8, freq="3min")),
        reports.assign(longitude=reports.longitude + np.r_[np.zeros(7), .1]),
        reports.assign(time=pd.date_range("2024-04-09 12:00", periods=8, freq="s"))]
    for frame in frames:
        assert mitigation.apply(frame, frame.time.max()).status == CourseStatus.UNSUPPORTED


def test_empty_nullable_integer_and_missing_speed_inputs(mitigation):
    reports = track()
    assert mitigation.apply(reports.iloc[:0], reports.time.max()).status == CourseStatus.NO_REPORTS
    assert mitigation.repair_reports(reports.iloc[:0], reports.time.max()).reports.empty
    assert mitigation.apply(reports.assign(cog=0), reports.time.max()).status == CourseStatus.OBSERVED
    nullable = reports.assign(cog=pd.Series([pd.NA] * len(reports), dtype="Float64"), sog=np.nan)
    assert mitigation.apply(nullable, reports.time.max()).status == CourseStatus.ESTIMATED


@pytest.mark.parametrize("config", [{"minimum_reports": 2}, {"minimum_speed_knots": 0},
    {"minimum_speed_knots": 60}, {"minimum_displacement_meters": float("nan")},
    {"maximum_direction_deviation_degrees": 181}, {"maximum_gap_seconds": -1},
    {"minimum_reports": True}, {"minimum_span_seconds": 301}])
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        MissingCourseConfig(**config)


def test_invalid_clock_multiple_vessels_or_unparsed_measurements_rejected(mitigation):
    reports = track()
    with pytest.raises(ValueError):
        mitigation.apply(reports, "invalid")
    with pytest.raises(ValueError, match="one vessel"):
        mitigation.apply(pd.concat([reports, reports.assign(mmsi="other")]), reports.time.max())
    with pytest.raises(ValueError):
        mitigation.apply(reports.assign(cog="invalid"), reports.time.max())


def test_adapter_only_changes_course_features_preserving_observed_missingness(mitigation, extractor):
    reports = track()
    snapshot = missing_course_snapshot(reports, reports.time.max(), extractor, mitigation)
    assert snapshot.original_features.course_sin.isna().all()
    assert snapshot.mitigated_features.course_sin.iloc[0] == pytest.approx(1)
    assert snapshot.mitigated_features.course_cos.iloc[0] == pytest.approx(0, abs=1e-8)
    assert snapshot.mitigated_features.missing_course_fraction.iloc[0] == 1
    for name in snapshot.original_features:
        if name not in COURSE_FEATURES:
            pd.testing.assert_series_equal(snapshot.original_features[name], snapshot.mitigated_features[name])
    assert not {"arrival_time", "original_cog", "fault_applied", "estimated_cog"} & set(snapshot.mitigated_features)


def test_clean_and_unsupported_adapters_are_identity(mitigation, extractor):
    for reports in (track().assign(cog=90.), track(speed_knots=0), track().head(2), track().iloc[:0]):
        snapshot = missing_course_snapshot(reports, pd.Timestamp("2024-04-09 12:07"), extractor, mitigation)
        pd.testing.assert_frame_equal(snapshot.original_features, snapshot.mitigated_features)


def test_adapter_never_turns_unavailable_course_into_north(mitigation, extractor):
    reports = track(speed_knots=0).assign(cog=360.)
    snapshot = missing_course_snapshot(reports, reports.time.max(), extractor, mitigation)
    assert snapshot.original_features.course_sin.isna().all()
    assert snapshot.mitigated_features.course_cos.isna().all()
    assert snapshot.mitigated_features.missing_course_fraction.iloc[0] == 1
    assert reports.cog.eq(360).all()


def test_adapter_rejects_different_geographic_reference(mitigation, extractor):
    with pytest.raises(ValueError, match="geographic"):
        missing_course_snapshot(track(), pd.Timestamp("2024-04-09 12:07"), extractor,
            replace(mitigation, gate=replace(mitigation.gate, longitude=-76.4)))

"""Received-only sensor-noise detection, field reconstruction and provenance."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import BaseMitigation, SensorNoiseConfig, SensorNoiseMitigation, SensorNoiseStatus


@pytest.fixture
def mitigation():
    return SensorNoiseMitigation(GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6))


def track(speed: float = 10., course: float = 270.) -> pd.DataFrame:
    distance = np.arange(7) * 60 * speed * KNOTS_TO_METERS_PER_SECOND
    radians = np.deg2rad(course)
    return pd.DataFrame({
        "mmsi": "123456789", "time": pd.date_range("2024-03-05 12:00", periods=7, freq="min"),
        "longitude": -76.15 + distance * np.sin(radians) / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.))),
        "latitude": 37. + distance * np.cos(radians) / METERS_PER_DEGREE,
        "sog": speed, "cog": course, "vessel_type": 70,
    })


def test_contract_clean_feed_and_strict_json(mitigation):
    reports = track()
    original = reports.copy(deep=True)
    result = mitigation.apply(reports, reports.time.max())
    assert isinstance(mitigation, BaseMitigation)
    assert result.status == SensorNoiseStatus.NORMAL and result.can_predict
    assert not result.anomaly_detected and not result.requires_review
    assert result.speed_source == result.course_source == "reported"
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(mitigation.parameters, allow_nan=False)
    pd.testing.assert_frame_equal(reports, original)


@pytest.mark.parametrize("speed,course,sources", [(20., 210., ("estimated", "estimated")),
                                                  (20., 270., ("estimated", "reported")),
                                                  (10., 210., ("reported", "estimated"))])
def test_reconstructs_only_inconsistent_sensor_fields(mitigation, speed, course, sources):
    reports = track()
    reports.loc[6, ["sog", "cog"]] = [speed, course]
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == SensorNoiseStatus.RECONSTRUCTED
    assert result.anomaly_detected and result.can_predict and result.position_supported
    assert (result.speed_source, result.course_source) == sources
    assert result.speed_knots == pytest.approx(10.)
    assert result.course_degrees == pytest.approx(270.)


def test_circle_boundary_is_not_a_course_jump(mitigation):
    reports = track(course=359.)
    reports.loc[6, "cog"] = 1.
    result = mitigation.apply(reports, reports.time.max())
    assert result.status == SensorNoiseStatus.NORMAL
    assert result.course_difference_degrees == pytest.approx(2.)
    assert result.course_degrees == 1.


def test_stationary_history_does_not_invent_direction_or_flag_course_noise(mitigation):
    reports = track(speed=0.).assign(cog=np.nan)
    result = mitigation.apply(reports, reports.time.max())
    assert result.can_predict and not result.course_suspect
    assert result.estimated_speed_knots == pytest.approx(0.)
    assert result.estimated_course_degrees is None and result.course_degrees is None
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("field,value", [("sog", np.nan), ("sog", 102.3), ("sog", -1.),
                                         ("sog", np.inf), ("cog", np.nan), ("cog", 360.)])
def test_missing_field_attacks_and_sentinels_are_not_noise_repaired(mitigation, field, value):
    reports = track()
    reports.loc[6, field] = value
    result = mitigation.apply(reports, reports.time.max())
    assert result.requires_review and not result.can_predict
    assert result.speed_source != "estimated" and result.course_source != "estimated"
    json.dumps(result.to_dict(), allow_nan=False)


def test_large_positive_noise_is_not_silently_clipped_to_encoding_limit(mitigation):
    reports = track()
    reports.loc[6, "sog"] = 120.
    result = mitigation.apply(reports, reports.time.max())
    assert result.speed_suspect and result.speed_knots == pytest.approx(10.)


def test_rejects_bad_or_maneuvering_position_reference(mitigation):
    for field, value in (("longitude", np.nan), ("latitude", 100.), ("longitude", -75.)):
        reports = track()
        reports.loc[6, ["sog", "cog"]] = [20., 210.]
        reports.loc[6, field] = value
        result = mitigation.apply(reports, reports.time.max())
        assert result.requires_review and not result.position_supported
        assert result.speed_source == result.course_source == "reported"
    turning = track()
    turning.loc[6, "latitude"] += .002
    assert mitigation.apply(turning, turning.time.max()).requires_review


def test_warmup_staleness_and_gaps_require_review(mitigation):
    reports = track()
    assert mitigation.apply(reports.head(2), reports.time.iloc[1]).status == SensorNoiseStatus.WARMING_UP
    assert mitigation.apply(reports.iloc[:0], reports.time.max()).status == SensorNoiseStatus.NO_REPORTS
    assert mitigation.apply(reports, reports.time.max() + pd.Timedelta(minutes=6)).requires_review
    gap = reports.assign(time=pd.date_range("2024-03-05 12:00", periods=7, freq="4min"))
    wider = replace(mitigation, config=replace(mitigation.config, window_minutes=15))
    assert wider.apply(gap, gap.time.max()).reasons == ("position_history_gap",)


def test_future_undelivered_duplicates_order_and_attack_truth_do_not_influence_result(mitigation):
    reports = track().assign(sog=20., cog=210.)
    clock = reports.time.iloc[4]
    expected = mitigation.apply(reports.head(5), clock).to_dict()
    changed = pd.concat([reports, reports], ignore_index=True).sample(frac=1, random_state=4)
    changed["fault_applied"], changed["original_sog"], changed["arrival_time"] = True, -999, "hidden"
    assert mitigation.apply(changed, clock).to_dict() == expected
    delayed = reports.assign(delivered_time=reports.time)
    delayed.loc[5:, "delivered_time"] += pd.Timedelta(hours=1)
    assert mitigation.apply(delayed, clock).to_dict() == expected
    recent_bad = reports.head(5).assign(delivered_time=reports.time.head(5))
    with pytest.raises(ValueError):
        mitigation.apply(recent_bad, clock, latest_received_time=clock + pd.Timedelta(seconds=1))


def test_conflicting_same_time_values_do_not_fake_support(mitigation):
    reports = track()
    conflict = reports.tail(1).assign(longitude=-76.)
    result = mitigation.apply(pd.concat([reports, conflict]), reports.time.max())
    assert result.reasons == ("conflicting_same_time_reports",) and result.requires_review


def test_reconstruction_is_a_private_causal_copy_and_preserves_non_sensor_fields(mitigation):
    reports = track().assign(sog=20., cog=210.)
    original = reports.copy(deep=True)
    short, _ = mitigation.reconstruct_reports(reports.head(5), reports.time.iloc[4])
    full, result = mitigation.reconstruct_reports(reports, reports.time.max())
    pd.testing.assert_frame_equal(short, full.head(5))
    pd.testing.assert_frame_equal(reports, original)
    pd.testing.assert_frame_equal(full.drop(columns=["sog", "cog"]), original.drop(columns=["sog", "cog"]))
    assert full.sog.iloc[:2].eq(20.).all()  # Warmup never borrows future positions.
    assert np.allclose(full.sog.iloc[2:], 10.) and np.allclose(full.cog.iloc[2:], 270.)
    assert result.anomaly_detected  # Repairs never erase evidence in current raw diagnostics.


def test_delayed_arrival_cannot_backfill_earlier_reconstructions(mitigation):
    reports = track().assign(sog=20., delivered_time=lambda frame: frame.time)
    reports.loc[0, "delivered_time"] = reports.time.iloc[6]
    first, _ = mitigation.reconstruct_reports(reports.head(5), reports.time.iloc[4])
    later, _ = mitigation.reconstruct_reports(reports, reports.time.max())
    pd.testing.assert_frame_equal(first, later.loc[later.time.isin(first.time)].reset_index(drop=True))


@pytest.mark.parametrize("settings", [{"minimum_reports": 2}, {"minimum_reports": True},
    {"window_minutes": 0}, {"speed_difference_knots": float("nan")},
    {"course_difference_degrees": 181}, {"maximum_gap_seconds": float("inf")},
    {"minimum_span_seconds": 400}, {"maximum_fit_residual_meters": -1}])
def test_invalid_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        SensorNoiseConfig(**settings)


def test_invalid_input_and_vessel_mixing_are_rejected(mitigation):
    reports = track()
    for frame in (reports.assign(sog="bad"), reports.assign(time="bad"),
                  reports.assign(delivered_time=reports.time - pd.Timedelta(seconds=1)),
                  pd.concat([reports, reports.assign(mmsi="987654321")])):
        with pytest.raises(ValueError):
            mitigation.apply(frame, reports.time.max())
    with pytest.raises(ValueError):
        mitigation.apply(reports, "bad")

"""Position warnings use received evidence and never supply model inputs."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from api.anamoly_detector import AnomalyDetector
from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import BaseMitigation, GapMitigation
from mitigation.position_jump_mitigation import (
    PositionJumpMitigation, PositionJumpMitigationConfig, PositionStatus,
)
from mitigation.position_jump_mitigation.position_jump_mitigation import position_motion_pairs

METERS_PER_DEGREE = np.pi / 180 * 6_371_000.


@pytest.fixture
def reports():
    return pd.DataFrame({"record_id": [f"report-{i}" for i in range(10)], "mmsi": "123456789",
        "time": pd.date_range("2024-04-09 12:00", periods=10, freq="min"), "latitude": 37.,
        "longitude": -76.2 + np.arange(10) * 60 * 12 * KNOTS_TO_METERS_PER_SECOND
            / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.))),
        "sog": 12., "cog": 90., "vessel_type": 70})


@pytest.fixture
def detector():
    return PositionJumpMitigation()


def test_clean_movement_provides_diagnostics_without_modifying_reports(reports, detector):
    before = reports.copy(deep=True)
    result = detector.apply(reports, reports.time.max())
    assert isinstance(detector, BaseMitigation)
    assert result.status == PositionStatus.NORMAL and not result.anomaly_detected
    assert result.assessed_pairs == 6 and result.maximum_residual_meters < .01
    assert result.observation_time == reports.time.max() and result.evidence == ()
    assert not result.to_dict()["forecast_modified"]
    json.dumps(result.to_dict(), allow_nan=False)
    pd.testing.assert_frame_equal(before, reports)


@pytest.mark.parametrize("offset", [-2000., 2000.])
def test_jump_warns_about_disagreement_without_claiming_either_fix_is_correct(reports, detector, offset):
    reports.loc[9, "longitude"] += offset / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.)))
    result = detector.apply(reports, reports.time.max())
    assert result.anomaly_detected and not result.can_predict
    assert result.flagged_reports == 1 and result.maximum_residual_meters == pytest.approx(abs(offset))
    assert result.evidence[0]["reason"] == "position_motion_disagreement"
    assert result.evidence[0]["time"] == reports.time.max().isoformat()
    assert result.evidence[0]["previous_time"] == reports.time.iloc[-2].isoformat()


def test_score_matches_endpoint_uncertainty_formula(reports, detector):
    reports.loc[9, "longitude"] += 500 / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.)))
    row = position_motion_pairs(reports, detector.config).iloc[-1]
    variance = 2 * detector.config.position_sigma_meters**2 + .5 * detector.config.velocity_sigma_mps**2 * 60**2
    assert row.score == pytest.approx(500**2 / variance)


def test_future_delivery_shuffle_duplicates_and_hidden_truth_do_not_change_result(reports, detector):
    reports["delivered_time"] = reports.time
    reports.loc[9, "longitude"] += .02
    reports.loc[9, "delivered_time"] += pd.Timedelta(minutes=2)
    clock = reports.time.max()
    expected = detector.apply(reports, clock)
    changed = pd.concat([reports, reports, reports.tail(1).assign(time=clock + pd.Timedelta(hours=1),
        delivered_time=clock + pd.Timedelta(hours=1))]).sample(frac=1, random_state=1)
    changed = changed.assign(fault_applied=True, original_longitude=999, arrival_time="hidden")
    assert detector.apply(changed, clock) == expected
    assert not expected.anomaly_detected
    assert detector.apply(reports, clock + pd.Timedelta(minutes=2)).anomaly_detected


def test_warning_expires_and_recent_consistent_reports_recover(reports, detector):
    reports.loc[2, "longitude"] += .02
    assert detector.apply(reports, reports.time.iloc[3]).anomaly_detected
    assert not detector.apply(reports, reports.time.iloc[9]).anomaly_detected
    assert detector.apply(reports, reports.time.max() + pd.Timedelta(minutes=6)).status == PositionStatus.UNASSESSED


@pytest.mark.parametrize("column,value", [("sog", np.nan), ("cog", np.nan), ("cog", 360.), ("sog", 102.3)])
def test_missing_or_unavailable_navigation_is_unassessed_not_imputed(reports, detector, column, value):
    reports[column] = value
    result = detector.apply(reports, reports.time.max())
    assert result.status == PositionStatus.UNASSESSED and not result.anomaly_detected
    assert result.assessed_pairs == 0


def test_stationary_with_unknown_course_is_zero_motion_not_a_guessed_heading(reports, detector):
    reports = reports.assign(longitude=-76.2, sog=0., cog=np.nan)
    assert detector.apply(reports, reports.time.max()).status == PositionStatus.NORMAL
    assert reports.cog.isna().all()


@pytest.mark.parametrize("column,value", [("latitude", np.nan), ("longitude", 181.), ("latitude", 91.)])
def test_invalid_positions_warn_and_remain_in_source(reports, detector, column, value):
    reports.loc[9, column] = value
    before = reports.copy(deep=True)
    result = detector.apply(reports, reports.time.max())
    assert result.anomaly_detected and "invalid_or_missing_position" in result.reasons
    pd.testing.assert_frame_equal(before, reports)


def test_same_time_conflict_warns_and_duplicate_deliveries_are_not_extra_support(reports, detector):
    reports["delivered_time"] = reports.time
    conflict = reports.tail(1).assign(longitude=-75., record_id="conflict", delivered_time=reports.time.max()+pd.Timedelta(seconds=30))
    combined = pd.concat([reports, conflict])
    assert not detector.apply(combined, reports.time.max()).anomaly_detected
    result = detector.apply(combined, conflict.delivered_time.iloc[0])
    assert result.anomaly_detected and "conflicting_same_time_positions" in result.reasons
    single = pd.concat([reports.tail(1)] * 8)
    assert detector.apply(single, reports.time.max()).status == PositionStatus.UNASSESSED


def test_long_gaps_are_unassessed_rather_than_assuming_constant_velocity(reports, detector):
    sparse = reports.iloc[[0, 9]].copy()
    assert detector.apply(sparse, sparse.time.max()).status == PositionStatus.UNASSESSED


def test_constant_offset_from_first_report_cannot_be_detected_internally(reports, detector):
    reports.longitude += .02
    assert not detector.apply(reports, reports.time.max()).anomaly_detected


def test_circular_course_and_longitude_are_handled(reports, detector):
    pair = reports.head(2).copy()
    pair.loc[:, "longitude"] = -76.2
    pair.loc[1, "latitude"] += 60 * 12 * KNOTS_TO_METERS_PER_SECOND / METERS_PER_DEGREE
    pair.loc[:, "cog"] = [358., 2.]
    assert not detector.apply(pair, pair.time.max()).anomaly_detected
    pair.loc[:, "latitude"] = 0.
    pair.loc[:, "longitude"] = [179.999, -179.999]
    pair.loc[:, "cog"] = 90.
    pair.loc[:, "sog"] = .002 * METERS_PER_DEGREE / 60 / KNOTS_TO_METERS_PER_SECOND
    assert not detector.apply(pair, pair.time.max()).anomaly_detected


def test_api_groups_vessels_and_keeps_gap_behavior(reports, detector):
    gate = GateConfig(-76.3, 36.95, 37.05, -76.1, 36.9, 37.1, 120, 6)
    reports.loc[9, "longitude"] += .02
    other = reports.assign(mmsi="987654321", longitude=-76.2, sog=0.)
    combined = pd.concat([reports, other])
    result = AnomalyDetector(GapMitigation(gate), detector).evaluate(combined, reports.time.max())
    assert len(result["anomalies"]) == 1 and result["anomalies"][0]["mmsi"] == "123456789"
    assert result["anomalies"][0]["type"] == "position_jump" and not result["forecast_modified"]
    assert len(result["position_statuses"]) == 2
    json.dumps(result, allow_nan=False)


def test_empty_and_multiple_vessels(reports, detector):
    assert detector.apply(reports.iloc[:0], reports.time.max()).status == PositionStatus.NO_REPORTS
    with pytest.raises(ValueError, match="one vessel"):
        detector.apply(pd.concat([reports, reports.assign(mmsi="2")]), reports.time.max())


@pytest.mark.parametrize("kwargs", [{"position_sigma_meters": 0}, {"velocity_sigma_mps": float("nan")},
    {"distance_threshold_squared": -1}, {"warning_window_minutes": True}, {"maximum_pair_gap_seconds": float("inf")}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        PositionJumpMitigationConfig(**kwargs)


def test_invalid_inputs_and_latest_time(reports, detector):
    with pytest.raises(ValueError, match="parsed real"):
        detector.apply(reports.assign(latitude="37"), reports.time.max())
    with pytest.raises(ValueError, match="latest report time"):
        detector.apply(reports, reports.time.max()+pd.Timedelta(minutes=1),
                       latest_received_time=reports.time.max()+pd.Timedelta(minutes=1))
    with pytest.raises(ValueError):
        detector.apply(reports, "invalid")

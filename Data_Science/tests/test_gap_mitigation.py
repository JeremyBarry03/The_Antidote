"""Causal per-vessel reporting silence and frontend notification contracts."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from api.anamoly_detector import AnomalyDetector
from eta_baselines.configuration import GateConfig
from mitigation import BaseMitigation, GapMitigation, GapMitigationConfig, GapStatus


@pytest.fixture
def detector():
    gate = GateConfig(-76.3, 36.95, 37.05, -76.1, 36.9, 37.1, 120, 6)
    return GapMitigation(gate)


@pytest.fixture
def reports():
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-09 12:00", periods=5, freq="min"),
                         "latitude": 37., "longitude": -76.2, "sog": np.nan, "cog": np.nan})


def test_subclass_triggers_without_new_reports_and_preserves_inputs(detector, reports):
    original = reports.copy(deep=True)
    assert isinstance(detector, BaseMitigation)
    assert detector.apply(reports, "2024-04-09 12:09").status == GapStatus.NORMAL
    gap = detector.apply(reports, "2024-04-09 12:09:01")
    assert gap.anomaly_detected and not gap.can_predict
    assert gap.timeout_minutes == 5 and gap.recent_cadence_minutes == 1
    assert gap.anomaly_since == pd.Timestamp("2024-04-09 12:09")
    assert gap.report_age_minutes > 5
    json.dumps(gap.to_dict(), allow_nan=False)
    pd.testing.assert_frame_equal(original, reports)


def test_recovery_is_observed_not_assumed(detector, reports):
    recovered = pd.concat([reports, reports.tail(1).assign(time=pd.Timestamp("2024-04-09 12:12"))])
    assert detector.apply(recovered, "2024-04-09 12:11").anomaly_detected
    assert detector.apply(recovered, "2024-04-09 12:12").status == GapStatus.NORMAL


def test_future_shuffle_duplicates_and_hidden_truth_cannot_change_detection(detector, reports):
    expected = detector.apply(reports, "2024-04-09 12:10").to_dict()
    changed = pd.concat([reports, reports, reports.tail(1).assign(time=pd.Timestamp("2024-04-09 13:00"), longitude=-76.4)])
    changed = changed.sample(frac=1, random_state=42).assign(arrival_time="hidden", fault_applied=True)
    assert detector.apply(changed, "2024-04-09 12:10").to_dict() == expected


def test_missing_or_outside_positions_do_not_start_monitoring(detector, reports):
    for frame in (reports.assign(latitude=np.nan), reports.assign(longitude=-75.0), reports.iloc[:0]):
        assert detector.apply(frame, "2024-04-09 12:30").status == GapStatus.INACTIVE
    assert detector.apply(reports.head(2), "2024-04-09 12:30").status == GapStatus.WARMING_UP


@pytest.mark.parametrize("longitude,latitude,status", [(-76.31, 37., GapStatus.ARRIVED), (-76.2, 38., GapStatus.LEFT_AREA)])
def test_arrival_or_departure_stops_monitoring(detector, reports, longitude, latitude, status):
    changed = pd.concat([reports, reports.tail(1).assign(time=pd.Timestamp("2024-04-09 12:06"),
                                                        longitude=longitude, latitude=latitude)])
    assert detector.apply(changed, "2024-04-09 13:00").status == status
    reentry = pd.concat([changed, reports.assign(time=reports.time + pd.Timedelta(hours=1))])
    assert detector.apply(reentry, "2024-04-09 13:04").status == GapStatus.NORMAL


def test_end_of_stream_never_inferred_from_last_supplied_row(detector, reports):
    assert detector.apply(reports, "2024-04-09 13:00").anomaly_detected
    assert detector.apply(reports, "2024-04-09 13:00", stream_ended=True).status == GapStatus.STREAM_ENDED


def test_slow_normal_reporting_uses_vessel_cadence(detector, reports):
    slow = reports.assign(time=pd.date_range("2024-04-09 12:00", periods=5, freq="4min"))
    result = detector.apply(slow, "2024-04-09 12:26")
    assert result.timeout_minutes == 12 and result.status == GapStatus.NORMAL
    assert detector.apply(slow, "2024-04-09 12:29").anomaly_detected


def test_delivery_time_and_duplicate_delivery_do_not_fake_recovery(detector, reports):
    delayed = reports.assign(delivered_time=reports.time + pd.Timedelta(minutes=3))
    result = detector.apply(delayed, "2024-04-09 12:10")
    assert result.status == GapStatus.NORMAL and result.silence_minutes == 3 and result.report_age_minutes == 6
    repeat = pd.concat([delayed, delayed.tail(1).assign(delivered_time=pd.Timestamp("2024-04-09 12:15"))])
    assert detector.apply(repeat, "2024-04-09 12:15").anomaly_detected


def test_other_vessel_cannot_refresh_or_enroll_silent_vessel(detector, reports):
    other = reports.assign(mmsi="987654321", time=reports.time + pd.Timedelta(minutes=10))
    combined = pd.concat([reports, other])
    result = AnomalyDetector(detector).evaluate(combined, "2024-04-09 12:14")
    assert len(result["anomalies"]) == 1
    assert result["anomalies"][0]["mmsi"] == "123456789"
    assert not result["forecast_modified"]
    assert len(result["vessel_statuses"]) == 2
    json.dumps(result, allow_nan=False)
    with pytest.raises(ValueError, match="one vessel"):
        detector.apply(combined, "2024-04-09 12:14")


def test_future_only_vessel_and_empty_api_do_not_trigger(detector, reports):
    assert AnomalyDetector(detector).evaluate(reports, "2024-04-09 11:00")["vessel_statuses"] == []
    assert not AnomalyDetector(detector).evaluate(reports.iloc[:0], "2024-04-09 12:00")["anomaly_detected"]


@pytest.mark.parametrize("config", [{"minimum_silence_minutes": 0}, {"cadence_multiplier": float("nan")},
                                    {"minimum_reports": 2}, {"minimum_reports": True}, {"cadence_window_reports": 2},
                                    {"minimum_reports": 11}])
def test_invalid_policy_rejected(config):
    with pytest.raises(ValueError):
        GapMitigationConfig(**config)


def test_invalid_input_and_clock_are_rejected(detector, reports):
    with pytest.raises(ValueError):
        detector.apply(reports, "invalid")
    with pytest.raises(ValueError):
        detector.apply(reports.assign(delivered_time=reports.time - pd.Timedelta(minutes=1)), reports.time.max())
    with pytest.raises(ValueError):
        detector.apply(reports.assign(latitude="bad"), reports.time.max())
    with pytest.raises(ValueError):
        detector.apply(reports, reports.time.max(), stream_ended="false")


def test_configurable_timeout_does_not_change_model_or_source(detector, reports):
    configured = replace(detector, config=GapMitigationConfig(minimum_silence_minutes=10))
    assert detector.apply(reports, "2024-04-09 12:10").anomaly_detected
    assert configured.apply(reports, "2024-04-09 12:10").status == GapStatus.NORMAL

"""Shared-contract drift detection, reconstruction and location observability."""

import json

import numpy as np
import pandas as pd
import pytest

from attacks import LocationDriftAttack, LocationDriftConfig, SensorDriftAttack, SensorDriftConfig
from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import (BaseMitigation, SensorDriftMitigation, SensorDriftMitigationConfig, SensorDriftStatus,
                        LocationDriftMitigation, LocationDriftMitigationConfig, LocationDriftStatus)


@pytest.fixture
def gate():
    return GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6)


def track(count=61, speed=10., course=270., cadence_seconds=60):
    distance = np.arange(count) * cadence_seconds * speed * KNOTS_TO_METERS_PER_SECOND
    radians = np.deg2rad(course)
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=count, freq=f"{cadence_seconds}s"),
        "longitude": -76.1 + distance * np.sin(radians) / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.))),
        "latitude": 37. + distance * np.cos(radians) / METERS_PER_DEGREE,
        "sog": speed, "cog": course, "vessel_type": 70})


@pytest.mark.parametrize("rate", [-.1, .1])
def test_speed_drift_uses_persistence_then_replaces_only_speed(gate, rate):
    original = track()
    source = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=rate)).apply(original).reports
    before = source.copy(deep=True)
    strategy = SensorDriftMitigation(gate)
    assert isinstance(strategy, BaseMitigation)
    result = strategy.apply(source, source.time.max())
    assert result.status == SensorDriftStatus.RECONSTRUCTED and result.anomaly_detected and result.can_predict
    assert result.speed_source == "estimated" and result.speed_knots == pytest.approx(10.)
    assert np.sign(result.ewma_disagreement_knots) == np.sign(rate)
    derived, _ = strategy.reconstruct_reports(source, source.time.max())
    pd.testing.assert_frame_equal(source, before)
    pd.testing.assert_frame_equal(derived.drop(columns="sog"), source.drop(columns="sog"))
    assert derived.sog.iloc[-1] == pytest.approx(10.)
    assert derived.sog.iloc[1] == source.sog.iloc[1]
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(strategy.parameters, allow_nan=False)


def test_speed_clean_spike_alternating_and_small_disagreement_do_not_trigger(gate):
    strategy = SensorDriftMitigation(gate)
    clean = track()
    assert strategy.apply(clean, clean.time.max()).status == SensorDriftStatus.NORMAL
    for source in (clean.assign(sog=10.1), clean.assign(sog=10. + np.where(np.arange(len(clean)) % 2, 2., -2.))):
        assert not strategy.apply(source, source.time.max()).anomaly_detected
    spike = clean.copy()
    spike.loc[60, "sog"] = 30.
    assert not strategy.apply(spike, spike.time.max()).anomaly_detected


def test_genuine_acceleration_does_not_become_a_speed_drift_repair(gate):
    source = track(count=40)
    source["sog"] = 6. + np.arange(len(source)) * .5
    distance = np.r_[0., np.cumsum((source.sog.to_numpy()[:-1] + source.sog.to_numpy()[1:]) * .5 * 60 * KNOTS_TO_METERS_PER_SECOND)]
    source["longitude"] = -76.1 - distance / (METERS_PER_DEGREE * np.cos(np.deg2rad(37.)))
    result = SensorDriftMitigation(gate).apply(source, source.time.max())
    assert result.requires_review and not result.anomaly_detected and result.speed_source == "reported"
    assert result.reasons == ("maneuvering_position_track",)


def test_burst_of_reports_does_not_replace_elapsed_persistence(gate):
    source = track(count=60, cadence_seconds=1).assign(sog=7.)
    assert not SensorDriftMitigation(gate).apply(source, source.time.max()).anomaly_detected
    drifting = LocationDriftAttack(LocationDriftConfig(bearing_degrees=0.)).apply(track(count=60, cadence_seconds=1)).reports
    assert not LocationDriftMitigation(gate).apply(drifting, drifting.time.max()).anomaly_detected


def test_speed_reconstruction_is_causal_and_does_not_backfill_late_history(gate):
    strategy = SensorDriftMitigation(gate)
    source = track(count=25).assign(sog=lambda frame: frame.sog - np.arange(len(frame)) * .1,
                                   delivered_time=lambda frame: frame.time)
    source.loc[10, "delivered_time"] = source.time.iloc[22]
    early, _ = strategy.reconstruct_reports(source.head(20), source.time.iloc[19])
    later, _ = strategy.reconstruct_reports(source, source.time.max())
    pd.testing.assert_frame_equal(early, later.loc[later.time.isin(early.time)].reset_index(drop=True))
    shuffled = pd.concat([source, source]).sample(frac=1, random_state=4)
    shuffled["original_sog"], shuffled["fault_applied"] = -999., True
    assert strategy.apply(shuffled, source.time.max()).to_dict() == strategy.apply(source, source.time.max()).to_dict()


@pytest.mark.parametrize("kind", ["position", "speed", "gap", "turn", "stale"])
def test_speed_unreliable_reference_requests_review(gate, kind):
    source = track().assign(sog=7.)
    clock = source.time.max()
    if kind == "position":
        source.loc[60, "longitude"] = np.nan
    elif kind == "speed":
        source.loc[60, "sog"] = np.nan
    elif kind == "gap":
        source.loc[60, "time"] += pd.Timedelta(minutes=4)
        clock = source.time.max()
    elif kind == "turn":
        source.loc[60, "latitude"] += .003
    else:
        clock += pd.Timedelta(minutes=6)
    result = SensorDriftMitigation(gate).apply(source, clock)
    assert result.requires_review and not result.can_predict and result.speed_source != "estimated"
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("bearing", [0., 90., 180., 270.])
def test_location_drift_flags_and_requests_verification_without_editing_coordinates(gate, bearing):
    original = track()
    source = LocationDriftAttack(LocationDriftConfig(bearing_degrees=bearing)).apply(original).reports
    before = source.copy(deep=True)
    strategy = LocationDriftMitigation(gate)
    result = strategy.apply(source, source.time.max())
    assert isinstance(strategy, BaseMitigation)
    assert result.drift_detected and result.anomaly_detected and result.requires_review and not result.can_predict
    assert not result.correction_applied
    assert result.to_dict()["recommended_action"] == "verify_position"
    assert result.anomaly_since <= result.decision_time
    pd.testing.assert_frame_equal(source, before)
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(strategy.parameters, allow_nan=False)


def test_location_alarm_remains_after_bias_stops_growing(gate):
    source = LocationDriftAttack(LocationDriftConfig(bearing_degrees=0., maximum_bias_meters=100.,
        rate_variation_fraction=0)).apply(track(count=181)).reports
    result = LocationDriftMitigation(gate).apply(source, source.time.max())
    assert result.status == LocationDriftStatus.DRIFT and result.drift_detected
    assert result.ewma_disagreement_meters_per_minute < 1.
    assert not result.can_predict  # Matching velocities do not recover absolute position.


def test_clean_location_is_normal_but_constant_offset_is_unobservable(gate):
    strategy = LocationDriftMitigation(gate)
    for source in (track(), track().assign(longitude=lambda frame: frame.longitude + .01)):
        result = strategy.apply(source, source.time.max())
        assert result.status == LocationDriftStatus.NORMAL and result.can_predict
        assert not result.anomaly_detected
    stopped = track(speed=0.).assign(cog=np.nan)
    assert strategy.apply(stopped, stopped.time.max()).can_predict


def test_location_single_spike_alternating_error_and_short_history_do_not_prove_drift(gate):
    strategy = LocationDriftMitigation(gate)
    source = track(count=12)
    spike = source.copy()
    spike.loc[11, "latitude"] += .001
    assert not strategy.apply(spike, spike.time.max()).drift_detected
    jitter = source.assign(latitude=37. + np.where(np.arange(len(source)) % 2, .0001, -.0001))
    assert not strategy.apply(jitter, jitter.time.max()).drift_detected
    assert strategy.apply(source.head(2), source.time.iloc[1]).requires_review


@pytest.mark.parametrize("kind", ["position", "navigation", "gap", "turn", "stale"])
def test_location_unreliable_inputs_request_review(gate, kind):
    source = track()
    clock = source.time.max()
    if kind == "position":
        source.loc[60, "latitude"] = np.nan
    elif kind == "navigation":
        source.loc[60, "cog"] = 360.
    elif kind == "gap":
        source.loc[60, "time"] += pd.Timedelta(minutes=4)
        clock = source.time.max()
    elif kind == "turn":
        source.loc[60, "cog"] = 180.
    else:
        clock += pd.Timedelta(minutes=6)
    result = LocationDriftMitigation(gate).apply(source, clock)
    assert result.requires_review and not result.can_predict and not result.correction_applied
    json.dumps(result.to_dict(), allow_nan=False)


@pytest.mark.parametrize("cls", [SensorDriftMitigation, LocationDriftMitigation])
def test_common_contract_future_truth_duplicates_conflicts_and_input_validation(gate, cls):
    strategy = cls(gate)
    source = track().assign(delivered_time=lambda frame: frame.time)
    clock = source.time.iloc[20]
    short = strategy.apply(source.head(21), clock).to_dict()
    changed = source.copy()
    changed.loc[21:, "latitude"] = 80.
    changed["original_longitude"], changed["fault_applied"] = 0., True
    assert strategy.apply(changed, clock).to_dict() == short
    assert strategy.apply(pd.concat([changed, changed]), clock).to_dict() == short
    delayed = source.copy()
    delayed.loc[21:, "delivered_time"] += pd.Timedelta(hours=2)
    assert strategy.apply(delayed, clock).to_dict() == short
    conflict = pd.concat([source, source.tail(1).assign(longitude=-75.)])
    assert strategy.apply(conflict, source.time.max()).requires_review
    assert strategy.apply(source.iloc[:0], clock).requires_review
    for bad in (source.assign(sog="bad"), source.assign(time="bad"),
                source.assign(delivered_time=source.time-pd.Timedelta(seconds=1)),
                pd.concat([source, source.assign(mmsi="987654321")])):
        with pytest.raises(ValueError):
            strategy.apply(bad, clock)
    with pytest.raises(ValueError):
        strategy.apply(source, clock, latest_received_time=clock + pd.Timedelta(minutes=1))


@pytest.mark.parametrize("settings", [dict(minimum_reports=2), dict(minimum_persistent_reports=True),
    dict(ewma_time_constant_minutes=0), dict(drift_threshold_knots=np.nan), dict(maximum_track_turn_degrees=181),
    dict(minimum_span_seconds=1000), dict(minimum_disagreement_knots=1.)])
def test_speed_configuration_validation(settings):
    with pytest.raises(ValueError):
        SensorDriftMitigationConfig(**settings)


@pytest.mark.parametrize("settings", [dict(minimum_persistent_reports=2), dict(ewma_time_constant_minutes=False),
    dict(drift_threshold_meters_per_minute=np.inf), dict(maximum_direction_change_degrees=181),
    dict(minimum_disagreement_meters_per_minute=100), dict(stationary_speed_knots=70.)])
def test_location_configuration_validation(settings):
    with pytest.raises(ValueError):
        LocationDriftMitigationConfig(**settings)

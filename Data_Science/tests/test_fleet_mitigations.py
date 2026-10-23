"""Fleet strategies, conditional references and comparator integrity."""

import json
import numpy as np
import pandas as pd
import pytest

from Optimized_Model.features import QUALITY_COLUMNS
from Optimized_Model.fleet_mitigations import FleetPolicy, available_anchor, position_anchors
from Optimized_Model.service import _json_value
from tests.test_drift_mitigation import track
from tests.test_fleet import fleet  # noqa: F401 -- shared deterministic fixture


@pytest.fixture
def coherent_fleet(fleet):
    history = track(count=40)
    history["time"] += pd.Timedelta(hours=12)
    fleet.dataset.histories["voyage"] = history
    fleet.starts["voyage"] = history.time.min()
    fleet.approaches.loc["voyage", "arrival_time"] = history.time.max() + pd.Timedelta(minutes=1)
    fleet.start = history.time.min()
    fleet.end = history.time.max() + pd.Timedelta(minutes=11)
    fleet.initial_time = history.time.iloc[30]
    return fleet


def vessel(service, settings, **options):
    return service.frame(service.initial_time.timestamp(), settings, **options)["ships"][0]


def strategy(ship, name):
    return next(row for row in ship["mitigation"]["strategies"] if row["id"] == name)


@pytest.mark.parametrize("direction", ["under", "over"])
def test_speed_drift_repairs_both_directions_without_changing_a_b_or_feed(coherent_fleet, direction):
    source = coherent_fleet.dataset.histories["voyage"].copy(deep=True)
    off = vessel(coherent_fleet, {"sensor_drift": 100}, mitigate=False, drift_direction=direction)
    on = vessel(coherent_fleet, {"sensor_drift": 100}, drift_direction=direction)
    assert strategy(on, "sensor_drift")["applied"]
    assert on["predictions"]["C"]["eta"] != off["predictions"]["C"]["eta"]
    for name in ("A", "B"):
        assert on["predictions"][name] == off["predictions"][name]
    assert [row["speed"] for row in on["reports"]] == [row["speed"] for row in off["reports"]]
    assert any(row["estimated_values"] for row in on["reports"])
    pd.testing.assert_frame_equal(coherent_fleet.dataset.histories["voyage"], source)


def test_missing_speed_and_course_combine_using_original_positions(coherent_fleet):
    ship = vessel(coherent_fleet, {"missing_speed": 100, "missing_course": 100})
    assert strategy(ship, "missing_speed")["applied"]
    assert strategy(ship, "missing_course")["applied"]
    last = ship["reports"][-1]
    assert pd.isna(last["speed"]) and pd.isna(last["course"])
    assert last["estimated_values"]["speed"] == pytest.approx(10.)
    assert last["estimated_values"]["course"] == pytest.approx(270.)
    json.dumps(_json_value(ship), allow_nan=False)


def test_class_carry_forward_uses_received_history_and_preserves_unknown_without_it(coherent_fleet):
    history = coherent_fleet.dataset.histories["voyage"]
    history.loc[history.index >= 27, "vessel_type"] = np.nan
    ship = vessel(coherent_fleet, {})
    assert strategy(ship, "missing_vessel_class")["applied"]
    assert pd.isna(ship["reports"][-1]["vessel_type"])
    no_history = vessel(coherent_fleet, {"missing_vessel_class": 100})
    assert not strategy(no_history, "missing_vessel_class")["applied"]
    assert strategy(no_history, "missing_vessel_class")["requires_review"]


def test_gaussian_noise_has_supported_estimates_and_c_only_changes(coherent_fleet):
    off = vessel(coherent_fleet, {"sensor_deterioration": 100}, mitigate=False)
    on = vessel(coherent_fleet, {"sensor_deterioration": 100})
    assert strategy(on, "sensor_noise")["applied"]
    assert on["predictions"]["B"] == off["predictions"]["B"]
    assert "sensor_noise" not in {row["id"] for row in vessel(coherent_fleet, {})["mitigation"]["strategies"]}


def test_location_drift_warns_without_references_and_corrects_only_with_explicit_fixes(coherent_fleet):
    settings = {"location_drift": 100}
    off = vessel(coherent_fleet, settings, mitigate=False)
    monitor = vessel(coherent_fleet, settings)
    assert strategy(monitor, "location_drift")["detected"]
    assert not strategy(monitor, "location_drift")["applied"]
    assert monitor["predictions"] == off["predictions"]
    corrected = vessel(coherent_fleet, settings, trusted_fixes=True)
    assert strategy(corrected, "location_drift")["applied"]
    assert corrected["mitigation"]["reference_simulated"]
    assert corrected["predictions"]["B"] == off["predictions"]["B"]
    last = corrected["reports"][-1]
    original = coherent_fleet.dataset.histories["voyage"].iloc[30]
    assert last["estimated_values"]["longitude"] == pytest.approx(original.longitude)
    assert last["longitude"] != pytest.approx(original.longitude)


@pytest.mark.parametrize("position", ["location_drift", "position_jump"])
def test_mixed_position_and_sensor_faults_do_not_treat_either_as_trusted(coherent_fleet, position):
    settings = {position: 100, "sensor_drift": 100, "sensor_deterioration": 100, "missing_speed": 50}
    ship = vessel(coherent_fleet, settings)
    assert not ship["mitigation"]["features_changed"]
    assert strategy(ship, "sensor_drift")["requires_review"]
    assert strategy(ship, "sensor_noise")["requires_review"]
    assert not ship["mitigation"]["estimated_values"]
    assert ship["predictions"] == vessel(coherent_fleet, settings, mitigate=False)["predictions"]


def test_noise_and_speed_drift_together_pause_overlapping_sensor_repairs(coherent_fleet):
    ship = vessel(coherent_fleet, {"sensor_drift": 100, "sensor_deterioration": 100})
    for name in ("sensor_drift", "sensor_noise"):
        assert strategy(ship, name)["requires_review"] and not strategy(ship, name)["applied"]


def test_position_detector_is_warning_only(coherent_fleet):
    settings = {"position_jump": 100}
    on = vessel(coherent_fleet, settings)
    off = vessel(coherent_fleet, settings, mitigate=False)
    assert strategy(on, "position_jump")["detected"]
    assert on["predictions"] == off["predictions"]
    assert not on["mitigation"]["features_changed"]


def test_future_changes_do_not_backfill_estimates_or_anchors(coherent_fleet):
    settings = {"location_drift": 100}
    before = _json_value(vessel(coherent_fleet, settings, trusted_fixes=True))
    history = coherent_fleet.dataset.histories["voyage"]
    history.loc[history.time > coherent_fleet.initial_time, ["longitude", "sog"]] = [-75., 50.]
    coherent_fleet._stream.cache_clear()
    after = _json_value(vessel(coherent_fleet, settings, trusted_fixes=True))
    assert before == after
    nominal, _, _ = coherent_fleet._stream("voyage", (0.,) * 8)
    anchors = position_anchors(nominal)
    assert available_anchor(anchors, nominal.time.iloc[4], nominal.time.iloc[4]).time == nominal.time.iloc[0]


def test_adapters_preserve_raw_quality_fields_support_and_clocks(coherent_fleet):
    _, changed, _ = coherent_fleet._stream("voyage", (0., 100., 100., 0., 0., 0., 0., 0.))
    clock = coherent_fleet.initial_time
    received = changed.loc[changed.time <= clock]
    patch, metadata = coherent_fleet.mitigations.apply(received, clock, FleetPolicy())
    assert metadata["features_changed"]
    assert not set(patch) & (set(QUALITY_COLUMNS) | {"observation_time", "decision_time", "supported", "reasons"})
    assert not any(name.startswith("raw_") for name in patch)


@pytest.mark.parametrize("options", [
    {"mitigate": "true"}, {"trusted_fixes": 1}, {"drift_direction": "sideways"},
    {"trusted_fixes": True}, {"mitigate": False, "trusted_fixes": True},
])
def test_invalid_options_fail_before_inference(coherent_fleet, options):
    with pytest.raises(ValueError):
        vessel(coherent_fleet, {}, **options)


@pytest.mark.parametrize("attack", ["missing_speed", "missing_course", "sensor_drift", "sensor_deterioration", "position_jump"])
def test_simulated_anchor_mode_rejects_untrusted_navigation_combinations(coherent_fleet, attack):
    with pytest.raises(ValueError, match="no navigation or position-jump"):
        vessel(coherent_fleet, {"location_drift": 100, attack: 50}, trusted_fixes=True)

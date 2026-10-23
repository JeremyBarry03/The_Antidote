"""Bounded coordinate reconstruction, independent evidence and causal delivery."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from attacks import LocationDriftAttack, LocationDriftConfig, SensorDriftAttack
from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import LocationDriftMitigation, LocationDriftStatus, PositionAnchor
from tests.test_drift_mitigation import track


@pytest.fixture
def strategy():
    return LocationDriftMitigation(GateConfig(-76.3, 36.95, 37.05, -75.8, 36.9, 37.1, 120, 6))


def anchor_at(original, index=0, **overrides):
    row = original.iloc[index]
    return PositionAnchor(**(dict(mmsi=str(row.mmsi), time=row.time,
        longitude=float(row.longitude), latitude=float(row.latitude),
        source="independent test fixture position") | overrides))


@pytest.mark.parametrize("bearing", [0., 90., 180., 270.])
def test_location_only_correction_retains_alarm_and_only_changes_derived_coordinates(strategy, bearing):
    original = track(count=6)
    raw = LocationDriftAttack(LocationDriftConfig(bearing_degrees=bearing)).apply(original).reports
    before = raw.copy(deep=True)
    result = strategy.apply(raw, raw.time.max(), anchor=anchor_at(original), navigation_trusted=True)
    assert result.status == LocationDriftStatus.RECONSTRUCTED
    assert result.drift_detected and result.anomaly_detected and result.correction_applied
    assert result.can_predict and not result.requires_review and result.position_source == "estimated"
    assert result.longitude == pytest.approx(original.longitude.iloc[-1], abs=1e-10)
    assert result.latitude == pytest.approx(original.latitude.iloc[-1], abs=1e-10)
    assert result.reported_longitude == raw.longitude.iloc[-1]
    assert result.reported_latitude == raw.latitude.iloc[-1]
    assert result.observation_time == raw.time.max() and result.projection_minutes == 5.
    assert result.to_dict()["recommended_action"] == "use_estimated_position"
    assert result.anchor_source == "independent test fixture position"
    derived, diagnostics = strategy.reconstruct_reports(raw, raw.time.max(),
        anchor=anchor_at(original), navigation_trusted=True)
    pd.testing.assert_frame_equal(raw, before)
    pd.testing.assert_frame_equal(derived.drop(columns=["longitude", "latitude"]),
                                  raw.drop(columns=["longitude", "latitude"]))
    pd.testing.assert_frame_equal(derived.head(3), raw.head(3))
    np.testing.assert_allclose(derived[["longitude", "latitude"]].tail(3),
                               original[["longitude", "latitude"]].tail(3), atol=1e-10, rtol=0)
    assert diagnostics.to_dict() == result.to_dict()
    json.dumps(result.to_dict(), allow_nan=False)
    json.dumps(strategy.parameters, allow_nan=False)


def test_neither_a_trusted_position_nor_trusted_navigation_alone_permits_correction(strategy):
    original = track(count=6)
    raw = LocationDriftAttack().apply(original).reports
    for kwargs in ({}, {"navigation_trusted": True}, {"anchor": anchor_at(original)},
                   {"anchor": anchor_at(original), "navigation_trusted": False}):
        result = strategy.apply(raw, raw.time.max(), **kwargs)
        assert result.drift_detected and result.requires_review and not result.correction_applied
        assert result.position_source == "reported"
        assert result.longitude == raw.longitude.iloc[-1] and result.latitude == raw.latitude.iloc[-1]


def test_combined_faults_are_not_corrected_without_independent_navigation_trust(strategy):
    original = track(count=6)
    raw = LocationDriftAttack().apply(SensorDriftAttack().apply(original).reports).reports
    result = strategy.apply(raw, raw.time.max(), anchor=anchor_at(original))
    assert result.drift_detected and not result.correction_applied and result.requires_review
    assert "trusted_navigation_required_for_position_correction" in result.reasons


def test_projection_expires_and_does_not_clear_a_detected_drift(strategy):
    original = track(count=9)
    raw = LocationDriftAttack().apply(original).reports
    anchor = anchor_at(original)
    at_limit = strategy.apply(raw, raw.time.iloc[5], anchor=anchor, navigation_trusted=True)
    expired = strategy.apply(raw, raw.time.iloc[5]+pd.Timedelta(nanoseconds=1),
                             anchor=anchor, navigation_trusted=True)
    assert at_limit.correction_applied and not expired.correction_applied
    assert expired.drift_detected and expired.requires_review
    assert "position_anchor_expired" in expired.reasons
    derived, current = strategy.reconstruct_reports(raw, raw.time.max(), anchor=anchor, navigation_trusted=True)
    assert not current.correction_applied
    pd.testing.assert_frame_equal(derived.iloc[6:], raw.iloc[6:])
    assert derived.latitude.iloc[5] == pytest.approx(original.latitude.iloc[5])


def test_a_fresh_verified_anchor_supports_an_old_latched_drift(strategy):
    original = track(count=61)
    raw = LocationDriftAttack().apply(original).reports
    result = strategy.apply(raw, raw.time.max(), anchor=anchor_at(original, 58), navigation_trusted=True)
    assert result.correction_applied and result.projection_minutes == 2.
    assert result.anomaly_since < result.anchor_time
    assert result.longitude == pytest.approx(original.longitude.iloc[-1], abs=1e-10)
    assert result.latitude == pytest.approx(original.latitude.iloc[-1], abs=1e-10)


def test_a_late_anchor_cannot_backfill_earlier_corrections(strategy):
    original = track(count=6)
    raw = LocationDriftAttack().apply(original).reports.assign(delivered_time=lambda frame: frame.time)
    anchor = anchor_at(original, received_time=raw.time.iloc[5])
    early, _ = strategy.reconstruct_reports(raw, raw.time.iloc[4], anchor=anchor, navigation_trusted=True)
    later, result = strategy.reconstruct_reports(raw, raw.time.iloc[5], anchor=anchor, navigation_trusted=True)
    pd.testing.assert_frame_equal(early, later.head(5))
    pd.testing.assert_frame_equal(early, raw.head(5))
    assert result.correction_applied and later.latitude.iloc[5] == pytest.approx(original.latitude.iloc[5])
    future = anchor_at(original, 5, time=raw.time.max()+pd.Timedelta(minutes=1))
    result = strategy.apply(raw, raw.time.max(), anchor=future, navigation_trusted=True)
    assert not result.correction_applied and "position_anchor_not_yet_available" in result.reasons


def test_projection_integrates_from_an_anchor_between_report_times(strategy):
    original = track(count=6)
    speeds = 10. + np.arange(len(original))*.1
    distance = np.r_[0., np.cumsum((speeds[:-1]+speeds[1:])*.5*60*KNOTS_TO_METERS_PER_SECOND)]
    original["sog"] = speeds
    scale = METERS_PER_DEGREE*np.cos(np.deg2rad(37.))
    original["longitude"] = -76.1-distance/scale
    anchor = anchor_at(original, time=original.time.iloc[0]+pd.Timedelta(seconds=30),
        longitude=-76.1-(10.+10.05)*.5*30*KNOTS_TO_METERS_PER_SECOND/scale)
    raw = LocationDriftAttack().apply(original).reports
    result = strategy.apply(raw, raw.time.max(), anchor=anchor, navigation_trusted=True)
    assert result.correction_applied and result.projection_minutes == 4.5
    assert result.longitude == pytest.approx(original.longitude.iloc[-1], abs=1e-10)


@pytest.mark.parametrize("kind", ["gap", "turn", "missing_speed", "stale"])
def test_unreliable_navigation_anywhere_after_anchor_blocks_projection(strategy, kind):
    original = track(count=16)
    raw = LocationDriftAttack().apply(original).reports
    if kind == "gap":
        raw = raw.loc[~raw.index.isin([9, 10, 11])].reset_index(drop=True)
    elif kind == "turn":
        raw.loc[11, "cog"] = 90.
    elif kind == "missing_speed":
        raw.loc[11, "sog"] = np.nan
    clock = raw.time.max()+pd.Timedelta(minutes=6) if kind == "stale" else raw.time.max()
    result = strategy.apply(raw, clock, anchor=anchor_at(original, 10), navigation_trusted=True)
    assert result.drift_detected and result.requires_review and not result.correction_applied


def test_projection_future_reports_audit_truth_and_duplicates_cannot_change_result(strategy):
    original = track(count=10)
    raw = LocationDriftAttack().apply(original).reports
    clock, anchor = raw.time.iloc[5], anchor_at(original)
    expected = strategy.apply(raw.head(6), clock, anchor=anchor, navigation_trusted=True).to_dict()
    raw.loc[6:, "latitude"] = 80.
    raw["original_longitude"], raw["original_latitude"], raw["fault_applied"] = -50., 20., True
    repeated = pd.concat([raw, raw]).sample(frac=1, random_state=4)
    assert strategy.apply(repeated, clock, anchor=anchor, navigation_trusted=True).to_dict() == expected


def test_clean_feed_stays_reported_even_with_an_anchor(strategy):
    raw = track(count=6)
    result = strategy.apply(raw, raw.time.max(), anchor=anchor_at(raw), navigation_trusted=True)
    assert result.status == LocationDriftStatus.NORMAL and result.can_predict
    assert not result.correction_applied and result.position_source == "reported"
    derived, _ = strategy.reconstruct_reports(raw, raw.time.max(), anchor=anchor_at(raw), navigation_trusted=True)
    pd.testing.assert_frame_equal(derived, raw)


def test_anchor_and_navigation_input_validation(strategy):
    original = track(count=6)
    raw = LocationDriftAttack().apply(original).reports
    for settings in (dict(longitude=np.nan), dict(latitude=91.), dict(longitude=True),
                     dict(time="bad"), dict(time=pd.NaT), dict(source=""), dict(mmsi=""),
                     dict(received_time=original.time.iloc[0]-pd.Timedelta(seconds=1))):
        with pytest.raises(ValueError):
            anchor_at(original, **settings)
    with pytest.raises(ValueError, match="observed vessel"):
        strategy.apply(raw, raw.time.max(), anchor=replace(anchor_at(original), mmsi="987654321"))
    with pytest.raises(ValueError, match="boolean"):
        strategy.apply(raw, raw.time.max(), navigation_trusted=1)
    with pytest.raises(ValueError, match="PositionAnchor"):
        strategy.apply(raw, raw.time.max(), anchor={"longitude": 0})
    with pytest.raises(ValueError, match="compatible timezones"):
        strategy.apply(raw, raw.time.max(), anchor=replace(anchor_at(original),
            time=original.time.iloc[0].tz_localize("UTC"), received_time=original.time.iloc[0].tz_localize("UTC")),
            navigation_trusted=True)


@pytest.mark.parametrize("limit", [0., -1., np.inf, np.nan, True])
def test_projection_limit_validation(strategy, limit):
    with pytest.raises(ValueError, match="maximum_projection_minutes"):
        replace(strategy.config, maximum_projection_minutes=limit)

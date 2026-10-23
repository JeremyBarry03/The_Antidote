"""Gradual location bias preserves source motion, timing and causal replay."""

from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, LocationDriftAttack, LocationDriftConfig


@pytest.fixture
def reports():
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=61, freq="min"),
        "latitude": 37., "longitude": np.linspace(-76.1, -76.3, 61), "sog": 10., "cog": 270., "vessel_type": 70})


def test_smooth_location_bias_preserves_motion_clocks_and_source(reports):
    original = reports.copy(deep=True)
    attack = LocationDriftAttack(LocationDriftConfig(bearing_degrees=90.))
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    pd.testing.assert_frame_equal(reports, original)
    pd.testing.assert_frame_equal(stream.reports.drop(columns=["latitude", "longitude", "record_id", "delivered_time"]),
                                  reports.drop(columns=["latitude", "longitude"]))
    assert len(stream.reports) == len(reports)
    distance = stream.modification_log.requested_displacement_meters.to_numpy()
    assert distance[0] == 0 and np.all(np.diff(distance) >= 0) and distance.max() < 1852
    np.testing.assert_allclose(stream.modification_log.applied_displacement_meters, distance, atol=1e-6)
    assert not stream.modification_log.fault_applied.iloc[0]
    assert stream.modification_log.action.iloc[-1] == "location_drifted"
    assert not {"original_latitude", "original_longitude", "fault_applied", "attack", "seed"} & set(stream.reports)
    json.dumps(attack.parameters, allow_nan=False)


def test_order_sampling_duplicates_future_and_seed_are_stable(reports):
    attack = LocationDriftAttack()
    full = attack.apply(reports)
    pd.testing.assert_frame_equal(full.reports, attack.apply(reports.sample(frac=1, random_state=4)).reports)
    short = attack.apply(reports.head(20))
    pd.testing.assert_frame_equal(short.reports, full.available(reports.time.iloc[19]))
    sparse = reports.iloc[[0, 4, 11, 35, 60]]
    pd.testing.assert_frame_equal(full.reports.loc[sparse.index], attack.apply(sparse).reports)
    doubled = attack.apply(pd.concat([reports, reports]))
    assert len(doubled.reports) == 2 * len(reports)
    assert doubled.reports.groupby("time").longitude.nunique().le(1).all()
    assert not np.array_equal(full.reports.longitude, LocationDriftAttack(replace(attack.config, seed=43)).apply(reports).reports.longitude)


def test_start_target_missingness_and_real_delivery_are_preserved(reports):
    reports.loc[9, "latitude"] = np.nan
    reports.loc[10, "longitude"] = 181.
    reports["delivered_time"] = reports.time + pd.Timedelta(minutes=2)
    other = reports.assign(mmsi="987654321")
    start = reports.time.iloc[5]
    attack = LocationDriftAttack(LocationDriftConfig(start_time=start, target_mmsi="123456789"))
    stream = attack.apply(pd.concat([reports, other]))
    untouched = stream.reports.loc[stream.reports.mmsi.eq("987654321")]
    pd.testing.assert_frame_equal(untouched[reports.columns], other)
    assert not stream.modification_log.loc[stream.modification_log.mmsi.eq("987654321"), "fault_applied"].any()
    first = stream.reports.loc[stream.reports.mmsi.eq("123456789")]
    pd.testing.assert_frame_equal(first.loc[first.time.le(start), reports.columns], reports.loc[reports.time.le(start)])
    assert pd.isna(first.latitude.iloc[9]) and first.longitude.iloc[10] == 181.
    assert stream.available(reports.time.iloc[0] + pd.Timedelta(minutes=1)).empty
    window = reports.iloc[20:31]
    pd.testing.assert_frame_equal(first.loc[window.index], attack.apply(window).reports)


@pytest.mark.parametrize("settings", [{"drift_rate_meters_per_minute": 0}, {"maximum_bias_meters": 0},
                                      {"start_time": "2025-01-01"}, {"target_mmsi": "987654321"}])
def test_noop_preserves_original_values_and_empty_input(reports, settings):
    attack = LocationDriftAttack(LocationDriftConfig(**settings))
    stream = attack.apply(reports)
    pd.testing.assert_frame_equal(stream.reports[reports.columns], reports)
    assert not stream.modification_log.fault_applied.any()
    assert attack.apply(reports.iloc[:0]).reports.empty


def test_geodesic_offset_handles_dateline_and_poles(reports):
    for latitude, longitude in ((0., 179.999), (89.99, 120.)):
        source = reports.assign(latitude=latitude, longitude=longitude)
        stream = LocationDriftAttack(LocationDriftConfig(bearing_degrees=90.)).apply(source)
        assert stream.reports.longitude.between(-180, 180).all()
        assert stream.reports.latitude.between(-90, 90).all()
        np.testing.assert_allclose(stream.modification_log.applied_displacement_meters,
                                   stream.modification_log.requested_displacement_meters, atol=.001)


@pytest.mark.parametrize("settings", [dict(drift_rate_meters_per_minute=-1), dict(maximum_bias_meters=-1),
    dict(maximum_bias_meters=1e10), dict(drift_rate_meters_per_minute=True), dict(maximum_bias_meters=np.nan),
    dict(rate_variation_fraction=1), dict(variation_period_minutes=0), dict(bearing_degrees=360),
    dict(bearing_degrees=True), dict(seed=True), dict(target_mmsi="bad"), dict(start_time="bad")])
def test_invalid_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        LocationDriftConfig(**settings)

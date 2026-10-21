"""Location jumps preserve source truth, causal selection and spherical distances."""

from dataclasses import FrozenInstanceError
import json

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, PositionJumpAttack, PositionJumpConfig
from attacks.positionJumpAttack.position_jump_attack import EARTH_RADIUS_METERS


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=120, freq="min"),
        "latitude": 37., "longitude": np.linspace(-76.1,-76.2,120), "sog": 12., "cog": 270.,
        "vessel_type": 70, "arrival_time": pd.Timestamp("2024-04-10 03:00")})


def test_only_position_changes_and_audit_truth_stays_separate(reports):
    original = reports.copy(deep=True)
    attack = PositionJumpAttack()
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    pd.testing.assert_frame_equal(reports,original)
    other = list(reports.columns.drop(["latitude","longitude"]))
    pd.testing.assert_frame_equal(stream.reports[other],original[other])
    assert 0 < stream.modification_log.fault_applied.sum() < len(reports)
    assert not {"fault_applied","original_latitude","original_longitude","selected","attack","seed"} & set(stream.reports)
    assert stream.modification_log.loc[stream.modification_log.fault_applied,"action"].eq("position_shifted").all()
    np.testing.assert_allclose(stream.modification_log.loc[stream.modification_log.fault_applied,
        "applied_displacement_meters"],2000,rtol=0,atol=1e-6)
    assert json.loads(json.dumps(attack.parameters))["displacement_meters"] == 2000
    with pytest.raises(FrozenInstanceError):
        attack.config.seed = 1


@pytest.mark.parametrize("bearing,lat,lon", [(0,1,0),(90,0,1),(180,-1,0),(270,0,-1)])
def test_known_cardinal_destinations_at_equator(reports,bearing,lat,lon):
    settings = PositionJumpConfig(EARTH_RADIUS_METERS*np.pi/180,1,bearing_degrees=bearing)
    stream = PositionJumpAttack(settings).apply(reports.assign(latitude=0.,longitude=0.))
    np.testing.assert_allclose(stream.reports.latitude,lat,atol=1e-10)
    np.testing.assert_allclose(stream.reports.longitude,lon,atol=1e-10)


@pytest.mark.parametrize("fraction", [.1,.2,.25,.5,1.])
def test_percentages_repeat_exactly_and_are_stable_when_severity_changes(reports,fraction):
    low = PositionJumpAttack(PositionJumpConfig(500,fraction,4201)).apply(reports)
    high = PositionJumpAttack(PositionJumpConfig(40000,fraction,4201)).apply(reports)
    np.testing.assert_array_equal(low.modification_log.selected,high.modification_log.selected)
    np.testing.assert_allclose(low.modification_log.bearing_degrees,high.modification_log.bearing_degrees)
    pd.testing.assert_frame_equal(low.reports,PositionJumpAttack(PositionJumpConfig(500,fraction,4201)).apply(reports).reports)
    if fraction == 1:
        assert low.modification_log.fault_applied.all()
    else:
        assert 0 < low.modification_log.fault_applied.sum() < len(reports)


def test_selection_and_bearing_ignore_shuffle_duplicates_and_future_reports(reports):
    attack = PositionJumpAttack()
    stream = attack.apply(reports)
    cut = reports.time.iloc[49]
    pd.testing.assert_frame_equal(stream.available(cut),attack.apply(reports.iloc[:50]).available(cut))
    shuffled = reports.sample(frac=1,random_state=5)
    pd.testing.assert_frame_equal(attack.apply(shuffled).reports.sort_index(),stream.reports)
    pd.testing.assert_series_equal(attack.apply(shuffled).reports.time,shuffled.time)
    duplicate = pd.concat([reports.iloc[:20],reports.iloc[:20]])
    repeated = attack.apply(duplicate)
    assert len(repeated.reports) == len(duplicate)
    assert repeated.reports.groupby("time").longitude.nunique().eq(1).all()
    other_seed = PositionJumpAttack(PositionJumpConfig(seed=43)).apply(reports)
    assert not other_seed.reports.longitude.equals(stream.reports.longitude)


def test_half_open_window_returns_to_original_coordinates_without_changing_other_data(reports):
    start,end = reports.time.iloc[10],reports.time.iloc[20]
    stream = PositionJumpAttack(PositionJumpConfig(2000,1,start_time=start,end_time=end)).apply(reports)
    expected = reports.time.ge(start)&reports.time.lt(end)
    np.testing.assert_array_equal(stream.modification_log.fault_applied,expected)
    pd.testing.assert_frame_equal(stream.reports.loc[~expected,reports.columns],reports.loc[~expected])
    assert stream.modification_log.fault_applied.sum() == 10
    single = PositionJumpAttack(PositionJumpConfig(2000,1,start_time=start,
        end_time=start+pd.Timedelta(seconds=1))).apply(reports)
    assert single.modification_log.fault_applied.sum() == 1


def test_targeting_and_combining_vessels_preserve_each_vessels_result(reports):
    other = reports.assign(mmsi="987654321")
    combined = pd.concat([reports,other],ignore_index=True)
    together = PositionJumpAttack().apply(combined)
    pd.testing.assert_frame_equal(together.reports.iloc[:len(reports)],PositionJumpAttack().apply(reports).reports)
    pd.testing.assert_frame_equal(together.reports.iloc[len(reports):].reset_index(drop=True),PositionJumpAttack().apply(other).reports)
    targeted = PositionJumpAttack(PositionJumpConfig(2000,1,target_mmsi="123456789")).apply(combined)
    pd.testing.assert_frame_equal(targeted.reports.iloc[len(reports):][other.columns].reset_index(drop=True),other)


def test_invalid_missing_and_nullable_coordinates_remain_unmodified(reports):
    special = reports.copy()
    special.loc[:3,"latitude"] = [np.nan,91,np.inf,-91]
    special.loc[4:6,"longitude"] = [181,np.nan,-np.inf]
    stream = PositionJumpAttack(PositionJumpConfig(2000,1)).apply(special)
    pd.testing.assert_frame_equal(stream.reports.loc[:6,special.columns],special.loc[:6])
    assert not stream.modification_log.loc[:6,"selected"].any()
    nullable = reports.assign(latitude=pd.array([37]*len(reports),dtype="Int64"))
    nullable.loc[0,"latitude"] = pd.NA
    result = PositionJumpAttack(PositionJumpConfig(2000,1)).apply(nullable)
    assert np.isnan(result.reports.latitude.iloc[0]) and result.modification_log.fault_applied.iloc[1:].all()


@pytest.mark.parametrize("settings", [dict(displacement_meters=0),dict(affected_fraction=0)])
def test_noop_and_empty_input_preserve_dtypes(reports,settings):
    integer = reports.assign(latitude=37,longitude=-76)
    attack = PositionJumpAttack(PositionJumpConfig(**settings))
    result = attack.apply(integer)
    pd.testing.assert_frame_equal(result.reports[integer.columns],integer)
    assert not result.modification_log.fault_applied.any()
    empty = attack.apply(integer.iloc[:0])
    assert empty.reports.empty and empty.modification_log.empty


def test_wrapping_poles_and_source_delivery_metadata(reports):
    edge = reports.assign(latitude=0.,longitude=179.999)
    east = PositionJumpAttack(PositionJumpConfig(40000,1,bearing_degrees=90)).apply(edge)
    assert east.reports.longitude.lt(0).all()
    polar = PositionJumpAttack(PositionJumpConfig(40000,1,bearing_degrees=0)).apply(
        reports.assign(latitude=89.9,longitude=20.))
    assert polar.reports.latitude.between(-90,90).all() and polar.reports.longitude.between(-180,180).all()
    np.testing.assert_allclose(polar.modification_log.applied_displacement_meters,40000,atol=1e-4)
    delayed = reports.assign(delivered_time=reports.time+pd.Timedelta(minutes=2),
                             record_id=[f"source-{i}" for i in range(len(reports))])
    result = PositionJumpAttack().apply(delayed)
    pd.testing.assert_series_equal(result.reports.delivered_time,delayed.delivered_time)
    pd.testing.assert_series_equal(result.reports.record_id,delayed.record_id)
    assert result.available(reports.time.iloc[0]).empty


@pytest.mark.parametrize("settings", [dict(displacement_meters=-1),dict(displacement_meters=np.nan),
    dict(displacement_meters=np.inf),dict(displacement_meters=True),dict(displacement_meters=1e20),
    dict(bearing_degrees=-1),dict(bearing_degrees=360),dict(bearing_degrees=np.nan),dict(bearing_degrees=True),
    dict(affected_fraction=-.1),dict(affected_fraction=1.1),dict(affected_fraction=np.nan),
    dict(seed=True),dict(seed=1.5),dict(target_mmsi="bad"),dict(start_time="2024-01-01"),
    dict(start_time="bad",end_time="2024-01-01"),dict(start_time="2024-01-02",end_time="2024-01-01")])
def test_invalid_configuration_fails_clearly(settings):
    with pytest.raises(ValueError):
        PositionJumpConfig(**settings)


@pytest.mark.parametrize("field", ["latitude","longitude"])
def test_required_numeric_fields_and_timezone_compatibility(reports,field):
    with pytest.raises(ValueError,match=field):
        PositionJumpAttack().apply(reports.drop(columns=field))
    for value in ("37",True,complex(37,1)):
        with pytest.raises(ValueError,match=field):
            PositionJumpAttack().apply(reports.assign(**{field:value}))
    settings = PositionJumpConfig(start_time="2024-04-10T00:00:00Z",end_time="2024-04-10T01:00:00Z")
    with pytest.raises(ValueError,match="compatible timezones"):
        PositionJumpAttack(settings).apply(reports)
    utc = reports.assign(time=reports.time.dt.tz_localize("UTC"))
    assert str(PositionJumpAttack(settings).apply(utc).reports.time.dt.tz) == "UTC"

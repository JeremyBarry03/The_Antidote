"""Navigation noise is reproducible, circular, causal and separate from truth."""

from dataclasses import FrozenInstanceError
import json

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, SensorDeteriorationAttack, SensorDeteriorationConfig


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=100, freq="min"),
                         "sog": 12., "cog": 270., "longitude": -76.1, "latitude": 37., "vessel_type": 70})


def test_only_sog_and_cog_change_and_originals_and_truth_remain_separate(reports):
    original = reports.copy(deep=True)
    attack = SensorDeteriorationAttack()
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert stream.modification_log.sog_changed.all() and stream.modification_log.cog_changed.all()
    pd.testing.assert_frame_equal(reports, original)
    columns = list(reports.columns.drop(["sog", "cog"]))
    pd.testing.assert_frame_equal(stream.reports[columns], reports[columns])
    assert not {"fault_applied", "original_sog", "original_cog", "selected", "seed"} & set(stream.reports)
    assert json.loads(json.dumps(attack.parameters))["cog_sigma_degrees"] == 5.
    with pytest.raises(FrozenInstanceError):
        attack.config.seed = 1


def test_gaussian_draws_are_independent_and_higher_sigma_increases_expected_magnitude(reports):
    large = pd.concat([reports]*100, ignore_index=True)
    large["time"] = pd.date_range("2024-04-10", periods=len(large), freq="s")
    low = SensorDeteriorationAttack(SensorDeteriorationConfig(.5, 2)).apply(large).modification_log
    high = SensorDeteriorationAttack(SensorDeteriorationConfig(2, 10)).apply(large).modification_log
    x, y = low.requested_sog_noise_knots/.5, low.requested_cog_noise_degrees/2
    assert abs(x.mean()) < .04 and abs(y.mean()) < .04
    assert .96 < x.std() < 1.04 and .96 < y.std() < 1.04
    assert abs(x.corr(y)) < .04
    assert high.applied_sog_noise_knots.abs().mean() > low.applied_sog_noise_knots.abs().mean()*3.8
    assert high.applied_cog_noise_degrees.abs().mean() > low.applied_cog_noise_degrees.abs().mean()*4.8


def test_wraps_in_both_directions_and_speed_clips_only_at_zero(reports):
    edge = reports.assign(sog=0., cog=358.)
    stream = SensorDeteriorationAttack(SensorDeteriorationConfig(4, 20)).apply(edge)
    audit = stream.modification_log
    np.testing.assert_allclose(stream.reports.sog, np.maximum(0, audit.original_sog+audit.requested_sog_noise_knots))
    np.testing.assert_allclose(stream.reports.cog, (audit.original_cog+audit.requested_cog_noise_degrees) % 360)
    assert stream.reports.sog.ge(0).all() and stream.reports.cog.ge(0).all() and stream.reports.cog.lt(360).all()
    assert audit.cog_wrapped.any() and audit.sog_clipped.any()
    north = SensorDeteriorationAttack(SensorDeteriorationConfig(0, 20)).apply(reports.assign(cog=0.))
    assert north.modification_log.cog_wrapped.any()
    high = SensorDeteriorationAttack(SensorDeteriorationConfig(4, 0)).apply(reports.assign(sog=102.2))
    assert high.reports.sog.gt(102.2).any()


@pytest.mark.parametrize("fraction", [.1, .25, .5, 1.])
def test_shared_selection_and_independent_modes_match_combined_draws(reports, fraction):
    settings = dict(affected_fraction=fraction, seed=4201)
    both = SensorDeteriorationAttack(SensorDeteriorationConfig(1, 5, **settings)).apply(reports)
    speed = SensorDeteriorationAttack(SensorDeteriorationConfig(1, 0, **settings)).apply(reports)
    course = SensorDeteriorationAttack(SensorDeteriorationConfig(0, 5, **settings)).apply(reports)
    pd.testing.assert_series_equal(both.reports.sog, speed.reports.sog)
    pd.testing.assert_series_equal(both.reports.cog, course.reports.cog)
    pd.testing.assert_series_equal(speed.reports.cog, reports.cog)
    pd.testing.assert_series_equal(course.reports.sog, reports.sog)
    np.testing.assert_array_equal(both.modification_log.selected, speed.modification_log.selected)
    np.testing.assert_array_equal(both.modification_log.sog_changed, both.modification_log.cog_changed)
    assert both.modification_log.fault_applied.sum() > 0


def test_seeds_order_duplicates_future_reports_and_other_vessels_do_not_change_draws(reports):
    attack = SensorDeteriorationAttack(SensorDeteriorationConfig(affected_fraction=.5))
    stream = attack.apply(reports)
    pd.testing.assert_frame_equal(stream.reports, attack.apply(reports).reports)
    cut = reports.time.iloc[49]
    pd.testing.assert_frame_equal(stream.available(cut), attack.apply(reports.iloc[:50]).available(cut))
    shuffled = reports.sample(frac=1, random_state=5)
    pd.testing.assert_frame_equal(attack.apply(shuffled).reports.sort_index(), stream.reports)
    pd.testing.assert_series_equal(attack.apply(shuffled).reports.time, shuffled.time)
    duplicate = pd.concat([reports.iloc[:10], reports.iloc[:10]])
    repeated = attack.apply(duplicate)
    assert len(repeated.reports) == len(duplicate)
    assert repeated.reports.groupby("time").sog.nunique().eq(1).all()
    combined = pd.concat([reports, reports.assign(mmsi="987654321")], ignore_index=True)
    combined_stream = attack.apply(combined)
    pd.testing.assert_frame_equal(combined_stream.reports.iloc[:len(reports)], stream.reports)
    changed_seed = SensorDeteriorationAttack(SensorDeteriorationConfig(seed=43)).apply(reports)
    assert not changed_seed.reports.sog.equals(stream.reports.sog)


def test_invalid_and_missing_measurements_are_preserved_instead_of_becoming_valid(reports):
    special = reports.copy()
    special.loc[:5, "sog"] = [np.nan, np.inf, -1, 102.3, -np.inf, 0]
    special.loc[:5, "cog"] = [np.nan, 360, -1, np.inf, -np.inf, 0]
    result = SensorDeteriorationAttack().apply(special)
    pd.testing.assert_frame_equal(result.reports.loc[:4, ["sog", "cog"]], special.loc[:4, ["sog", "cog"]])
    assert not result.modification_log.loc[:4, "fault_applied"].any()
    partial = SensorDeteriorationAttack().apply(reports.assign(sog=np.nan))
    assert partial.reports.sog.isna().all() and partial.modification_log.cog_changed.all()


def test_targeting_integer_nullable_values_empty_input_and_delivery_metadata(reports):
    integer = reports.assign(sog=pd.array([12]*len(reports), dtype="Int64"), cog=270)
    integer.loc[0, "sog"] = pd.NA
    integer["delivered_time"] = integer.time+pd.Timedelta(minutes=2)
    integer["record_id"] = [f"source-{i}" for i in range(len(integer))]
    combined = pd.concat([integer, integer.assign(mmsi="987654321")], ignore_index=True)
    attack = SensorDeteriorationAttack(SensorDeteriorationConfig(target_mmsi="123456789"))
    stream = attack.apply(combined)
    assert np.isnan(stream.reports.sog.iloc[0])
    assert stream.reports.loc[stream.reports.mmsi.eq("987654321"), "sog"].dropna().eq(12).all()
    pd.testing.assert_series_equal(stream.reports.delivered_time, combined.delivered_time)
    pd.testing.assert_series_equal(stream.reports.record_id, combined.record_id)
    assert stream.available(integer.time.iloc[0]).empty
    empty = attack.apply(integer.iloc[:0])
    assert empty.reports.empty and empty.modification_log.empty


@pytest.mark.parametrize("settings", [dict(affected_fraction=0), dict(sog_sigma_knots=0, cog_sigma_degrees=0)])
def test_noop_preserves_original_dtypes_and_fault_flags(reports, settings):
    integer = reports.assign(sog=12, cog=270)
    result = SensorDeteriorationAttack(SensorDeteriorationConfig(**settings)).apply(integer)
    pd.testing.assert_frame_equal(result.reports[integer.columns], integer)
    assert not result.modification_log.fault_applied.any()


@pytest.mark.parametrize("settings", [dict(sog_sigma_knots=-1), dict(cog_sigma_degrees=-1),
    dict(sog_sigma_knots=np.nan), dict(cog_sigma_degrees=np.inf), dict(sog_sigma_knots=True),
    dict(cog_sigma_degrees="5"), dict(affected_fraction=-.1), dict(affected_fraction=1.1),
    dict(affected_fraction=np.nan), dict(affected_fraction=True), dict(seed=True), dict(seed=1.5),
    dict(target_mmsi="bad"), dict(target_mmsi=123456789)])
def test_invalid_configurations_fail_early(settings):
    with pytest.raises(ValueError):
        SensorDeteriorationConfig(**settings)


@pytest.mark.parametrize("field", ["sog", "cog"])
@pytest.mark.parametrize("value", ["12", True, complex(1, 1)])
def test_unparsed_measurements_fail_clearly(reports, field, value):
    with pytest.raises(ValueError, match=field):
        SensorDeteriorationAttack().apply(reports.assign(**{field: value}))


def test_severity_mapping_and_required_fields(reports):
    config = SensorDeteriorationConfig.from_severity("extreme", affected_fraction=.25, seed=4202)
    assert (config.sog_sigma_knots, config.cog_sigma_degrees, config.affected_fraction) == (4, 20, .25)
    with pytest.raises(ValueError, match="severity"):
        SensorDeteriorationConfig.from_severity("typo")
    for field in ("sog", "cog"):
        with pytest.raises(ValueError, match=field):
            SensorDeteriorationAttack().apply(reports.drop(columns=field))

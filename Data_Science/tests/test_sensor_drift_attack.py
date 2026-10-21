"""Speed drift preserves evidence and creates a causal, smooth, repeatable bias."""

from dataclasses import FrozenInstanceError
import json

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, SensorDriftAttack, SensorDriftConfig


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=121, freq="min"),
        "sog": 12., "cog": 270., "longitude": np.linspace(-76.1, -76.3, 121),
        "latitude": 37., "vessel_type": 70})


def test_defaults_generate_automatic_drift_and_keep_truth_separate(reports):
    original = reports.copy(deep=True)
    reports.loc[5, "sog"] = np.nan
    original.loc[5, "sog"] = np.nan
    attack = SensorDriftAttack()
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert stream.reports.sog.iloc[0] == 12.
    assert 9. <= stream.reports.sog.iloc[-1] < 12.
    assert np.isnan(stream.reports.sog.iloc[5])
    assert not stream.modification_log.fault_applied.iloc[0]
    assert not stream.modification_log.fault_applied.iloc[5]
    assert stream.modification_log.action.iloc[-1] == "speed_drifted"
    assert len(stream.reports) == len(reports)
    pd.testing.assert_frame_equal(reports, original)
    other = list(reports.columns.drop("sog"))
    pd.testing.assert_frame_equal(stream.reports[other], reports[other])
    assert not {"original_sog", "reported_sog", "requested_bias_knots", "fault_applied", "attack", "seed"} & set(stream.reports)
    assert json.loads(json.dumps(attack.parameters))["drift_rate_knots_per_minute"] == -.1
    with pytest.raises(FrozenInstanceError):
        attack.config.seed = 1


@pytest.mark.parametrize("rate", [-.1, .1])
def test_bias_is_smooth_bounded_and_never_reverses_direction(reports, rate):
    dense = reports.iloc[:1].reindex(range(12001)).ffill()
    dense["time"] = pd.date_range(reports.time.iloc[0], periods=len(dense), freq="s")
    result = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=rate)).apply(dense)
    bias = result.modification_log.requested_bias_knots.to_numpy()
    differences = np.diff(bias)
    assert bias[0] == 0.
    assert np.max(np.abs(bias)) <= 3.
    assert np.all(differences*np.sign(rate) >= -1e-12)
    slopes = differences*60
    assert np.max(np.abs(slopes)) <= abs(rate)*1.25+1e-10
    assert np.max(np.abs(np.diff(slopes))) < .001
    assert np.ptp(slopes[:600]) > .001


def test_zero_rate_variation_matches_the_declared_bias_equation(reports):
    result = SensorDriftAttack(SensorDriftConfig(rate_variation_fraction=0)).apply(reports)
    minutes = np.arange(len(reports), dtype=float)
    expected = 3*np.tanh(-.1*minutes/3)
    np.testing.assert_allclose(result.modification_log.requested_bias_knots, expected, rtol=0, atol=1e-14)


def test_sampling_frequency_order_and_future_reports_do_not_change_existing_values(reports):
    attack = SensorDriftAttack()
    full = attack.apply(reports)
    sampled = reports.iloc[[0, 3, 7, 20, 45, 120]]
    sparse = attack.apply(sampled)
    np.testing.assert_array_equal(full.reports.loc[sampled.index, "sog"], sparse.reports.sog)
    cutoff = reports.time.iloc[45]
    pd.testing.assert_frame_equal(full.available(cutoff), attack.apply(reports.iloc[:46]).available(cutoff))
    shuffled = attack.apply(reports.sample(frac=1, random_state=1))
    pd.testing.assert_frame_equal(full.reports, shuffled.reports)
    pd.testing.assert_frame_equal(full.reports, attack.apply(reports).reports)


def test_each_vessel_has_its_own_start_phase_and_optional_target(reports):
    second = reports.assign(mmsi="987654321", time=reports.time+pd.Timedelta(minutes=30))
    combined = pd.concat([reports, second])
    both = SensorDriftAttack().apply(combined)
    for mmsi, group in both.reports.groupby("mmsi"):
        original = combined.loc[combined.mmsi.eq(mmsi)]
        pd.testing.assert_frame_equal(group, SensorDriftAttack().apply(original).reports)
        assert group.sog.iloc[0] == 12.
    first_bias = both.modification_log.loc[both.modification_log.mmsi.eq("123456789"), "requested_bias_knots"]
    second_bias = both.modification_log.loc[both.modification_log.mmsi.eq("987654321"), "requested_bias_knots"]
    assert not np.array_equal(first_bias.to_numpy(), second_bias.to_numpy())
    targeted = SensorDriftAttack(SensorDriftConfig(target_mmsi="123456789")).apply(combined)
    assert targeted.reports.loc[targeted.reports.mmsi.eq("987654321"), "sog"].eq(12.).all()
    assert not targeted.modification_log.loc[targeted.modification_log.mmsi.eq("987654321"), "fault_applied"].any()


def test_explicit_start_time_preserves_pre_start_values_and_delivery_metadata(reports):
    reports["record_id"] = [f"original-{index}" for index in range(len(reports))]
    reports["delivered_time"] = reports.time+pd.Timedelta(minutes=2)
    start = reports.time.iloc[30]
    attack = SensorDriftAttack(SensorDriftConfig(start_time=start.isoformat()))
    result = attack.apply(reports)
    assert result.reports.loc[result.reports.time.le(start), "sog"].eq(12.).all()
    assert result.reports.loc[result.reports.time.gt(start), "sog"].lt(12.).all()
    pd.testing.assert_series_equal(result.reports.delivered_time, reports.delivered_time)
    pd.testing.assert_series_equal(result.reports.record_id, reports.record_id)
    assert result.available(reports.time.iloc[0]+pd.Timedelta(minutes=1)).empty
    assert attack.parameters["start_time"] == start.isoformat()
    window = reports.iloc[40:61]
    pd.testing.assert_frame_equal(result.reports.loc[window.index], attack.apply(window).reports)


@pytest.mark.parametrize("settings", [dict(drift_rate_knots_per_minute=0), dict(maximum_bias_knots=0),
    dict(target_mmsi="987654321"), dict(start_time="2025-01-01")])
def test_no_change_preserves_speed_dtype_and_audit(settings, reports):
    reports["sog"] = reports.sog.astype("Int64")
    result = SensorDriftAttack(SensorDriftConfig(**settings)).apply(reports)
    pd.testing.assert_frame_equal(result.reports[reports.columns], reports)
    assert not result.modification_log.fault_applied.any()
    assert result.modification_log.action.eq("retained").all()


def test_clipping_audits_requested_and_actual_bias_without_false_changes(reports):
    low = reports.assign(sog=0.)
    result = SensorDriftAttack().apply(low)
    assert result.reports.sog.eq(0.).all()
    assert result.modification_log.clipped.iloc[1:].all()
    assert not result.modification_log.fault_applied.any()
    assert result.modification_log.applied_bias_knots.eq(0.).all()
    high = reports.assign(sog=102.)
    result = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=.1)).apply(high)
    assert result.reports.sog.le(102.2).all()
    assert result.modification_log.clipped.any()
    assert result.modification_log.applied_bias_knots.iloc[-1] == pytest.approx(.2)
    assert result.modification_log.requested_bias_knots.iloc[-1] > 2.


def test_nullable_speeds_empty_input_and_repeated_indices_are_supported(reports):
    reports["sog"] = reports.sog.astype("Int64")
    reports.loc[3, "sog"] = pd.NA
    result = SensorDriftAttack().apply(reports)
    assert pd.isna(result.reports.sog.iloc[3])
    empty = SensorDriftAttack().apply(reports.iloc[:0])
    assert empty.reports.empty and empty.modification_log.empty
    repeated = pd.concat([reports.iloc[:8], reports.iloc[:8]])
    duplicated = SensorDriftAttack().apply(repeated)
    assert len(duplicated.reports) == len(repeated)
    assert duplicated.reports.groupby("time").sog.nunique().le(1).all()
    other_seed = SensorDriftAttack(SensorDriftConfig(seed=43)).apply(reports)
    assert not np.array_equal(result.reports.sog.fillna(0), other_seed.reports.sog.fillna(0))


@pytest.mark.parametrize("settings", [dict(drift_rate_knots_per_minute=float("nan")),
    dict(drift_rate_knots_per_minute=float("inf")), dict(drift_rate_knots_per_minute=True),
    dict(drift_rate_knots_per_minute="-.1"), dict(maximum_bias_knots=-1), dict(maximum_bias_knots=float("inf")),
    dict(maximum_bias_knots=True), dict(rate_variation_fraction=-.1), dict(rate_variation_fraction=1),
    dict(rate_variation_fraction=float("nan")), dict(variation_period_minutes=0),
    dict(variation_period_minutes=-1), dict(variation_period_minutes=float("inf")),
    dict(seed=True), dict(seed=1.2), dict(target_mmsi="bad"), dict(target_mmsi=123456789),
    dict(start_time="not-a-time"), dict(start_time="NaT"), dict(start_time=pd.NaT), dict(start_time=42)])
def test_invalid_configuration_fails_early(settings):
    with pytest.raises(ValueError):
        SensorDriftConfig(**settings)


@pytest.mark.parametrize("speed", ["12", True, complex(12, 1), np.inf, -1., 102.3])
def test_invalid_speeds_fail_early(reports, speed):
    with pytest.raises(ValueError, match="sog"):
        SensorDriftAttack().apply(reports.assign(sog=speed))


def test_missing_columns_and_incompatible_timezones_fail_early(reports):
    with pytest.raises(ValueError, match="sog"):
        SensorDriftAttack().apply(reports.drop(columns="sog"))
    with pytest.raises(ValueError, match="datetimes"):
        SensorDriftAttack().apply(reports.assign(time=reports.time.astype(str)))
    with pytest.raises(ValueError, match="compatible timezones"):
        SensorDriftAttack(SensorDriftConfig(start_time="2024-04-10T00:00:00Z")).apply(reports)
    utc = reports.assign(time=reports.time.dt.tz_localize("UTC"))
    result = SensorDriftAttack(SensorDriftConfig(start_time="2024-04-10T00:00:00Z")).apply(utc)
    assert str(result.reports.time.dt.tz) == "UTC"


@pytest.mark.parametrize("period", [1e-306, 1e-320])
def test_unrepresentable_variation_period_fails_instead_of_creating_missing_speed(reports, period):
    with pytest.raises(ValueError, match="too small"):
        SensorDriftAttack(SensorDriftConfig(variation_period_minutes=period)).apply(reports)

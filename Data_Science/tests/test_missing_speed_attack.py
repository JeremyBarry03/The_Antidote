"""Speed masking, input preservation and deterministic replay selection."""

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, MissingSpeedAttack, MissingSpeedConfig


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=30, freq="min"),
                         "sog": [float(i % 5) for i in range(30)], "cog": 270.,
                         "longitude": [-76.1-i*.001 for i in range(30)], "latitude": 37., "vessel_type": 70})


def test_only_speed_changes_and_existing_missing_values_are_not_new_faults(reports):
    reports.loc[0, 'sog'] = np.nan
    original = reports.copy(deep=True)
    attack = MissingSpeedAttack(MissingSpeedConfig(1))
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert stream.reports.sog.isna().all()
    assert stream.modification_log.fault_applied.sum() == 29
    pd.testing.assert_frame_equal(reports, original)
    columns = list(reports.columns.drop('sog'))
    pd.testing.assert_frame_equal(stream.reports[columns], original[columns])
    assert not {'original_sog', 'fault_applied', 'attack', 'seed'} & set(stream.reports)


def test_partial_selection_is_repeatable_and_future_invariant(reports):
    attack = MissingSpeedAttack(MissingSpeedConfig(.5, seed=42))
    time = reports.time.iloc[14]
    full = attack.apply(reports)
    earlier = attack.apply(reports.loc[reports.time <= time])
    pd.testing.assert_frame_equal(full.available(time), earlier.available(time))
    pd.testing.assert_frame_equal(full.reports, attack.apply(reports).reports)
    assert 0 < full.modification_log.fault_applied.sum() < len(reports)


def test_targets_one_vessel_and_preserves_delivery_metadata(reports):
    combined = pd.concat([reports, reports.assign(mmsi='987654321')], ignore_index=True)
    combined['delivered_time'] = combined.time+pd.Timedelta(minutes=2)
    combined['record_id'] = [f'source-{i}' for i in range(len(combined))]
    attack = MissingSpeedAttack(MissingSpeedConfig(1, target_mmsi='123456789'))
    stream = attack.apply(combined)
    assert stream.reports.loc[stream.reports.mmsi.eq('123456789'), 'sog'].isna().all()
    assert stream.reports.loc[stream.reports.mmsi.eq('987654321'), 'sog'].notna().all()
    assert (stream.reports.delivered_time-stream.reports.time).eq(pd.Timedelta(minutes=2)).all()
    assert stream.available(pd.Timestamp('2024-04-10 00:01')).empty
    assert set(stream.reports.record_id) == set(combined.record_id)


def test_zero_prevalence_empty_and_repeated_indices_are_supported(reports):
    attack = MissingSpeedAttack(MissingSpeedConfig(0))
    pd.testing.assert_frame_equal(attack.apply(reports).reports[reports.columns], reports)
    assert attack.apply(reports.iloc[:0]).reports.empty
    repeated = pd.concat([reports.head(2), reports.head(2)])
    result = MissingSpeedAttack(MissingSpeedConfig(1)).apply(repeated)
    assert len(result.reports) == 4 and result.reports.sog.isna().all()


def test_masking_integer_speeds_does_not_turn_missing_values_into_zero(reports):
    reports['sog'] = reports.sog.astype(int)
    assert MissingSpeedAttack(MissingSpeedConfig(1)).apply(reports).reports.sog.isna().all()


def test_rejects_missing_or_unparsed_speed_and_time(reports):
    attack = MissingSpeedAttack(MissingSpeedConfig())
    with pytest.raises(ValueError, match='sog'):
        attack.apply(reports.drop(columns='sog'))
    with pytest.raises(ValueError, match='numeric'):
        attack.apply(reports.assign(sog='12.0'))
    with pytest.raises(ValueError, match='datetimes'):
        attack.apply(reports.assign(time=reports.time.astype(str)))


@pytest.mark.parametrize('settings', [dict(affected_fraction=-.1), dict(affected_fraction=1.1),
    dict(affected_fraction=float('nan')), dict(affected_fraction=float('inf')), dict(affected_fraction=True),
    dict(seed=1.5), dict(seed=True), dict(target_mmsi='bad')])
def test_invalid_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        MissingSpeedConfig(**settings)

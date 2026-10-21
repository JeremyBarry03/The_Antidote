"""Missing course is distinct from north, with source timing and speed preserved."""

import numpy as np
import pandas as pd
import pytest

from attacks import BaseAttack, MissingCourseAttack, MissingCourseConfig


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({'mmsi': '123456789', 'time': pd.date_range('2024-04-10', periods=30, freq='min'),
                         'sog': 12., 'cog': [float((350+i) % 360) for i in range(30)],
                         'longitude': [-76.1-i*.001 for i in range(30)], 'latitude': 37., 'vessel_type': 70})


def test_only_course_is_masked_and_natural_missingness_is_not_an_injected_fault(reports):
    reports.loc[0, 'cog'] = np.nan
    original = reports.copy(deep=True)
    attack = MissingCourseAttack(MissingCourseConfig(1))
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert stream.reports.cog.isna().all()
    assert stream.modification_log.fault_applied.sum() == 29
    pd.testing.assert_frame_equal(reports, original)
    columns = list(reports.columns.drop('cog'))
    pd.testing.assert_frame_equal(stream.reports[columns], original[columns])
    assert not {'original_cog', 'fault_applied', 'attack', 'seed'} & set(stream.reports)


def test_selection_is_repeatable_causal_and_keeps_real_zero_course(reports):
    attack = MissingCourseAttack(MissingCourseConfig(.5, seed=42))
    time = reports.time.iloc[14]
    full = attack.apply(reports)
    earlier = attack.apply(reports.loc[reports.time <= time])
    pd.testing.assert_frame_equal(full.available(time), earlier.available(time))
    pd.testing.assert_frame_equal(full.reports, attack.apply(reports).reports)
    assert 0 < full.modification_log.fault_applied.sum() < len(reports)
    zero = MissingCourseAttack(MissingCourseConfig(0)).apply(reports)
    assert zero.reports.loc[reports.cog.eq(0), 'cog'].eq(0).all()
    pd.testing.assert_frame_equal(zero.reports[reports.columns], reports)


def test_targeting_delivery_metadata_empty_input_and_integer_course(reports):
    reports['cog'] = reports.cog.astype(int)
    combined = pd.concat([reports, reports.assign(mmsi='987654321')], ignore_index=True)
    combined['delivered_time'] = combined.time+pd.Timedelta(minutes=2)
    combined['record_id'] = [f'source-{i}' for i in range(len(combined))]
    attack = MissingCourseAttack(MissingCourseConfig(1, target_mmsi='123456789'))
    stream = attack.apply(combined)
    assert stream.reports.loc[stream.reports.mmsi.eq('123456789'), 'cog'].isna().all()
    assert stream.reports.loc[stream.reports.mmsi.eq('987654321'), 'cog'].notna().all()
    assert (stream.reports.delivered_time-stream.reports.time).eq(pd.Timedelta(minutes=2)).all()
    assert stream.available(pd.Timestamp('2024-04-10 00:01')).empty
    assert set(stream.reports.record_id) == set(combined.record_id)
    assert attack.apply(combined.iloc[:0]).reports.empty


def test_invalid_fields_fail_before_masking(reports):
    attack = MissingCourseAttack(MissingCourseConfig())
    with pytest.raises(ValueError, match='cog'):
        attack.apply(reports.drop(columns='cog'))
    with pytest.raises(ValueError, match='numeric'):
        attack.apply(reports.assign(cog='270'))
    with pytest.raises(ValueError, match='numeric'):
        attack.apply(reports.assign(cog=True))


@pytest.mark.parametrize('settings', [dict(affected_fraction=-.1), dict(affected_fraction=1.1),
    dict(affected_fraction=float('nan')), dict(affected_fraction=float('inf')), dict(affected_fraction=True),
    dict(seed=1.5), dict(seed=True), dict(target_mmsi='bad')])
def test_invalid_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        MissingCourseConfig(**settings)

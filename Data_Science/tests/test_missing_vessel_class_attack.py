"""Missing classification keeps every motion report in the active attack."""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from attacks import BaseAttack, MissingVesselClassAttack, MissingVesselClassConfig
from attacks.missingVesselClassAttack import classified_cargo_tanker_reports
from eta_baselines.configuration import ExperimentConfig
from eta_baselines.features import FEATURE_COLUMNS, VESSEL_CLASS_COLUMNS, FeatureBuilder


@pytest.fixture
def reports() -> pd.DataFrame:
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-10", periods=30, freq="min"),
                         "vessel_type": 80., "sog": 12., "cog": 240.,
                         "longitude": np.linspace(-76.1, -76.2, 30), "latitude": 37.})


def test_mask_changes_only_class_and_preserves_all_reports(reports):
    reports.loc[0, "vessel_type"] = np.nan
    original = reports.copy(deep=True)
    attack = MissingVesselClassAttack(MissingVesselClassConfig(1))
    stream = attack.apply(reports)
    assert isinstance(attack, BaseAttack)
    assert len(stream.reports) == len(reports)
    assert stream.reports.vessel_type.isna().all()
    assert stream.modification_log.fault_applied.sum() == 29
    assert stream.modification_log.action.eq("vessel_class_removed").sum() == 29
    pd.testing.assert_frame_equal(reports, original)
    columns = list(original.columns.drop("vessel_type"))
    pd.testing.assert_frame_equal(stream.reports[columns], original[columns])
    assert not {"original_vessel_type", "fault_applied", "attack", "seed"} & set(stream.reports)


@pytest.mark.parametrize("vessel_type", [70., 80.])
def test_removal_changes_only_class_features_and_preserves_unknown_state(reports, vessel_type):
    config = ExperimentConfig.load(Path(__file__).resolve().parents[1]/"config.json")
    builder = FeatureBuilder(config.gate, config.features)
    original = reports.assign(vessel_type=vessel_type)
    removed = MissingVesselClassAttack(MissingVesselClassConfig(1)).apply(original).reports
    before, after = builder.summarize(original), builder.summarize(removed)
    assert tuple(after[column] for column in VESSEL_CLASS_COLUMNS) == (0., 0., 1.)
    other = [column for column in FEATURE_COLUMNS if column not in VESSEL_CLASS_COLUMNS]
    np.testing.assert_allclose([before[column] for column in other], [after[column] for column in other], equal_nan=True)


@pytest.mark.parametrize("unit", ["report", "vessel"])
def test_selection_is_repeatable_and_earlier_reports_do_not_depend_on_future(reports, unit):
    attack = MissingVesselClassAttack(MissingVesselClassConfig(.5, selection_unit=unit))
    full = attack.apply(reports)
    cutoff = reports.time.iloc[14]
    earlier = attack.apply(reports.loc[reports.time <= cutoff])
    pd.testing.assert_frame_equal(full.available(cutoff), earlier.available(cutoff))
    pd.testing.assert_frame_equal(full.reports, attack.apply(reports).reports)
    pd.testing.assert_frame_equal(attack.apply(reports.sample(frac=1, random_state=2)).reports[reports.columns],
                                  full.reports[reports.columns])
    assert attack.parameters["selection_unit"] == unit


def test_vessel_selection_masks_whole_histories_and_targeting_preserves_other_vessels(reports):
    combined = pd.concat([reports.assign(mmsi=str(100000000+i)) for i in range(100)], ignore_index=True)
    attack = MissingVesselClassAttack(MissingVesselClassConfig(.5, selection_unit="vessel"))
    stream = attack.apply(combined)
    assert stream.modification_log.groupby("mmsi").fault_applied.nunique().eq(1).all()
    selected = stream.modification_log.groupby("mmsi").fault_applied.first()
    assert 0 < selected.sum() < len(selected)
    target = str(100000001)
    targeted = MissingVesselClassAttack(MissingVesselClassConfig(1, target_mmsi=target)).apply(combined)
    assert targeted.reports.loc[targeted.reports.mmsi.eq(target), "vessel_type"].isna().all()
    assert targeted.reports.loc[~targeted.reports.mmsi.eq(target), "vessel_type"].eq(80).all()


def test_historical_filter_remains_available_only_for_legacy_reproduction(reports):
    frame = reports.iloc[:8].copy()
    frame["vessel_type"] = [70., 79., 80., 89., np.nan, 0., 69., 90.]
    original = frame.copy(deep=True)
    eligible = classified_cargo_tanker_reports(frame)
    assert eligible.vessel_type.tolist() == [70., 79., 80., 89.]
    pd.testing.assert_frame_equal(frame, original)
    assert frame.vessel_type.isna().sum() == 1


def test_zero_mask_nullable_class_delivery_and_empty_stream(reports):
    reports["vessel_type"] = reports.vessel_type.astype("Int64")
    reports["delivered_time"] = reports.time+pd.Timedelta(minutes=2)
    original = reports.copy(deep=True)
    unchanged = MissingVesselClassAttack(MissingVesselClassConfig(0)).apply(reports)
    pd.testing.assert_frame_equal(unchanged.reports[reports.columns], original)
    masked = MissingVesselClassAttack(MissingVesselClassConfig(1)).apply(reports)
    assert masked.reports.vessel_type.isna().all()
    assert masked.available(pd.Timestamp("2024-04-10 00:01")).empty
    assert classified_cargo_tanker_reports(masked.reports).empty
    assert MissingVesselClassAttack(MissingVesselClassConfig()).apply(reports.iloc[:0]).reports.empty


@pytest.mark.parametrize("settings", [dict(affected_fraction=-.1), dict(affected_fraction=1.1),
    dict(affected_fraction=float("nan")), dict(affected_fraction=True), dict(seed=1.5), dict(seed=True),
    dict(target_mmsi="bad"), dict(selection_unit="approach"), dict(selection_unit=None)])
def test_invalid_configurations_are_rejected(settings):
    with pytest.raises(ValueError):
        MissingVesselClassConfig(**settings)


def test_invalid_class_columns_are_rejected(reports):
    attack = MissingVesselClassAttack(MissingVesselClassConfig())
    for frame in (reports.drop(columns="vessel_type"), reports.assign(vessel_type="80"),
                  reports.assign(vessel_type=True)):
        with pytest.raises(ValueError):
            attack.apply(frame)
        with pytest.raises(ValueError):
            classified_cargo_tanker_reports(frame)

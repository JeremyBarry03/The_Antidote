"""Training replication preserves truth and cannot include evaluation rows."""

import numpy as np
import pandas as pd
import pytest

from attacks import UnequalVessellRecordAttack, UnequalVessellRecordConfig
from eta_baselines.evaluation import approach_weights


@pytest.fixture
def training_examples() -> pd.DataFrame:
    return pd.DataFrame({
        "mmsi": ["123456789"] * 4 + ["234567890"] * 2 + ["345678901"] * 2,
        "approach_id": ["a"] * 4 + ["b"] * 2 + ["c"] * 2,
        "split": "train", "speed_knots": [np.nan, 8., 10., 12., 5., 6., 4., 7.],
        "observation_to_arrival_minutes": np.arange(8.) + 1,
    })


def test_only_selected_vessels_gain_rows_without_changing_any_values(training_examples):
    original = training_examples.copy(deep=True)
    attack = UnequalVessellRecordAttack(UnequalVessellRecordConfig(5, .2))
    result = attack.apply(training_examples)
    assert len(result.examples) == 24
    assert result.modification_log.fault_applied.sum() == 16
    assert result.examples.groupby("mmsi").size().to_dict() == {
        "123456789": 20, "234567890": 2, "345678901": 2}
    pd.testing.assert_frame_equal(training_examples, original)
    reconstructed = original.iloc[result.modification_log.source_row].reset_index(drop=True)
    pd.testing.assert_frame_equal(result.examples, reconstructed)
    assert list(result.examples) == list(original)
    assert result.modification_log.groupby("source_row").replica.apply(list).iloc[0] == [0, 1, 2, 3, 4]
    assert attack.parameters == {"record_multiplier": 5, "vessel_fraction": .2}


def test_noop_and_selection_do_not_depend_on_targets_or_input_order(training_examples):
    attack = UnequalVessellRecordAttack(UnequalVessellRecordConfig(1, .5))
    pd.testing.assert_frame_equal(attack.apply(training_examples).examples, training_examples)
    amplified = UnequalVessellRecordAttack(UnequalVessellRecordConfig(3, .5))
    first = amplified.apply(training_examples)
    changed = training_examples.sample(frac=1, random_state=42).copy()
    changed["observation_to_arrival_minutes"] = 99999.
    other = amplified.apply(changed)
    pd.testing.assert_frame_equal(first.vessel_summary, other.vessel_summary)
    assert first.vessel_summary.loc[first.vessel_summary.selected, "mmsi"].tolist() == ["123456789", "234567890"]


def test_existing_approach_weights_counterbalance_replication_mass(training_examples):
    result = UnequalVessellRecordAttack(UnequalVessellRecordConfig(10)).apply(training_examples)
    weighted = result.examples.assign(weight=approach_weights(result.examples))
    totals = weighted.groupby("approach_id").weight.sum()
    np.testing.assert_allclose(totals, totals.iloc[0])
    assert result.vessel_summary.attacked_rows.sum() == len(result.examples)
    assert result.vessel_summary.attacked_share.sum() == pytest.approx(1.)


@pytest.mark.parametrize("settings", [
    {"record_multiplier": True}, {"record_multiplier": 0}, {"record_multiplier": 101},
    {"record_multiplier": 2.5}, {"vessel_fraction": True}, {"vessel_fraction": 0},
    {"vessel_fraction": 1.01}, {"vessel_fraction": float("nan")},
    {"vessel_fraction": float("inf")}, {"vessel_fraction": "0.2"},
])
def test_invalid_settings_fail_early(settings):
    with pytest.raises(ValueError):
        UnequalVessellRecordConfig(**settings)


def test_evaluation_missing_identity_and_ambiguous_approaches_are_rejected(training_examples):
    attack = UnequalVessellRecordAttack(UnequalVessellRecordConfig())
    for invalid in (training_examples.assign(split="evaluation"),
                    training_examples.assign(split=None),
                    training_examples.assign(mmsi=None),
                    training_examples.assign(mmsi="invalid"),
                    training_examples.assign(approach_id=""),
                    training_examples.assign(approach_id="same"),
                    training_examples.drop(columns="split"), training_examples.iloc[:0]):
        with pytest.raises(ValueError):
            attack.apply(invalid)

"""Saved-run comparisons must pair the same forecasts and reference targets."""

import json

import pandas as pd
import pytest

from experiments.position_jump_attack.compare_fixed import compare


@pytest.fixture
def saved_runs(tmp_path):
    normal,fixed = tmp_path/"normal",tmp_path/"fixed"
    normal.mkdir()
    fixed.mkdir()
    protocol = dict(protected_hashes={"B":"same-frozen-model","April":"same-source"},
                    models=["B"],seeds=[4201],window_policy="Whole supplied approach feed")
    (fixed/"protocol.json").write_text(json.dumps(protocol))
    (normal/"protocol.json").write_text(json.dumps({**protocol,"displacement_std_meters":200}))
    rows = []
    for index in range(2):
        for original in (True,False):
            rows.append(dict(system="B",decision_id=f"decision-{index}",approach_id=f"approach-{index}",
                mmsi=f"12345678{index}",decision_time="2024-04-01 00:00:00",arrival_time="2024-04-01 01:00:00",
                scenario="original" if original else "jump",severity="original" if original else "2000m",
                mode="whole_feed",available=True,seed=42 if original else 4201,
                displacement_meters=0 if original else 2000,affected_fraction=0 if original else .25,
                error_minutes=index+1 if original else 2*index+2))
    baseline = pd.DataFrame(rows)
    baseline.to_csv(fixed/"predictions.csv",index=False)
    changed = baseline.copy()
    changed.loc[changed.scenario.ne("original"),"error_minutes"] += 1
    changed.to_csv(normal/"predictions.csv",index=False)
    return normal,fixed


def test_fixed_comparison_reports_actual_paired_error_differences(saved_runs):
    result,validation = compare(*saved_runs)
    row = result.iloc[0]
    assert row.fixed_mae_minutes == row.fixed_mdae_minutes == 3
    assert row.normal_mae_minutes == row.normal_mdae_minutes == 4
    assert row.normal_minus_fixed_mae == row.normal_minus_fixed_mdae == 1
    assert row.paired_predictions == 2
    assert validation["original_forecasts_match"] and validation["paired_predictions"] == 4


@pytest.mark.parametrize("column", ["arrival_time","decision_time","decision_id"])
def test_fixed_comparison_rejects_changed_targets_or_schedule(saved_runs,column):
    normal,fixed = saved_runs
    frame = pd.read_csv(normal/"predictions.csv")
    frame.loc[frame.scenario.ne("original"),column] = "changed"
    frame.to_csv(normal/"predictions.csv",index=False)
    with pytest.raises(ValueError):
        compare(normal,fixed)


def test_fixed_comparison_rejects_changed_model_hash(saved_runs):
    normal,fixed = saved_runs
    protocol = json.loads((normal/"protocol.json").read_text())
    protocol["protected_hashes"]["B"] = "different-model"
    (normal/"protocol.json").write_text(json.dumps(protocol))
    with pytest.raises(ValueError,match="protected_hashes"):
        compare(normal,fixed)

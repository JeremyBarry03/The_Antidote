"""Check warm-cache provenance and matched class experiment summaries."""

import pandas as pd

from experiments.missing_vessel_class_mitigation.run import scenario_feed, summarize, write_report


def history():
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-04-09 12:00", periods=15, freq="min"),
                         "vessel_type": 70., "latitude": 37., "longitude": -76.2,
                         "sog": 12., "cog": 270.})


def test_warm_dropout_retains_only_legitimately_received_pre_onset_labels():
    source = history()
    before = source.copy(deep=True)
    feed = scenario_feed(source, "warm_dropout", 1., 0)
    assert feed.vessel_type.iloc[:10].eq(70).all()
    assert feed.vessel_type.iloc[10:].isna().all()
    pd.testing.assert_frame_equal(feed.drop(columns="vessel_type"), source.drop(columns="vessel_type"))
    pd.testing.assert_frame_equal(source, before)


def test_whole_vessel_full_mask_never_leaves_a_hidden_cache_label():
    source = history()
    feed = scenario_feed(source, "vessel", 1., 4201)
    assert feed.vessel_type.isna().all() and len(feed) == len(source)


def test_summary_uses_equal_approach_weight_and_unknown_denominator(tmp_path):
    frame = pd.DataFrame({"split": "evaluation", "mode": "report", "fraction": .5,
        "seed": 4201, "approach_id": ["a", "b", "b", "b"], "mmsi": ["1", "2", "2", "2"],
        "decision_id": ["a1", "b1", "b2", "b3"], "original_error": [2., 10., 10., 10.],
        "mitigated_error": [3., 8., 8., 8.], "class_unknown_before": [True, True, False, True],
        "class_recovered": [True, True, False, False]})
    frame["absolute_error_change"] = frame.mitigated_error.abs() - frame.original_error.abs()
    summary = summarize(frame)
    row = summary.iloc[0]
    assert row.original_mae == 6 and row.mitigated_mae == 5.5
    assert row.mae_change == -.5
    assert row.recovery_rate_when_unknown == 2 / 3
    assert row.original_coverage == row.mitigated_coverage == 1
    assert row.improved_approaches == row.worsened_approaches == 1
    write_report(summary, tmp_path)
    assert "1 approaches improved, 1 worsened" in (tmp_path / "REPORT.md").read_text(encoding="utf-8")

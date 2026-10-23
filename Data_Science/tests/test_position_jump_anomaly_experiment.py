"""Anomaly evaluation denominators and causal warning windows."""

import numpy as np
import pandas as pd
import pytest

from experiments.position_jump_anomaly.run import window_counts, summarize


def test_windows_include_boundary_and_current_events_but_never_future_events():
    times = pd.Series(pd.date_range("2024-04-01", periods=3, freq="5min"))
    clocks = pd.Series(pd.to_datetime(["2024-04-01 00:04:00", "2024-04-01 00:05:00", "2024-04-01 00:10:01"]))
    np.testing.assert_array_equal(window_counts(times, np.array([1, 1, 1]), clocks, 5.), [1, 2, 1])
    np.testing.assert_array_equal(window_counts(times.iloc[:0], np.array([], dtype=bool), clocks, 5.), [0, 0, 0])


def test_summary_excludes_unassessed_pairs_and_both_endpoints_define_affected_pair():
    decisions = pd.DataFrame({"split": "evaluation", "mode": "whole_feed", "fraction": .5,
        "seed": 4201, "approach_id": ["a", "a"], "decision_id": ["a0", "a1"],
        "anomaly": [True, False], "affected_window": [True, False], "first_detection_delay_minutes": 1.})
    pairs = pd.DataFrame({"split": "evaluation", "mode": "whole_feed", "fraction": .5,
        "assessed": [True, True, True, False], "affected_pair": [True, True, False, True],
        "flagged": [True, False, False, False]})
    row = summarize(decisions, pairs).iloc[0]
    assert row.assessed_pairs == 3 and row.affected_pairs == 2
    assert row.affected_pair_detection_rate == .5 and row.reference_pair_alert_rate == 0
    assert row.affected_window_alert_rate == 1 and row.decision_alert_rate == .5
    assert row.median_first_detection_delay_minutes == 1 and row.detected_approach_profiles == 1


def test_clean_summary_does_not_invent_detection_or_latency():
    decisions = pd.DataFrame({"split": ["evaluation"], "mode": ["clean"], "fraction": [0.],
        "seed": [0], "approach_id": ["a"], "decision_id": ["a0"], "anomaly": [True],
        "affected_window": [False], "first_detection_delay_minutes": [None]})
    pairs = pd.DataFrame({"split": ["evaluation"], "mode": ["clean"], "fraction": [0.],
        "assessed": [True], "affected_pair": [False], "flagged": [True]})
    row = summarize(decisions, pairs).iloc[0]
    assert pd.isna(row.affected_pair_detection_rate) and pd.isna(row.median_first_detection_delay_minutes)
    assert row.reference_pair_alert_rate == 1 and row.detected_approach_profiles == 0

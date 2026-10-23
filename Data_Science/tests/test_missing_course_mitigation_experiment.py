"""Course experiment uses paired support and the same weighting as speed."""

import pandas as pd
import pytest

from experiments.missing_course_mitigation.run import summarize, write_report


def test_course_summary_uses_equal_approach_weight_and_reports_regressions(tmp_path):
    frame = pd.DataFrame({"split": "evaluation", "fraction": .5,
        "seed": 4201, "approach_id": ["a", "b", "b", "b"], "mmsi": ["1", "2", "2", "2"],
        "decision_id": ["a1", "b1", "b2", "b3"], "original_error": [2., 10., 10., 10.],
        "mitigated_error": [3., 8., 8., 8.], "missing_guarded_reports": 4,
        "estimated_reports": 2, "slow_motion_rejections": 1, "direction_rejections": 0,
        "latest_course_estimated": True})
    frame["absolute_error_change"] = frame.mitigated_error.abs() - frame.original_error.abs()
    summary = summarize(frame)
    row = summary.iloc[0]
    assert row.original_mae == 6 and row.mitigated_mae == 5.5
    assert row.mae_change == pytest.approx(-.5)
    assert row.improved_approaches == row.worsened_approaches == 1
    assert row.reconstruction_rate == .5 and row.slow_motion_rejection_rate == .25
    assert row.original_coverage == row.mitigated_coverage == 1
    write_report(summary, tmp_path)
    report = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
    assert "1 approaches improved, 1 worsened" in report
    assert "Simulated missing-course" in report

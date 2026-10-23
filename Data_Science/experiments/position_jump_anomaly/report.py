"""Render measured warning metrics separately from detector and model logic."""

from pathlib import Path

import pandas as pd


def write_report(summary: pd.DataFrame, validation: dict, output: Path) -> None:
    lines = ["# Position anomaly-only evaluation", "",
        "Simulated disruption of copied AIS positions: mean displacement 2 km, SD 0.2 km. "
        "The detector compares adjacent positions against SOG/COG-implied movement. "
        "It fits no trusted track, changes no features and supplies no replacement observations. "
        "The previous correction estimator, adapter and all its results have been deleted.", "",
        "## Fixed policy", "",
        "The innovation is observed east/north displacement minus the average of endpoint "
        "SOG/COG velocities multiplied by elapsed seconds. Isotropic effective variance is "
        "2*(25 m)^2 + 0.5*(0.5 m/s)^2*dt^2. Score is squared innovation divided by this variance. "
        "Threshold 1.948477151551384 is the vessel-balanced March 99.5th percentile over 25,202 "
        "eligible pairs from 242 approaches / 218 vessels; no April data or ETA labels select it. "
        "The scales are experimental normalizers, not measured sensor specifications. "
        "The empirical threshold is not a calibrated probability of bad GPS.", "",
        "Pairs over 120 seconds apart or with unavailable velocity are unassessed. "
        "Invalid/missing coordinates and conflicting same-time positions warn separately. "
        "Warnings persist while flagged evidence is within the past five minutes, then expire. "
        "Silence is handled independently by the existing gap detector. No alert does not certify "
        "correct navigation or ETA.", ""]
    for split, title in (("validation", "March development"), ("evaluation", "April follow-up")):
        lines += [f"## {title}", "",
            "All attacked settings use seeds 4201-4203; rows pool scenario/decision or pair counts. "
            "A separate 100% burst starts after 20 minutes and lasts 15 minutes. "
            "Affected pair means EITHER endpoint injected; unassessed pairs are excluded from pair rates. "
            "An affected decision window contains an affected pair ending within the last five minutes.", "",
            "| Scenario | Selected | Assessed affected pairs flagged | Affected windows warned | Unmodified pair alert rate | All decision alert rate |",
            "|---|---:|---:|---:|---:|---:|"]
        for row in summary.loc[summary.split.eq(split)].itertuples():
            affected = f"{row.affected_pair_detection_rate:.2%}" if pd.notna(row.affected_pair_detection_rate) else "n/a"
            windows = f"{row.affected_window_alert_rate:.2%}" if pd.notna(row.affected_window_alert_rate) else "n/a"
            reference = f"{row.reference_pair_alert_rate:.2%}" if pd.notna(row.reference_pair_alert_rate) else "n/a"
            lines.append(f"| {row.mode} | {row.fraction:.0%} | {affected} | {windows} | {reference} | {row.decision_alert_rate:.2%} |")
        lines.append("")
    case = validation["saved_model_failure_case"]
    lines += ["## ETA behavior and regression", "",
        "All A/B/C inference frames and cards remain unchanged when enabling the detector, "
        "including point estimates, forecast availability and interval metadata. This is "
        "warning-only risk handling: it does not remove corruption or improve underlying ETA MAE/MdAE. "
        "A full ETA accuracy rerun was not performed for every corruption setting because warnings "
        "supply no model features. Complete-frame unit assertions and the saved-model regression "
        "check validate prediction invariance.", "",
        f"The prior severe failure was replayed on saved models: `{case['decision_id']}`, seed 4203, "
        f"50% corruption. Warning triggered: {case['position_warning_triggered']}. "
        f"C's absolute error remains {case['C_absolute_error_minutes']:.6f} minutes with warnings both off and on. "
        "No attempted correction introduces the former 256-minute error. Source reports, original "
        "reference arrivals and all A/B/C cards match exactly.", "",
        "## Detection limits", "",
        "Unmodified-pair and clean-feed alerts are false-alarm proxies, not proof of accurate GPS: "
        "legitimate maneuvers, SOG/COG errors or motion approximations can cause disagreement. "
        "The warning does not determine which endpoint or sensor is wrong. No causal poisoning "
        "claim is made about source AIS records.", "",
        "At 100%, the tested distances vary randomly around 2 km, creating detectable inconsistency. "
        "A coherent fixed offset present from the first report can remain invisible; a unit test "
        "explicitly demonstrates this limit. Unsupported intervals are not counted as successfully checked. "
        "April was previously inspected and is a follow-up cohort, not a pristine holdout.", "",
        "All 336 approach/seed profiles in each attacked April setting had an affected-pair "
        "detection before the last scheduled forecast. Median first-pair detection delay was zero "
        "minutes: this measures observation-time detection among detected profiles, starting at "
        "the first affected eligible PAIR, not the first corrupted standalone report. It does not "
        "measure HTTP polling, frontend notification or scheduled-decision latency.", "",
        "## Validation", "",
        f"{validation['prefix_checks']:,} independent public-detector first/last prefix checks matched "
        "the in-order adjacent-pair replay. Truth labels join only after observable decisions. "
        f"{validation['protected_files']} protected data/model/other-mitigation/attack/frontend files "
        f"have unchanged hashes: {validation['protected_hashes_unchanged']}. "
        f"Implementation unchanged during run: {validation['implementation_unchanged_during_run']}. "
        f"Elapsed: {validation['elapsed_seconds']:.1f} seconds.", "",
        "See tests.json for test commands and totals. CSV outputs remain local and ignored. "
        "Reproduce with `python experiments/position_jump_anomaly/run.py`."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

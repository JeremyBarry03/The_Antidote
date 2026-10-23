"""Fixed-policy course reconstruction stress test on the existing frozen Model C."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import MissingCourseAttack, MissingCourseConfig as AttackConfig
from eta_baselines.dataset import file_digest
from experiments.missing_speed_mitigation.run import FRACTIONS, SEEDS, SETTINGS, metrics, paired_change, score
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import load_systems
from Optimized_Model.features import OptimizedFeatures
from mitigation.missing_course_mitigation import CourseStatus, MissingCourseConfig, MissingCourseMitigation
from mitigation.missing_course_mitigation.optimized_model import COURSE_FEATURES, missing_course_snapshot

POLICY = MissingCourseConfig()


def approach_views(task: tuple) -> tuple[list[dict], list[dict], list[dict]]:
    baseline, guard_config, history, decisions = task
    extractor = OptimizedFeatures(baseline, guard_config)
    mitigation = MissingCourseMitigation(baseline.gate, POLICY)
    original_rows, mitigated_rows, metadata = [], [], []
    before = history.copy(deep=True)
    for fraction, seed in SETTINGS:
        stream = MissingCourseAttack(AttackConfig(affected_fraction=fraction, seed=seed)).apply(history)
        for _, decision in decisions.iterrows():
            snapshot = missing_course_snapshot(stream.available(decision.decision_time),
                                               decision.decision_time, extractor, mitigation)
            original, mitigated = snapshot.original_features, snapshot.mitigated_features
            assert original.empty == mitigated.empty
            for column in original:
                if column not in COURSE_FEATURES:
                    pd.testing.assert_series_equal(original[column], mitigated[column])
            original_rows.append(original.iloc[0].to_dict() if len(original) else {})
            mitigated_rows.append(mitigated.iloc[0].to_dict() if len(mitigated) else {})
            metadata.append({key: decision[key] for key in
                             ("approach_id", "mmsi", "decision_id", "decision_time", "arrival_time", "split")}
                            | {"fraction": fraction, "seed": seed, "supported": bool(len(original)),
                               "missing_guarded_reports": len(snapshot.repair.audit),
                               "estimated_reports": sum(row.status == CourseStatus.ESTIMATED for row in snapshot.repair.audit),
                               "unsupported_reports": sum(row.status == CourseStatus.UNSUPPORTED for row in snapshot.repair.audit),
                               "slow_motion_rejections": sum("insufficient_motion_for_course" in row.reasons
                                                             for row in snapshot.repair.audit),
                               "direction_rejections": sum("inconsistent_recent_direction" in row.reasons
                                                           for row in snapshot.repair.audit),
                               "latest_course_estimated": any(
                                   row.status == CourseStatus.ESTIMATED and row.observation_time == original.observation_time.iloc[0]
                                   for row in snapshot.repair.audit) if len(original) else False})
        unchanged = [name for name in history if name != "cog"]
        pd.testing.assert_frame_equal(history[unchanged].sort_values("time").reset_index(drop=True),
                                      stream.reports[unchanged].reset_index(drop=True))
    pd.testing.assert_frame_equal(history, before)
    return original_rows, mitigated_rows, metadata


def summarize(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, fraction), group in predictions.groupby(["split", "fraction"]):
        row = {"split": split, "fraction": fraction, "seeds": group.seed.nunique(),
               "approaches": group.approach_id.nunique(), "decisions": group.decision_id.nunique(),
               "prediction_pairs": len(group)}
        for arm in ("original", "mitigated"):
            row.update({f"{arm}_{name}": value for name, value in metrics(group, f"{arm}_error").items()})
        row.update(paired_change(group))
        missing = group.missing_guarded_reports.sum()
        row["reconstruction_rate"] = group.estimated_reports.sum() / missing if missing else 0.
        row["slow_motion_rejection_rate"] = group.slow_motion_rejections.sum() / missing if missing else 0.
        row["direction_rejection_rate"] = group.direction_rejections.sum() / missing if missing else 0.
        row["decisions_with_reconstruction"] = float(group.estimated_reports.gt(0).mean())
        row["latest_course_reconstruction_share"] = float(group.latest_course_estimated.mean())
        delta = group.groupby("approach_id").absolute_error_change.mean()
        row["improved_approaches"] = int(delta.lt(-1e-10).sum())
        row["worsened_approaches"] = int(delta.gt(1e-10).sum())
        row["unchanged_approaches"] = int(delta.abs().le(1e-10).sum())
        row["worst_approach_mae_change"] = float(delta.max())
        rows.append(row)
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, output: Path, predictions: pd.DataFrame | None = None) -> None:
    lines = ["# MissingCourseMitigation on frozen optimized XGBoost", "",
        "Simulated missing-course corruption on original AIS histories. No model retraining or forced degradation. "
        "Negative paired MAE change favors mitigation. Poly and ordinary XGBoost remain unchanged.", "",
        "Course is atan2(east velocity, north velocity), converted to degrees and wrapped into [0,360). "
        "It uses the same five-minute causal position fit and checks as Missing Speed. Extra fixed settings: "
        "at least one knot for fitted and segment motion, 30 m net displacement, and no segment direction "
        "more than 20 degrees from the fitted direction. These are provisional settings fixed before evaluation. "
        "Stopped or ambiguous tracks retain missing course. Existing 0-degree courses remain valid north.", "",
        "The existing C guard runs first. Only course sine/cosine, course dispersion, recent turn, and "
        "velocity disagreement may change. Observed missing-course fraction, all speed/position features, "
        "clocks and guard diagnostics remain intact. Model inputs never contain hidden originals, attack "
        "flags, audit records or crossing labels.", ""]
    for split, title in (("validation", "March development"), ("evaluation", "April follow-up evaluation")):
        lines += [f"## {title}", "",
            "| Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Reconstructed missing bins |",
            "|---:|---:|---:|---:|---:|---|---:|---:|"]
        for row in summary.loc[summary.split.eq(split)].itertuples():
            lines.append(f"| {row.fraction:.0%} | {row.original_mae:.4f} | {row.mitigated_mae:.4f} | "
                f"{row.original_mdae:.4f} | {row.mitigated_mdae:.4f} | "
                f"{row.mae_change:+.4f} [{row.ci_low:+.4f}, {row.ci_high:+.4f}] | "
                f"{row.mitigated_coverage:.2%} | {row.reconstruction_rate:.2%} |")
        lines.append("")
    lines += ["MAE weights approaches equally, with seeds averaged within approach. MdAE/P95 pool absolute "
        "errors over decision/seed pairs. Both arms use identical decisions, support and original crossing "
        "targets. Reconstruction rate counts missing guarded bins repeated across decision windows, not "
        "unique raw reports. Partial masking uses seeds 4201–4203; full masking is seed-independent and runs once.", "",
        "## Variation across April approaches", ""]
    for row in summary.loc[summary.split.eq("evaluation") & summary.fraction.gt(0)].itertuples():
        lines.append(f"At {row.fraction:.0%} masking: {row.improved_approaches} approaches improved, "
            f"{row.worsened_approaches} worsened and {row.unchanged_approaches} were unchanged. "
            f"Worst approach mean change: {row.worst_approach_mae_change:+.4f} minutes.")
    if predictions is not None:
        evaluation = predictions.loc[predictions.split.eq("evaluation")]
        full = evaluation.loc[evaluation.fraction.eq(1)].copy()
        clean = evaluation.loc[evaluation.fraction.eq(0)].copy()
        clean["clean_ae"] = clean.original_error.abs()
        full["attacked_ae"] = full.original_error.abs()
        full["mitigated_ae"] = full.mitigated_error.abs()
        comparison = full.groupby(["approach_id", "mmsi"])[["attacked_ae", "mitigated_ae"]].mean()
        comparison = comparison.join(clean.groupby(["approach_id", "mmsi"]).clean_ae.mean())
        comparison["change_vs_attacked"] = comparison.mitigated_ae - comparison.attacked_ae
        comparison.reset_index().to_csv(output / "approach_summary.csv", index=False)
        lines += ["", "## Largest full-mask regressions compared with clean C", "",
            "| MMSI | Clean C MAE | Missing-course C MAE | Mitigated C MAE |",
            "|---|---:|---:|---:|"]
        for row in comparison.nlargest(2, "change_vs_attacked").reset_index().itertuples():
            lines.append(f"| {row.mmsi} | {row.clean_ae:.4f} | {row.attacked_ae:.4f} | {row.mitigated_ae:.4f} |")
        lines += ["", "These are the largest regressions relative to the attacked feed. Comparing them "
            "with clean C also exposes pre-existing model errors: restoring a useful feature can restore "
            "an existing prediction mistake. Removing information can occasionally improve a flawed model. "
            "The actual harmed cases remain in all metrics; these examples do not excuse their regressions."]
    lines += ["", "Direction from a trailing fit is recent average course, not independently verified "
        "instantaneous course over ground; bow heading is not reconstructed. Coherent GPS errors or unobserved turns can still defeat it. The selected "
        "cohort's clean missingness and control changes are recorded in the table; clean identity alone "
        "does not validate reconstruction on naturally missing records. Model trees and imputer are unchanged; "
        "existing missing indicators generated by the imputer follow the effective numeric features. "
        "Original missing-course fraction is preserved, but uncertainty is not calibrated for this new path.", "",
        "April was inspected previously and is a follow-up cohort, not a pristine holdout. Stress rates "
        "are proposed simulated settings, not measured real-world failure rates. Arrival means the analytical "
        "crossing, not docking. Full P95 and per-decision diagnostics are saved as locally ignored CSVs.", "",
        "Missing Speed's old prediction file is read-only during regression checking. Its full saved "
        "cohort and reconstruction counts must match before this experiment is allowed to run. See speed_regression.json.", "",
        "Reproduce from Data_Science: `python experiments/missing_course_mitigation/check_speed_regression.py`, "
        "then `python experiments/missing_course_mitigation/run.py`."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    regression = json.loads((output / "speed_regression.json").read_text())
    assert regression["passed"]
    assert all(file_digest(Path(path)) == digest for path, digest in regression["implementation_hashes"].items())
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    predictor = next(system.predictor for system in load_systems(config) if system.name == "C")
    protected = [config.baseline.input_csv, config.later_csv, config.output_directory / "replay_dataset.joblib",
        *config.output_directory.joinpath("models").glob("*.joblib"),
        config.frozen_baseline_model("quadratic"), config.frozen_baseline_model("xgboost"),
        SCIENCE / "Optimized_Model/features.py", SCIENCE / "Optimized_Model/quality.py",
        SCIENCE / "Optimized_Model/model.py", SCIENCE / "eta_baselines/prediction.py",
        SCIENCE / "experiments/missing_speed_mitigation/results/predictions.csv"]
    hashes = {str(path): file_digest(path) for path in protected}
    protocol = {"model": "C / frozen optimized XGBoost", "mitigation": asdict(POLICY),
        "fractions": FRACTIONS, "seeds": SEEDS, "full_mask": "Seed-invariant; once", "training": "None",
        "policy_selection": "Fixed before March/April evaluation; no threshold search",
        "arms": ["original C", "original C+mitigation", "attacked C", "attacked C+mitigation"],
        "scoring": "Same score, MAE/MdAE/P95 and paired vessel-cluster bootstrap helpers as missing-speed experiment",
        "protected_hashes_before": hashes,
        "limits": "Simulated disruption; previously inspected April follow-up; analytical crossing, not docking."}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    predictions = []
    for split in ("validation", "evaluation"):
        decisions = dataset.partition(split).sort_values(["approach_id", "decision_time"])
        tasks = [(config.baseline, config.guard, dataset.histories[identity], group)
                 for identity, group in decisions.groupby("approach_id", sort=False)]
        originals, mitigated, metadata = [], [], []
        print(f"Course {split}: {len(tasks)} approaches / {len(decisions)} decisions", flush=True)
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(approach_views, task) for task in tasks]
            for completed, future in enumerate(as_completed(futures), 1):
                original, repaired, meta = future.result()
                originals.extend(original)
                mitigated.extend(repaired)
                metadata.extend(meta)
                if completed % 12 == 0 or completed == len(tasks):
                    print(f"  {completed}/{len(tasks)}", flush=True)
        frame = pd.DataFrame(metadata)
        frame["original_error"] = score(originals, frame, predictor)
        frame["mitigated_error"] = score(mitigated, frame, predictor)
        frame["absolute_error_change"] = frame.mitigated_error.abs() - frame.original_error.abs()
        assert not frame.duplicated(["decision_id", "fraction", "seed"]).any()
        assert frame.groupby(["fraction", "seed"]).size().eq(len(decisions)).all()
        predictions.append(frame)
    predictions = pd.concat(predictions, ignore_index=True)
    summary = summarize(predictions)
    assert {str(path): file_digest(path) for path in protected} == hashes
    clean = summary.loc[summary.split.eq("evaluation") & summary.fraction.eq(0)].iloc[0]
    assert abs(clean.original_mae - 5.85976006005499) < 1e-6
    assert np.array_equal(predictions.original_error.notna(), predictions.mitigated_error.notna())
    predictions.to_csv(output / "predictions.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    validation = {"protected_hashes_unchanged": True, "original_C_baseline_reproduced": True,
        "missing_speed_regression_passed": True, "missing_speed_saved_results_unchanged": True,
        "same_support_and_decision_times": True, "no_source_report_mutation": True,
        "only_course_features_changed": True, "observed_missingness_clocks_and_speed_preserved": True,
        "truth_and_audit_excluded_from_predictor_inputs": True, "no_retraining_or_frontend_edits": True,
        "evaluation_approaches": int(clean.approaches), "evaluation_decisions": int(clean.decisions),
        "elapsed_seconds": time.perf_counter() - started}
    (output / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    write_report(summary, output, predictions)
    print(summary.to_string(index=False), flush=True)
    print(f"Completed in {validation['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

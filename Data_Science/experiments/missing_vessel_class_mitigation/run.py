"""Frozen-C test of causal class carry-forward, with cold and legitimate warm history."""

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

from attacks import MissingVesselClassAttack, MissingVesselClassConfig as AttackConfig
from eta_baselines.dataset import file_digest
from experiments.missing_speed_mitigation.run import FRACTIONS, SEEDS, metrics, paired_change, score
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import load_systems
from Optimized_Model.features import OptimizedFeatures
from mitigation.missing_vessel_class_mitigation import (
    MissingVesselClassMitigation, MissingVesselClassMitigationConfig, VesselClassStatus,
)
from mitigation.missing_vessel_class_mitigation.optimized_model import vessel_class_snapshot

POLICY = MissingVesselClassMitigationConfig()
CLASS_FEATURES = ("is_cargo", "is_tanker", "vessel_class_unknown")
SETTINGS = [("clean", 0., 0), *[(unit, fraction, seed) for unit in ("report", "vessel")
    for fraction in FRACTIONS for seed in (SEEDS if fraction < 1 else SEEDS[:1])],
    ("warm_dropout", 1., 0)]
WARMUP_MINUTES = 10


def scenario_feed(history: pd.DataFrame, mode: str, fraction: float, seed: int) -> pd.DataFrame:
    """Class-dropout onset is fixed by observed entry time, never outcomes/errors."""
    if mode == "warm_dropout":
        feed = history.copy(deep=True)
        onset = feed.time.min() + pd.Timedelta(minutes=WARMUP_MINUTES)
        feed.loc[feed.time.ge(onset), "vessel_type"] = np.nan
        return feed
    return MissingVesselClassAttack(AttackConfig(
        affected_fraction=fraction, seed=seed, selection_unit="report" if mode == "clean" else mode)).apply(history).reports


def approach_views(task: tuple) -> tuple[list[dict], list[dict], list[dict]]:
    baseline, guard_config, history, decisions = task
    extractor = OptimizedFeatures(baseline, guard_config)
    mitigation = MissingVesselClassMitigation(POLICY)
    original_rows, mitigated_rows, metadata = [], [], []
    before = history.copy(deep=True)
    for mode, fraction, seed in SETTINGS:
        feed = scenario_feed(history, mode, fraction, seed)
        for _, decision in decisions.iterrows():
            snapshot = vessel_class_snapshot(feed, decision.decision_time, extractor, mitigation)
            original, mitigated = snapshot.original_features, snapshot.mitigated_features
            assert original.empty == mitigated.empty
            for column in original:
                if column not in CLASS_FEATURES:
                    pd.testing.assert_series_equal(original[column], mitigated[column])
            original_rows.append(original.iloc[0].to_dict() if len(original) else {})
            mitigated_rows.append(mitigated.iloc[0].to_dict() if len(mitigated) else {})
            metadata.append({key: decision[key] for key in
                ("approach_id", "mmsi", "decision_id", "decision_time", "arrival_time", "split")}
                | {"mode": mode, "fraction": fraction, "seed": seed, "supported": bool(len(original)),
                   "class_unknown_before": bool(original.vessel_class_unknown.iloc[0]) if len(original) else False,
                   "class_recovered": (snapshot.mitigation.status == VesselClassStatus.RECOVERED
                                       and bool(original.vessel_class_unknown.iloc[0])) if len(original) else False,
                   "all_supplied_types_missing": bool(feed.vessel_type.isna().all()),
                   "evidence_count": snapshot.mitigation.evidence_count,
                   "reason": "|".join(snapshot.mitigation.reasons)})
        unchanged = [name for name in history if name != "vessel_type"]
        pd.testing.assert_frame_equal(history[unchanged].sort_values("time").reset_index(drop=True),
                                      feed[unchanged].sort_values("time").reset_index(drop=True))
    pd.testing.assert_frame_equal(history, before)
    return original_rows, mitigated_rows, metadata


def summarize(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, mode, fraction), group in predictions.groupby(["split", "mode", "fraction"]):
        row = {"split": split, "mode": mode, "fraction": fraction, "seeds": group.seed.nunique(),
               "approaches": group.approach_id.nunique(), "decisions": group.decision_id.nunique(),
               "prediction_pairs": len(group)}
        for arm in ("original", "mitigated"):
            row.update({f"{arm}_{name}": value for name, value in metrics(group, f"{arm}_error").items()})
        row.update(paired_change(group))
        unknown = int(group.class_unknown_before.sum())
        row["unknown_decisions"] = unknown
        row["recovered_decisions"] = int(group.class_recovered.sum())
        row["recovery_rate_when_unknown"] = group.class_recovered.sum() / unknown if unknown else 0.
        delta = group.groupby("approach_id").absolute_error_change.mean()
        row["improved_approaches"] = int(delta.lt(-1e-10).sum())
        row["worsened_approaches"] = int(delta.gt(1e-10).sum())
        row["unchanged_approaches"] = int(delta.abs().le(1e-10).sum())
        row["worst_approach_mae_change"] = float(delta.max())
        rows.append(row)
    return pd.DataFrame(rows)


def selection_audit(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, mode, fraction, seed), group in predictions.groupby(["split", "mode", "fraction", "seed"]):
        absent = group.loc[group.all_supplied_types_missing]
        rows.append({"split": split, "mode": mode, "fraction": fraction, "seed": seed,
                     "scheduled_vessels": group.mmsi.nunique(),
                     "all_class_missing_vessels": absent.mmsi.nunique(),
                     "scheduled_approaches": group.approach_id.nunique(),
                     "all_class_missing_approaches": absent.approach_id.nunique()})
    return pd.DataFrame(rows)


def write_report(summary: pd.DataFrame, output: Path) -> None:
    lines = ["# MissingVesselClassMitigation on frozen optimized XGBoost", "",
        "Simulated loss of vessel classification on original AIS histories. The model is unchanged; "
        "only the existing cargo/tanker/unknown flags may be recovered. Every AIS row remains available. "
        "Negative paired MAE change favors mitigation.", "",
        "The fixed policy requires three distinct earlier reports agreeing on a supported broad class "
        "inside a 60-minute history window. No history, stale evidence, conflicts, and unsupported classes "
        "remain unknown. The cache is rebuilt solely from each scenario's received history. Hidden clean "
        "classifications never initialize it, and exact AIS subtypes are not invented.", "",
        "Cold report masking tests missing individual labels. Cold whole-vessel masking removes all class "
        "evidence for deterministically selected MMSIs, so no recovery is possible for those vessels. "
        "The separate warm-dropout case retains legitimately received class labels during the first "
        f"{WARMUP_MINUTES} minutes after the first observation and masks types thereafter. The onset is "
        "fixed independently of prediction errors and crossing outcomes. Warm evidence can expire under "
        "the same fixed policy; recording the pre-dropout history does not provide future class labels.", ""]
    for split, title in (("validation", "March development"), ("evaluation", "April follow-up evaluation")):
        lines += [f"## {title}", "",
            "| Mode | Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Unknown decisions recovered |",
            "|---|---:|---:|---:|---:|---:|---|---:|---:|"]
        for row in summary.loc[summary.split.eq(split)].itertuples():
            lines.append(f"| {row.mode} | {row.fraction:.0%} | {row.original_mae:.4f} | {row.mitigated_mae:.4f} | "
                f"{row.original_mdae:.4f} | {row.mitigated_mdae:.4f} | "
                f"{row.mae_change:+.4f} [{row.ci_low:+.4f}, {row.ci_high:+.4f}] | "
                f"{row.mitigated_coverage:.2%} | {row.recovery_rate_when_unknown:.2%} |")
        lines.append("")
    lines += ["MAE gives approaches equal weight, averaging mask seeds within approach. MdAE and P95 "
        "pool absolute errors over decision/seed pairs. The paired interval resamples vessels 1,000 times. "
        "Both arms use identical decisions, original crossing labels and support. Partial cold masks use "
        "seeds 4201–4203; full masks are seed-invariant and run once. Warm dropout has no random seed. "
        "Mask fractions are selection probabilities, not guaranteed exact cohort percentages. "
        "Selection counts per seed are recorded in selection_audit.csv; a small cohort may select no vessel.", "",
        "## April variation across approaches", ""]
    for row in summary.loc[summary.split.eq("evaluation") & summary["mode"].ne("clean")].itertuples():
        lines.append(f"{row.mode}, {row.fraction:.0%}: {row.improved_approaches} approaches improved, "
            f"{row.worsened_approaches} worsened, {row.unchanged_approaches} were unchanged. "
            f"Worst approach mean change: {row.worst_approach_mae_change:+.4f} minutes.")
    lines += ["", "This does not infer vessel class from speed, position, future labels or vessel identity "
        "alone. Consistent history can still be consistently wrong; the policy is not a verified vessel "
        "registry or a defense against MMSI spoofing. Missing type never defaults to cargo. Recovering "
        "classification may have little ETA effect if C makes little use of those features. Actual changes "
        "are reported without forcing degradation or improvement.", "",
        "Stress rates are proposed experimental settings, not observed source failure rates. April has "
        "been inspected previously and is a follow-up cohort, not a pristine holdout. Arrival means the "
        "analytical crossing, not verified docking. The prepared cargo/tanker cohort was selected before "
        "masking, so this does not establish recovery of unknown-type vessels excluded upstream or an "
        "enrollment-coverage gain. No retraining or frontend edits. Source/model and earlier "
        "speed/course result hashes remain unchanged. P95, reasons and individual decisions are saved in "
        "locally ignored CSVs.", "",
        "Reproduce from Data_Science: `python experiments/missing_vessel_class_mitigation/run.py`."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    predictor = next(system.predictor for system in load_systems(config) if system.name == "C")
    protected = [config.baseline.input_csv, config.later_csv, config.output_directory / "replay_dataset.joblib",
        *config.output_directory.joinpath("models").glob("*.joblib"),
        config.frozen_baseline_model("quadratic"), config.frozen_baseline_model("xgboost"),
        SCIENCE / "Optimized_Model/features.py", SCIENCE / "Optimized_Model/quality.py",
        SCIENCE / "Optimized_Model/model.py", SCIENCE / "eta_baselines/prediction.py",
        SCIENCE / "experiments/missing_speed_mitigation/results/predictions.csv",
        SCIENCE / "experiments/missing_course_mitigation/results/predictions.csv"]
    hashes = {str(path): file_digest(path) for path in protected}
    protocol = {"model": "C / frozen optimized XGBoost", "mitigation": asdict(POLICY),
        "fractions": FRACTIONS, "seeds": SEEDS, "cold_modes": ["report", "vessel"],
        "warm_dropout_onset_minutes_after_first_observation": WARMUP_MINUTES,
        "full_mask": "Seed-independent; once", "training": "None",
        "policy_selection": "Fixed before March/April evaluation; no threshold search",
        "cache": "Scenario-local received history only; never initialized from clean hidden labels",
        "scoring": "Same scoring/MAE/MdAE/P95 and paired vessel bootstrap helpers as Missing Speed",
        "protected_hashes_before": hashes,
        "limitations": "Simulated corruption; previously inspected April follow-up; analytical crossing, not docking."}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    predictions = []
    for split in ("validation", "evaluation"):
        decisions = dataset.partition(split).sort_values(["approach_id", "decision_time"])
        tasks = [(config.baseline, config.guard, dataset.histories[identity], group)
                 for identity, group in decisions.groupby("approach_id", sort=False)]
        originals, mitigated, metadata = [], [], []
        print(f"Vessel class {split}: {len(tasks)} approaches / {len(decisions)} decisions", flush=True)
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
        assert not frame.duplicated(["decision_id", "mode", "fraction", "seed"]).any()
        assert frame.groupby(["mode", "fraction", "seed"]).size().eq(len(decisions)).all()
        predictions.append(frame)
    predictions = pd.concat(predictions, ignore_index=True)
    summary = summarize(predictions)
    assert {str(path): file_digest(path) for path in protected} == hashes
    clean = summary.loc[summary.split.eq("evaluation") & summary["mode"].eq("clean")].iloc[0]
    assert abs(clean.original_mae - 5.85976006005499) < 1e-6
    assert np.array_equal(predictions.original_error.notna(), predictions.mitigated_error.notna())
    cold_vessels = predictions.loc[predictions["mode"].eq("vessel") & predictions.all_supplied_types_missing]
    assert not cold_vessels.class_recovered.any()
    np.testing.assert_allclose(cold_vessels.original_error, cold_vessels.mitigated_error,
                               rtol=0, atol=1e-9, equal_nan=True)
    full_report = predictions.loc[predictions["mode"].eq("report") & predictions.fraction.eq(1)]
    assert not full_report.class_recovered.any()
    predictions.to_csv(output / "predictions.csv", index=False)
    selection_audit(predictions).to_csv(output / "selection_audit.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    validation = {"protected_hashes_unchanged": True, "original_C_baseline_reproduced": True,
        "old_speed_and_course_results_unchanged": True, "same_support_and_decision_times": True,
        "no_source_report_mutation": True, "only_class_features_changed": True,
        "truth_and_audit_excluded_from_predictor_inputs": True,
        "cold_whole_vessel_cache_never_recovers_unseen_labels": True,
        "full_report_mask_never_recovers_unseen_labels": True,
        "warm_cache_contains_only_received_pre_dropout_labels": True,
        "evaluation_approaches": int(clean.approaches), "evaluation_decisions": int(clean.decisions),
        "elapsed_seconds": time.perf_counter() - started}
    (output / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    write_report(summary, output)
    print(summary.to_string(index=False), flush=True)
    print(f"Completed in {validation['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

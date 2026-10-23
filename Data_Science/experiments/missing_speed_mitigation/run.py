"""Paired inference-only robustness test for C plus causal speed reconstruction."""

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

from attacks import MissingSpeedAttack, MissingSpeedConfig as AttackConfig
from eta_baselines.dataset import file_digest
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import load_systems
from Optimized_Model.features import OPTIMIZED_COLUMNS, OptimizedFeatures
from mitigation.missing_speed_mitigation import MissingSpeedConfig, MissingSpeedMitigation, SpeedStatus
from mitigation.missing_speed_mitigation.optimized_model import SPEED_FEATURES, missing_speed_snapshot

SEEDS = (4201, 4202, 4203)
FRACTIONS = (.1, .25, .5, 1.)
SETTINGS = [(0., 0), *[(fraction, seed) for fraction in FRACTIONS
                                  for seed in (SEEDS if fraction < 1 else SEEDS[:1])]]
POLICY = MissingSpeedConfig()


def approach_views(task: tuple) -> tuple[list[dict], list[dict], list[dict]]:
    baseline, guard_config, history, decisions = task
    extractor = OptimizedFeatures(baseline, guard_config)
    mitigation = MissingSpeedMitigation(baseline.gate, POLICY)
    original_rows, mitigated_rows, metadata = [], [], []
    before = history.copy(deep=True)
    for fraction, seed in SETTINGS:
        stream = MissingSpeedAttack(AttackConfig(affected_fraction=fraction, seed=seed)).apply(history)
        for _, decision in decisions.iterrows():
            snapshot = missing_speed_snapshot(stream.available(decision.decision_time),
                                              decision.decision_time, extractor, mitigation)
            original = snapshot.original_features
            mitigated = snapshot.mitigated_features
            assert original.empty == mitigated.empty
            for column in original:
                if column not in SPEED_FEATURES:
                    pd.testing.assert_series_equal(original[column], mitigated[column])
            original_rows.append(original.iloc[0].to_dict() if len(original) else {})
            mitigated_rows.append(mitigated.iloc[0].to_dict() if len(mitigated) else {})
            metadata.append({key: decision[key] for key in
                             ("approach_id", "mmsi", "decision_id", "decision_time", "arrival_time", "split")}
                            | {"fraction": fraction, "seed": seed, "supported": bool(len(original)),
                               "missing_guarded_reports": len(snapshot.repair.audit),
                               "estimated_reports": sum(row.status == SpeedStatus.ESTIMATED for row in snapshot.repair.audit),
                               "unsupported_reports": sum(row.status == SpeedStatus.UNSUPPORTED for row in snapshot.repair.audit),
                               "latest_speed_estimated": any(
                                   row.status == SpeedStatus.ESTIMATED and row.observation_time == original.observation_time.iloc[0]
                                   for row in snapshot.repair.audit) if len(original) else False})
        unchanged = [name for name in history if name != "sog"]
        pd.testing.assert_frame_equal(history[unchanged].sort_values("time").reset_index(drop=True),
                                      stream.reports[unchanged].reset_index(drop=True))
    pd.testing.assert_frame_equal(history, before)
    return original_rows, mitigated_rows, metadata


def score(rows: list[dict], metadata: pd.DataFrame, predictor) -> np.ndarray:
    """Only model features/clocks enter inference; outcomes are scored afterward."""
    supported = metadata.supported.to_numpy(dtype=bool)
    errors = np.full(len(metadata), np.nan)
    if supported.any():
        inputs = pd.DataFrame(rows).reindex(columns=[*OPTIMIZED_COLUMNS, "observation_time", "decision_time"])
        predictions = predictor.predict(inputs.loc[supported])
        errors[supported] = ((predictions.predicted_arrival_time.to_numpy()
                              - metadata.loc[supported, "arrival_time"].to_numpy())
                             / np.timedelta64(1, "m"))
    return errors


def metrics(frame: pd.DataFrame, column: str) -> dict[str, float]:
    valid = frame.loc[np.isfinite(frame[column])]
    absolute = valid[column].abs()
    per_approach = valid.assign(ae=absolute).groupby("approach_id").ae.mean()
    return {"mae": float(per_approach.mean()), "mdae": float(absolute.median()),
            "p95": float(absolute.quantile(.95)), "coverage": len(valid) / len(frame) if len(frame) else 0.}


def paired_change(frame: pd.DataFrame) -> dict[str, float]:
    common = frame.loc[np.isfinite(frame.original_error) & np.isfinite(frame.mitigated_error)].copy()
    if common.empty:
        return {"paired_decisions": 0, "mae_change": float("nan"), "ci_low": float("nan"), "ci_high": float("nan")}
    common["delta"] = common.mitigated_error.abs() - common.original_error.abs()
    per = common.groupby(["mmsi", "approach_id"]).delta.mean().reset_index()
    clusters = [group.delta.to_numpy() for _, group in per.groupby("mmsi")]
    rng = np.random.default_rng(42)
    bootstrap = [np.concatenate([clusters[index] for index in rng.integers(len(clusters), size=len(clusters))]).mean()
                 for _ in range(1000)]
    low, high = np.quantile(bootstrap, [.025, .975])
    return {"paired_decisions": len(common), "mae_change": float(per.delta.mean()),
            "ci_low": float(low), "ci_high": float(high)}


def summarize(predictions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, fraction), group in predictions.groupby(["split", "fraction"]):
        row = {"split": split, "fraction": fraction, "seeds": group.seed.nunique(),
               "approaches": group.approach_id.nunique(), "decisions": group.decision_id.nunique(),
               "prediction_pairs": len(group)}
        for arm in ("original", "mitigated"):
            row.update({f"{arm}_{name}": value for name, value in metrics(group, f"{arm}_error").items()})
        row.update(paired_change(group))
        row["reconstruction_rate"] = (group.estimated_reports.sum() / group.missing_guarded_reports.sum()
                                      if group.missing_guarded_reports.sum() else 0.)
        row["decisions_with_reconstruction"] = float(group.estimated_reports.gt(0).mean())
        row["latest_speed_reconstruction_share"] = float(group.latest_speed_estimated.mean())
        delta = group.groupby("approach_id").absolute_error_change.mean()
        row["improved_approaches"] = int(delta.lt(-1e-10).sum())
        row["worsened_approaches"] = int(delta.gt(1e-10).sum())
        row["unchanged_approaches"] = int(delta.abs().le(1e-10).sum())
        row["worst_approach_mae_change"] = float(delta.max())
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    systems = load_systems(config)
    predictor = next(system.predictor for system in systems if system.name == "C")
    protected = [config.baseline.input_csv, config.later_csv,
                 config.output_directory / "replay_dataset.joblib",
                 *config.output_directory.joinpath("models").glob("*.joblib"),
                 config.frozen_baseline_model("quadratic"), config.frozen_baseline_model("xgboost"),
                 SCIENCE / "Optimized_Model/features.py", SCIENCE / "Optimized_Model/quality.py",
                 SCIENCE / "Optimized_Model/model.py", SCIENCE / "eta_baselines/prediction.py"]
    hashes = {str(path): file_digest(path) for path in protected}
    protocol = {"model": "C / frozen optimized XGBoost", "config": str(config.baseline.input_csv),
                "mitigation": asdict(POLICY), "fractions": FRACTIONS, "seeds": SEEDS,
                "full_mask": "Seed-independent; run once", "training": "None",
                "arms": ["original C", "original C+mitigation", "attacked C", "attacked C+mitigation"],
                "MAE": "Equal approach weight; seeds averaged within approaches",
                "MdAE": "Pooled median absolute error over decision/seed pairs",
                "interval": "1000 paired vessel-cluster resamples; negative delta favors mitigation",
                "policy_selection": "Fixed before running; no threshold search or April tuning",
                "repair_stage": "After existing C guard, before speed feature generation",
                "retained": "Original missing-speed fraction, history_missing, timestamps, positions and guard diagnostics",
                "limits": "Simulated disruption; proposed stress rates, not measured missingness prevalence. "
                          "April inspected previously; follow-up cohort, not pristine holdout. Target is analytical crossing, not docking.",
                "protected_hashes_before": hashes}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    predictions = []
    for split in ("validation", "evaluation"):
        decisions = dataset.partition(split).sort_values(["approach_id", "decision_time"])
        tasks = [(config.baseline, config.guard, dataset.histories[identity], group)
                 for identity, group in decisions.groupby("approach_id", sort=False)]
        originals, mitigated, metadata = [], [], []
        print(f"{split}: {len(tasks)} approaches / {len(decisions)} decisions", flush=True)
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(approach_views, task) for task in tasks]
            for completed, future in enumerate(as_completed(futures), 1):
                original, repaired, meta = future.result()
                originals.extend(original)
                mitigated.extend(repaired)
                metadata.extend(meta)
                if completed % 12 == 0 or completed == len(tasks):
                    print(f"  {completed}/{len(tasks)} approaches", flush=True)
        meta = pd.DataFrame(metadata)
        meta["original_error"] = score(originals, meta, predictor)
        meta["mitigated_error"] = score(mitigated, meta, predictor)
        meta["absolute_error_change"] = meta.mitigated_error.abs() - meta.original_error.abs()
        assert not meta.duplicated(["decision_id", "fraction", "seed"]).any()
        assert meta.groupby(["fraction", "seed"]).size().eq(len(decisions)).all()
        predictions.append(meta)
    predictions = pd.concat(predictions, ignore_index=True)
    summary = summarize(predictions)
    hashes_after = {str(path): file_digest(path) for path in protected}
    assert hashes_after == hashes
    april = summary.loc[summary.split.eq("evaluation")]
    clean = april.loc[april.fraction.eq(0)].iloc[0]
    assert abs(clean.original_mae - 5.85976006005499) < 1e-6
    assert np.array_equal(predictions.original_error.notna(), predictions.mitigated_error.notna())
    predictions.to_csv(output / "predictions.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    validation = {"model_and_source_hashes_unchanged": True, "original_C_baseline_reproduced": True,
                  "same_support_and_decision_times": True, "no_report_mutation": True,
                  "only_speed_related_features_changed": True, "original_missingness_and_clocks_preserved": True,
                  "truth_and_audit_excluded_from_predictor_inputs": True,
                  "no_model_retraining_or_frontend_edits": True,
                  "evaluation_approaches": int(clean.approaches), "evaluation_decisions": int(clean.decisions),
                  "elapsed_seconds": time.perf_counter() - started}
    (output / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    lines = ["# MissingSpeedMitigation on frozen optimized XGBoost", "",
             "Simulated missing-speed corruption on original AIS histories. No model retraining. "
             "Poly and ordinary XGBoost remain unchanged. Negative paired delta favors mitigation.", "",
             "Policy is fixed before evaluation: five-minute trailing fit, at least three positions spanning "
             "60 seconds, no gap over 120 seconds, max speed 60 knots, max fit residual 50 m, "
             "max pair-velocity disagreement 2 knots. Unsupported speeds stay missing. "
             "The existing C guard runs first. No report timestamps or positions change; the original "
             "missing-speed fraction and history_missing feature remain visible to C.", ""]
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
    lines += ["MAE weights approaches equally, with seeds averaged within approach. MdAE/P95 pool errors. "
              "Both arms use identical support, decision times and original crossing labels. Reconstruction "
              "rate counts missing guarded bins repeated across decision windows, not unique raw reports. "
              "Full masking is seed-invariant and runs once. Partial masking uses seeds 4201–4203.", "",
              "## Interpretation and variation across approaches", ""]
    for row in april.loc[april.fraction.gt(0)].itertuples():
        lines.append(f"At {row.fraction:.0%} masking: {row.improved_approaches} approaches improved, "
                     f"{row.worsened_approaches} worsened, {row.unchanged_approaches} were unchanged. "
                     f"Worst approach-level mean change: {row.worst_approach_mae_change:+.4f} minutes.")
    lines += ["", "The clean selected cohort had no missing guarded SOG requiring repair; its exact "
              "identity is not validation on naturally missing-speed cases. Aggregate gains do not imply "
              "that every vessel or every decision benefits.", "",
              "A fit estimates recent average motion, not independently verified instantaneous speed. "
              "Turns, acceleration and coherent position errors can still defeat reconstruction. C's trees "
              "and imputer are unchanged; derived values can still change their split/missing-indicator behavior. "
              "Keeping original missingness features exposes uncertainty but does not guarantee calibrated predictions.", "",
              "This is a fixed-policy follow-up experiment on previously inspected data, not evidence of "
              "universal protection. Stress fractions are not measured source failure rates. Arrival means "
              "analytical crossing, not docking. P95, diagnostics and per-decision results are in locally ignored CSVs.", "",
              "Reproduce from Data_Science: `python experiments/missing_speed_mitigation/run.py`."]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary.to_string(index=False), flush=True)
    print(f"Completed in {validation['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

"""Paired comparisons preserve unavailable decisions and original outcomes."""

from dataclasses import dataclass
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from eta_baselines.evaluation import score_predictions
from eta_baselines.dataset import file_digest
from eta_baselines.prediction import EtaPredictor

from .configuration import OptimizedConfig
from .model import MODEL_SPECS, inference_implementation
from .views import predictor_inputs


@dataclass(frozen=True)
class PredictionSystem:
    name: str
    predictor: EtaPredictor
    input_view: str


def load_systems(config: OptimizedConfig) -> list[PredictionSystem]:
    systems = []
    for name, artifact in (("A", "quadratic"), ("B", "xgboost")):
        predictor = joblib.load(config.frozen_baseline_model(artifact))
        systems.extend([PredictionSystem(name, predictor, "raw"),
                        PredictionSystem(f"{name}_guard", predictor, "guarded")])
    for spec in MODEL_SPECS:
        path = config.output_directory / "models" / f"{spec.name}.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Required model/control {spec.name} is missing; run train before evaluation.")
        manifest = json.loads(path.with_name(f"{spec.name}_manifest.json").read_text())
        if (manifest["config"] != config.snapshot() or manifest["model_sha256"] != file_digest(path)
                or manifest.get("inference_implementation") != inference_implementation()):
            raise ValueError(f"Model {spec.name} does not match current inference code/config; use a new trained version.")
        systems.append(PredictionSystem(spec.name, joblib.load(path), spec.input_view))
    return systems


def predict_systems(views: pd.DataFrame, systems: list[PredictionSystem]) -> pd.DataFrame:
    outputs = []
    for system in systems:
        inputs = predictor_inputs(views, system.input_view)
        support_column = "raw_supported" if system.input_view == "raw" else "supported"
        supported = inputs[support_column].to_numpy(dtype=bool)
        result = views[["approach_id", "mmsi", "decision_id", "decision_time", "arrival_time",
                        "scenario", "condition", "seed", "split", "reasons",
                        "guard_received_count", "guard_removed_count"]].copy()
        result["system"] = system.name
        for column in ("is_tanker", "occupied_minute_bins", "seen_training_vessel"):
            if column in views:
                result[column] = views[column].to_numpy()
        result["available"] = supported
        for column in ("predicted_arrival_time", "observation_time"):
            result[column] = pd.NaT
        for column in ("error_minutes", "predicted_remaining_minutes", "report_age_minutes",
                       "predicted_observation_duration_minutes"):
            result[column] = np.nan
        if supported.any():
            predictions = system.predictor.predict(inputs.loc[supported])
            for column in ("predicted_arrival_time", "observation_time", "error_minutes",
                           "predicted_remaining_minutes", "report_age_minutes",
                           "predicted_observation_duration_minutes"):
                result.loc[supported, column] = predictions[column].to_numpy()
        outputs.append(result)
    return pd.concat(outputs, ignore_index=True)


def summarize_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    summaries = []
    for (system, scenario), group in predictions.groupby(["system", "scenario"], sort=False):
        valid = group.loc[group["available"] & group["error_minutes"].notna()]
        metrics = score_predictions(valid) if len(valid) else {}
        metrics.update({
            "system": system, "scenario": scenario, "condition": group["condition"].iloc[0],
            "scheduled_decisions": len(group), "available_decisions": len(valid),
            "unavailable_decisions": len(group) - len(valid),
            "scheduled_approaches": group["approach_id"].nunique(),
            "seeds": group["seed"].nunique(), "output_coverage": len(valid) / len(group),
            "expired_forecasts": int(valid["predicted_remaining_minutes"].lt(0).sum()),
            "invalid_forecasts": int((group["available"] & ~np.isfinite(group["error_minutes"])).sum()),
        })
        summaries.append(metrics)
    return pd.DataFrame(summaries)


def paired_vessel_intervals(predictions: pd.DataFrame, config: OptimizedConfig) -> pd.DataFrame:
    rows = []
    for scenario, group in predictions.groupby("scenario"):
        supported = group.loc[group["available"]].copy()
        supported["absolute_error"] = supported["error_minutes"].abs()
        per_case = supported.pivot_table(
            index=["mmsi", "approach_id", "decision_id", "seed"], columns="system", values="absolute_error",
        )
        if "C" not in per_case:
            continue
        for reference in ("B", "B_guard", "augmented_motion", "C_nominal", "B_rich_nominal"):
            if reference not in per_case:
                continue
            paired = per_case[["C", reference]].dropna().copy()
            if paired.empty:
                continue
            paired["delta"] = paired["C"] - paired[reference]
            by_approach = paired.groupby(["mmsi", "approach_id"])["delta"].mean()
            sums = by_approach.groupby("mmsi").agg(["sum", "count"])
            generator = np.random.default_rng(config.baseline.training.seed)
            estimates = []
            for _ in range(config.review.bootstrap_samples):
                sample = sums.iloc[generator.integers(0, len(sums), len(sums))]
                estimates.append(sample["sum"].sum() / sample["count"].sum())
            rows.append({"scenario": scenario, "comparison": f"C minus {reference}",
                         "paired_cases": len(paired), "paired_approaches": len(by_approach),
                         "vessels": len(sums), "mean_delta_minutes": by_approach.mean(),
                         "median_approach_delta_minutes": float(by_approach.median()),
                         "paired_approach_win_share": float(by_approach.lt(0).mean()),
                         "lower95": float(np.quantile(estimates, .025)),
                         "upper95": float(np.quantile(estimates, .975))})
    return pd.DataFrame(rows)


def save_evaluation(predictions: pd.DataFrame, config: OptimizedConfig, name: str) -> None:
    directory = config.output_directory / "results" / name
    directory.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(directory / "predictions.csv", index=False)
    summary = summarize_predictions(predictions)
    summary.to_csv(directory / "condition_summary.csv", index=False)
    paired_vessel_intervals(predictions, config).to_csv(directory / "paired_uncertainty.csv", index=False)
    valid = predictions.loc[predictions["available"]].assign(
        absolute_error=lambda frame: frame["error_minutes"].abs(),
        actual_remaining=lambda frame: (frame["arrival_time"] - frame["decision_time"]).dt.total_seconds() / 60,
    )
    valid["horizon"] = pd.cut(valid["actual_remaining"], [0, 15, 30, 60, 120, np.inf],
                               labels=["0-15", "15-30", "30-60", "60-120", "120+"])
    horizons = valid.groupby(["system", "scenario", "horizon", "approach_id"], observed=True)["absolute_error"].mean()
    horizons.groupby(["system", "scenario", "horizon"], observed=True).agg(["mean", "count"]).to_csv(directory / "horizon_errors.csv")
    valid.groupby(["system", "scenario", "seed", "approach_id", "mmsi"])["absolute_error"].agg(["mean", "max", "size"]).to_csv(directory / "approach_errors.csv")
    valid["day"] = valid["decision_time"].dt.date
    for field in ("day", "seed", "is_tanker", "occupied_minute_bins", "seen_training_vessel"):
        if field in valid:
            by_approach = valid.groupby(["system", "scenario", field, "approach_id"], observed=True)["absolute_error"].mean()
            by_approach.groupby(["system", "scenario", field], observed=True).agg(["mean", "count"]).to_csv(
                directory / f"errors_by_{field}.csv",
            )
    valid.nlargest(100, "absolute_error").to_csv(directory / "failures.csv", index=False)
    status = "protected" if set(predictions["split"]) == {"evaluation"} else "exploratory_or_development"
    (directory / "status.json").write_text(json.dumps({
        "status": status, "arrival_reference": "Existing analytical crossing gate; not VIG docking.",
        "calibrated": "interval_half_width_minutes" in predictions,
        "limitations": "Paired resampling describes this selected cohort; no universal robustness claim.",
    }, indent=2), encoding="utf-8")
    if name == "evaluation_primary":
        _save_adoption_check(summary, directory)


def _save_adoption_check(summary: pd.DataFrame, directory: Path) -> None:
    errors = summary.pivot(index="scenario", columns="system", values="approach_weighted_mae_minutes")
    degraded = ["stale_15", "quality_0.5nm_25pct", "combined_15_0.5nm_25pct"]
    nominal_cost = float(errors.loc["nominal", "C"] / errors.loc["nominal", "B"] - 1)
    degraded_gain = float(1 - errors.loc[degraded, "C"].mean() / errors.loc[degraded, "B"].mean())
    guard_gain = float(1 - errors.loc[degraded, "C"].mean() / errors.loc[degraded, "B_guard"].mean())
    artifact = {"nominal_relative_cost": nominal_cost, "degraded_relative_improvement": degraded_gain,
                "improvement_over_B_guard": guard_gain,
                "degraded_goal_met": degraded_gain >= .1, "nominal_cost_goal_met": nominal_cost <= .05,
                "guard_contribution_goal_met": guard_gain > 0,
                "interpretation": "Point-estimate project targets; consult paired uncertainty and coverage before adoption.",
                "action": "Investigate or report a negative finding if any goal fails; do not retune on this evaluation."}
    review_path = directory / "review_summary.csv"
    if review_path.exists():
        review = pd.read_csv(review_path)
        primary = review.loc[(review["system"] == "C") & review["tolerance_minutes"].eq(5)
                             & review["scenario"].ne("reserved_drift")]
        usefulness = primary.groupby("policy")["useful_output_rate"].mean()
        passes = bool(usefulness.get("calibrated", 0) > usefulness.get("age_only", 0))
        artifact.update({"review_policy_goal_met": passes,
                         "review_policy_recommendation": "calibrated" if passes else "retain_simple_age_only_comparator",
                         "review_policy_note": "No safety guarantee. Consult false warnings, misses and matched-coverage curves; keep the fixed calibration result visible."})
    (directory / "adoption_check.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")

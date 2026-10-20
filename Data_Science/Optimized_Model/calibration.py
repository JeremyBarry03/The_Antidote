"""Independent approach-level error envelopes and auditable review policies."""

from dataclasses import asdict, dataclass
import json
import math

import numpy as np
import pandas as pd

from eta_baselines.dataset import file_digest

from .configuration import OptimizedConfig

AGE_BANDS = ("0-5", "5-15", "15-30", "30+")


def age_band(age_minutes: float) -> str:
    if age_minutes <= 5:
        return "0-5"
    if age_minutes <= 15:
        return "5-15"
    if age_minutes <= 30:
        return "15-30"
    return "30+"


@dataclass(frozen=True)
class ErrorBand:
    half_width_minutes: float | None
    approaches: int


def _error_band(group: pd.DataFrame, config: OptimizedConfig) -> ErrorBand:
    scores = group.groupby("approach_id")["absolute_error"].max().to_numpy()
    if len(scores) < config.review.minimum_calibration_approaches:
        return ErrorBand(None, len(scores))
    level = min(1.0, math.ceil((len(scores) + 1) * config.review.coverage_target) / len(scores))
    return ErrorBand(float(np.quantile(scores, level, method="higher")), len(scores))


def model_hashes(config: OptimizedConfig) -> dict[str, str]:
    paths = list((config.output_directory / "models").glob("*.joblib"))
    paths.extend(config.frozen_baseline_model(name) for name in ("quadratic", "xgboost"))
    return {str(path.resolve()): file_digest(path) for path in paths}


def fit_calibration(predictions: pd.DataFrame, config: OptimizedConfig) -> dict[str, object]:
    if set(predictions["split"]) != {"calibration"}:
        raise ValueError("Calibration may only use the separate calibration partition.")
    if (predictions["decision_time"] >= pd.Timestamp(config.evaluation_start)).any():
        raise ValueError("Calibration inputs overlap protected evaluation.")
    records = {}
    for system, group in predictions.loc[predictions["available"]].groupby("system"):
        group = group.assign(absolute_error=group["error_minutes"].abs(),
                             age_band=group["report_age_minutes"].map(age_band))
        records[system] = {"pooled": asdict(_error_band(group, config))}
        for band, subset in group.groupby("age_band"):
            records[system][band] = asdict(_error_band(subset, config))
    artifact = {"bands": records, "model_hashes": model_hashes(config), "config": config.snapshot(),
                "meaning": "Empirical whole-approach error envelope; not universal coverage guarantee.",
                "reference_approaches": predictions["approach_id"].nunique()}
    path = config.output_directory / "calibration.json"
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return artifact


def load_calibration(config: OptimizedConfig) -> dict[str, object]:
    path = config.output_directory / "calibration.json"
    if not path.exists():
        raise FileNotFoundError("Separate calibration is required before protected review-policy evaluation.")
    artifact = json.loads(path.read_text())
    if artifact["model_hashes"] != model_hashes(config) or artifact["config"] != config.snapshot():
        raise ValueError("Calibration does not match the current frozen models/configuration.")
    return artifact


def apply_review(
    predictions: pd.DataFrame, calibration: dict[str, object], config: OptimizedConfig,
) -> pd.DataFrame:
    result = predictions.copy()
    widths = []
    support = []
    reasons = []
    for row in predictions.itertuples():
        bands = calibration["bands"].get(row.system, {})
        band = bands.get(age_band(row.report_age_minutes), bands.get("pooled", {}))
        if band.get("half_width_minutes") is None:
            band = bands.get("pooled", {})
        width = band.get("half_width_minutes")
        widths.append(width if width is not None else np.nan)
        support.append(band.get("approaches", 0))
        if not row.available:
            reason = "no_supported_input"
        elif width is None:
            reason = "insufficient_calibration_support"
        elif row.predicted_remaining_minutes < 0:
            reason = "estimated_arrival_already_expired"
        elif width > config.review.maximum_half_width_minutes:
            reason = "uncertainty_requires_verification"
        else:
            reason = "provisional_estimate"
        reasons.append(reason)
    result["interval_half_width_minutes"] = widths
    result["calibration_approaches"] = support
    result["review_reason"] = reasons
    result["accepted"] = result["review_reason"] == "provisional_estimate"
    result["age_only_accepted"] = (result["available"] & result["report_age_minutes"].le(
        config.review.age_only_threshold_minutes
    ) & result["predicted_remaining_minutes"].ge(0))
    return result


def review_metrics(predictions: pd.DataFrame, tolerance_minutes: float) -> dict[str, float | int | None]:
    available = predictions["available"]
    accepted = predictions["accepted"]
    accurate = available & predictions["error_minutes"].abs().le(tolerance_minutes)
    wrong = available & ~accurate
    calibrated = available & predictions["interval_half_width_minutes"].notna()
    covered = predictions.loc[calibrated, "error_minutes"].abs().le(
        predictions.loc[calibrated, "interval_half_width_minutes"],
    )
    groups = [predictions.loc[calibrated, "approach_id"]]
    if "seed" in predictions:
        groups.append(predictions.loc[calibrated, "seed"])
    return {
        "scheduled": len(predictions), "available": int(available.sum()),
        "accepted": int(accepted.sum()), "deferred_or_unavailable": int((~accepted).sum()),
        "accepted_share": float(accepted.mean()),
        "useful_output_rate": float((accepted & accurate).mean()),
        "missed_unreliable_forecasts": int((accepted & wrong).sum()),
        "unnecessary_reviews": int((~accepted & accurate).sum()),
        "unreliable_forecasts_flagged": int((~accepted & wrong).sum()),
        "accepted_mae_minutes": float(predictions.loc[accepted, "error_minutes"].abs().mean()) if accepted.any() else None,
        "accepted_approach_mae_minutes": float(predictions.loc[accepted].assign(
            absolute_error=lambda frame: frame["error_minutes"].abs(),
        ).groupby("approach_id")["absolute_error"].mean().mean()) if accepted.any() else None,
        "interval_supported_outputs": int(calibrated.sum()),
        "mean_interval_half_width_minutes": float(predictions.loc[calibrated, "interval_half_width_minutes"].mean()) if calibrated.any() else None,
        "measured_interval_coverage": float(covered.mean()) if calibrated.any() else None,
        "whole_approach_interval_coverage": float(covered.groupby(groups).all().mean()) if calibrated.any() else None,
    }


def save_review_curves(predictions: pd.DataFrame, config: OptimizedConfig, name: str) -> None:
    summaries, curves, matched = [], [], []
    for (system, scenario), group in predictions.groupby(["system", "scenario"]):
        for policy in ("calibrated", "age_only"):
            frame = group.copy()
            if policy == "age_only":
                frame["accepted"] = frame["age_only_accepted"]
            for tolerance in (2, 5, 10):
                summaries.append({"system": system, "scenario": scenario, "policy": policy,
                                  "tolerance_minutes": tolerance, **review_metrics(frame, tolerance)})
        for width in (2, 5, 10, 15, 30, 60, 120):
            frame = group.copy()
            frame["accepted"] = (frame["available"] & frame["predicted_remaining_minutes"].ge(0)
                                 & frame["interval_half_width_minutes"].le(width))
            curves.append({"system": system, "scenario": scenario, "threshold_minutes": width,
                           **review_metrics(frame, 5)})
            age_ordered = frame.loc[frame["available"] & frame["predicted_remaining_minutes"].ge(0)].sort_values(
                ["report_age_minutes", "decision_id", "seed"], kind="stable",
            )
            age_policy = group.copy()
            age_policy["accepted"] = False
            age_policy.loc[age_ordered.head(int(frame["accepted"].sum())).index, "accepted"] = True
            for policy, candidate in (("calibrated", frame), ("age_ranked", age_policy)):
                matched.append({"system": system, "scenario": scenario, "policy": policy,
                                "threshold_minutes": width, **review_metrics(candidate, 5)})
    directory = config.output_directory / "results" / name
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(directory / "review_summary.csv", index=False)
    pd.DataFrame(curves).to_csv(directory / "error_coverage_curves.csv", index=False)
    pd.DataFrame(matched).to_csv(directory / "matched_coverage.csv", index=False)

"""Compare frozen C versions on matched March records without fitting models."""

import argparse
import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from eta_baselines.dataset import file_digest
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.evaluation import PredictionSystem, load_systems, predict_systems
from Optimized_Model.views import read_views

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/data_eval/prior_comparison"
logger = logging.getLogger(__name__)


def summarize(predictions: pd.DataFrame, cohort: str) -> pd.DataFrame:
    rows = []
    for name, group in predictions.groupby("system"):
        valid = group.loc[group["available"] & np.isfinite(group["error_minutes"])]
        absolute = valid["error_minutes"].abs()
        rows.append({"cohort": cohort, "model": name, "decisions": len(group),
                     "approaches": group["approach_id"].nunique(),
                     "coverage": len(valid) / len(group),
                     "approach_weighted_mae_minutes": absolute.groupby(valid["approach_id"]).mean().mean(),
                     "forecast_mdae_minutes": absolute.median(),
                     "forecast_p95_minutes": absolute.quantile(.95)})
    return pd.DataFrame(rows)


def compare(prior_root: Path) -> pd.DataFrame:
    current = ROOT / "artifacts/data_eval/optimized"
    config = OptimizedConfig.load(ROOT / "Optimized_Model/config_data_eval.json")
    views = read_views(current / "views/evaluation_nominal.csv")
    if set(views["scenario"]) != {"nominal"} or not views["decision_time"].between(
        "2024-03-01", "2024-04-01", inclusive="left",
    ).all():
        raise ValueError("This comparison requires original March-only nominal inputs")
    predictions = pd.read_csv(current / "results/evaluation_nominal/predictions.csv")
    systems = [system for system in load_systems(config) if system.name in {"A", "B", "C"}]
    fresh = predict_systems(views, systems)
    matched = fresh.merge(predictions, on=["system", "decision_id"], suffixes=("_fresh", "_saved"),
                          validate="one_to_one")
    if len(matched) != len(predictions):
        raise ValueError("Saved predictions do not cover the current inputs")
    np.testing.assert_allclose(matched["error_minutes_fresh"], matched["error_minutes_saved"], atol=1e-8)
    source_hash = json.loads((ROOT / "artifacts/data_eval/run_manifest.json").read_text())["sources"]["march_sha256"]
    audits = []
    prior_systems = []
    boundary = None
    for version in ("march_gate_v1", "march_gate_vessel_class_v2"):
        directory = prior_root / "artifacts/optimized" / version
        manifest = json.loads((directory / "models/C_manifest.json").read_text())
        model = directory / "models/C.joblib"
        if file_digest(model) != manifest["model_sha256"]:
            raise ValueError(f"Prior model hash changed: {version}")
        replay = manifest["replay_manifest"]
        if source_hash not in replay["sources"].values():
            raise ValueError(f"Prior model used a different March source: {version}")
        splits = replay["baseline_configuration"]["splits"]
        period = (splits["test_start"], splits["end_exclusive"])
        if boundary is not None and boundary != period:
            raise ValueError("Prior models have different held-out periods")
        boundary = period
        checked = 0
        # Check actual legacy inputs, not just filename or schema compatibility.
        # This also tests the legacy 32-feature model against the current extractor.
        for partition in ("training", "development"):
            path = directory / f"views/{partition}.csv"
            if file_digest(path) != manifest[f"{partition}_view_sha256"]:
                raise ValueError(f"Prior input view changed: {path}")
            original = read_views(path)
            original = original.loc[original["scenario"].eq("nominal")]
            pairs = original.merge(views, on="decision_id", suffixes=("_old", "_new"), validate="one_to_one")
            if len(pairs) != len(original):
                raise ValueError("Prior nominal decisions are missing from the new March inputs")
            for column in manifest["feature_columns"]:
                np.testing.assert_allclose(pairs[f"{column}_old"], pairs[f"{column}_new"],
                                           atol=1e-9, rtol=1e-9, equal_nan=True, err_msg=column)
            for column in ("arrival_time", "observation_time"):
                if not pairs[f"{column}_old"].eq(pairs[f"{column}_new"]).all():
                    raise ValueError(f"Prior {column} differs from current inputs")
            checked += len(pairs)
        predictor = joblib.load(model)
        prior_systems.append(PredictionSystem(f"C_prior_{version}", predictor, "guarded"))
        audits.append({"version": version, "model_sha256": manifest["model_sha256"],
                       "verified_nominal_input_rows": checked, "splits": splits,
                       "train_approaches": manifest["train_approaches"],
                       "selected_parameters": manifest["selected_parameters"]})
        logger.info("Verified %s legacy nominal inputs for %s", checked, version)
    held = views.loc[views["episode_start"].ge(boundary[0]) & views["crossing_after"].lt(boundary[1])]
    if held.empty:
        raise ValueError("No common held-out March approaches")
    prior_predictions = predict_systems(held, prior_systems)
    current_held = predictions.loc[predictions["decision_id"].isin(held["decision_id"])]
    comparison = pd.concat([current_held, prior_predictions], ignore_index=True)
    for _, group in comparison.groupby("system"):
        if set(group["decision_id"]) != set(held["decision_id"]):
            raise ValueError("Models do not share exactly the same evaluation cases")
    controls = [system for system in load_systems(config) if system.name in {"C_nominal", "B_rich_nominal"}]
    control_predictions = predict_systems(views, controls)
    result = pd.concat([
        summarize(predictions, "entire_March_new_models"),
        summarize(comparison, "matched_March_25_31"),
        summarize(control_predictions, "entire_March_internal_diagnostics"),
        summarize(control_predictions.loc[control_predictions["decision_id"].isin(held["decision_id"])],
                  "matched_March_25_31_internal_diagnostics"),
    ], ignore_index=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(OUTPUT / "matched_predictions.csv", index=False)
    result.to_csv(OUTPUT / "summary.csv", index=False)
    (OUTPUT / "audit.json").write_text(json.dumps({"prior_models": audits,
        "march_source_sha256": source_hash, "matched_decisions_per_model": len(held),
        "matched_approaches": held["approach_id"].nunique(), "april_records_evaluated": 0,
        "models_retrained": False, "new_predictions_reproduced": len(matched)}, indent=2), encoding="utf-8")
    result.to_csv(Path(__file__).with_name("summary.csv"), index=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-root", type=Path, required=True, help="Prior checkout's Data_Science directory")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.prior_root.is_dir():
        parser.error("--prior-root must be an existing Data_Science directory")
    print(compare(args.prior_root.resolve()).to_string(index=False))


if __name__ == "__main__":
    main()

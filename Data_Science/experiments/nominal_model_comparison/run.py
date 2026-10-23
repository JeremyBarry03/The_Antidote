"""Audit 2023-only nominal fitting and compare A/B/C on all of March 2024."""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from eta_baselines.dataset import file_digest
from experiments.prior_model_comparison.run import summarize
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.evaluation import load_systems, paired_vessel_intervals, predict_systems
from Optimized_Model.views import read_views

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts/data_eval/nominal_comparison"
logger = logging.getLogger(__name__)


def decision_keys(frame: pd.DataFrame) -> set[tuple[str, pd.Timestamp]]:
    return set(zip(frame["approach_id"], frame["decision_time"]))


def run() -> pd.DataFrame:
    config = OptimizedConfig.load(ROOT / "Optimized_Model/config_data_eval.json")
    optimized = config.output_directory
    manifest = json.loads((optimized / "models/C_nominal_manifest.json").read_text())
    if not manifest["nominal_training_only"]:
        raise ValueError("C must be the nominal-only fitted artifact")
    baseline = config.baseline
    expected = {"start": "2023-01-01", "validation_start": "2023-06-30",
                "test_start": "2023-07-20", "end_exclusive": "2023-07-30"}
    saved = json.loads((baseline.output_directory / "config_snapshot.json").read_text())
    if saved["splits"] != expected or manifest["replay_manifest"]["baseline_configuration"] != saved:
        raise ValueError("Models do not share the declared 2023 preparation and fitting configuration")
    examples = pd.read_csv(baseline.output_directory / "examples.csv",
                           usecols=["approach_id", "decision_time", "split", "episode_start", "crossing_after"])
    for column in ("decision_time", "episode_start", "crossing_after"):
        examples[column] = pd.to_datetime(examples[column])
    training = {}
    for name, split, start, end, prefix in (
        ("training", "train", expected["start"], expected["validation_start"], "train"),
        ("development", "validation", expected["validation_start"], expected["test_start"], "development"),
    ):
        path = optimized / f"views/{name}.csv"
        if file_digest(path) != manifest[f"{name}_view_sha256"]:
            raise ValueError(f"Saved {name} inputs changed")
        frame = pd.read_csv(path, usecols=["condition", "supported", "approach_id", "decision_time",
                                          "episode_start", "crossing_after", "split"])
        selected = frame.loc[frame["condition"].eq("nominal") & frame["supported"]].copy()
        if len(selected) != manifest[f"{prefix}_rows"]:
            raise ValueError(f"Nominal {name} row count differs from the fitted model manifest")
        for column in ("decision_time", "episode_start", "crossing_after"):
            selected[column] = pd.to_datetime(selected[column])
        if not (selected["episode_start"].ge(start) & selected["crossing_after"].lt(end)).all():
            raise ValueError(f"C {name} inputs cross the declared 2023 boundary")
        base = examples.loc[examples["split"].eq(split)]
        if decision_keys(base) != decision_keys(selected) or set(selected["split"]) != {split}:
            raise ValueError(f"A/B and nominal C do not share the same {name} decisions")
        training[split] = {"start": start, "end_exclusive": end, "rows": len(selected),
                           "approaches": selected["approach_id"].nunique(), "condition": "nominal"}
        logger.info("Verified %s identical nominal %s decisions for A/B/C", len(selected), split)
    views = read_views(optimized / "views/evaluation_nominal.csv")
    if (set(views["scenario"]) != {"nominal"} or set(views["split"]) != {"evaluation"}
            or not views["episode_start"].ge("2024-03-01").all()
            or not views["crossing_after"].lt("2024-04-01").all()):
        raise ValueError("Evaluation must contain only original full-March approaches")
    if set(views["approach_id"]) & set(examples["approach_id"]):
        raise ValueError("March evaluation overlaps 2023 fitting/development records")
    systems = [system for system in load_systems(config) if system.name in {"A", "B", "C_nominal"}]
    if {system.name for system in systems} != {"A", "B", "C_nominal"}:
        raise ValueError("Required frozen nominal models are missing")
    predictions = predict_systems(views, systems)
    predictions["artifact_system"] = predictions["system"]
    predictions["system"] = predictions["system"].replace({"C_nominal": "C"})
    for _, group in predictions.groupby("system"):
        if set(group["decision_id"]) != set(views["decision_id"]):
            raise ValueError("Prediction schedules differ between models")
        if not group["available"].all() or not np.isfinite(group["error_minutes"]).all():
            raise ValueError("Unexpected unavailable or invalid nominal prediction")
    summary = summarize(predictions, "March_1_31_2024_all_nominal")
    paired = paired_vessel_intervals(predictions, config)
    paired["comparison"] = paired["comparison"].replace({"C minus B": "nominal_C minus B"})
    OUTPUT.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(OUTPUT / "predictions.csv", index=False)
    summary.to_csv(OUTPUT / "summary.csv", index=False)
    paired.to_csv(OUTPUT / "paired_uncertainty.csv", index=False)
    paths = {"A": config.frozen_baseline_model("quadratic"),
             "B": config.frozen_baseline_model("xgboost"),
             "C": optimized / "models/C_nominal.joblib"}
    for name, artifact in (("A", "quadratic"), ("B", "xgboost")):
        expected_hash = manifest["replay_manifest"]["frozen_baseline_hashes"][artifact]
        if file_digest(paths[name]) != expected_hash:
            raise ValueError(f"Frozen baseline {name} changed since model fitting")
    audit = {"training": training, "test_start": "2024-03-01", "test_end_exclusive": "2024-04-01",
             "evaluation_decisions_per_model": len(views), "evaluation_approaches": views["approach_id"].nunique(),
             "evaluation_vessels": views["mmsi"].nunique(), "injected_faults": False,
             "april_2024_records_evaluated": 0, "models_retrained": False,
             "C_artifact": "C_nominal.joblib", "original_augmented_C_retained": True,
             "models": {name: {"path": str(path.relative_to(ROOT)), "sha256": file_digest(path)}
                        for name, path in paths.items()}, "summary": summary.to_dict(orient="records"),
             "paired_uncertainty": paired.to_dict(orient="records")}
    (OUTPUT / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    Path(__file__).with_name("verification.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))
    print(paired.to_string(index=False))
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()

"""Fit model C and explanatory controls with the same shared estimator lifecycle."""

from dataclasses import dataclass
from importlib.metadata import version
import json
import logging
from pathlib import Path
import time
from typing import Literal

import joblib
import numpy as np
import pandas as pd

from XGBoost_Model.model import build_xgboost_regressor
from eta_baselines.dataset import file_digest
from eta_baselines.evaluation import score_predictions
from eta_baselines.fitting import FitPartition, fit_imputer, fit_regressor, training_weights
from eta_baselines.prediction import EtaPredictor

from .configuration import OptimizedConfig
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS
from .views import predictor_inputs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    columns: tuple[str, ...]
    input_view: Literal["raw", "guarded"]
    nominal_only: bool
    clock: Literal["observation", "decision"]


MODEL_SPECS = (
    ModelSpec("C", OPTIMIZED_COLUMNS, "guarded", False, "decision"),
    ModelSpec("C_nominal", OPTIMIZED_COLUMNS, "guarded", True, "decision"),
    ModelSpec("augmented_motion", RICH_COLUMNS, "guarded", False, "decision"),
    ModelSpec("B_rich_nominal", RICH_COLUMNS, "raw", True, "observation"),
)


def inference_implementation() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    modules = ["Optimized_Model/features.py", "Optimized_Model/quality.py", "Optimized_Model/replay.py",
               "eta_baselines/features.py", "eta_baselines/motion.py", "eta_baselines/prediction.py"]
    return {module: file_digest(root / module) for module in modules}


def _eligible(views: pd.DataFrame, spec: ModelSpec) -> pd.DataFrame:
    support = "raw_supported" if spec.input_view == "raw" else "supported"
    selected = views.loc[views[support]].copy()
    if spec.nominal_only:
        selected = selected.loc[selected["condition"] == "nominal"]
    selected = predictor_inputs(selected, spec.input_view)
    if spec.clock == "observation":
        selected["target_minutes"] = (selected["arrival_time"] - selected["observation_time"]).dt.total_seconds() / 60
    else:
        selected["target_minutes"] = selected["decision_to_arrival_minutes"]
    if selected.empty or selected["approach_id"].nunique() < 2:
        raise ValueError(f"Insufficient supported examples for {spec.name}.")
    return selected


def condition_error(predictions: pd.DataFrame) -> float:
    errors = [float(score_predictions(group)["approach_weighted_mae_minutes"])
              for _, group in predictions.groupby("condition")]
    return float(np.mean(errors))


def train_models(
    train_views: pd.DataFrame, validation_views: pd.DataFrame, config: OptimizedConfig,
    selected_names: list[str] | None = None,
) -> None:
    if set(train_views["approach_id"]) & set(validation_views["approach_id"]):
        raise ValueError("Training and development approaches overlap.")
    output = config.output_directory / "models"
    output.mkdir(exist_ok=True)
    for spec in MODEL_SPECS:
        if selected_names is not None and spec.name not in selected_names:
            continue
        started = time.perf_counter()
        train = _eligible(train_views, spec)
        validation = _eligible(validation_views, spec)
        imputer = fit_imputer(train, spec.columns)
        partitions = [FitPartition(imputer.transform(frame[list(spec.columns)]),
                                   frame["target_minutes"].to_numpy(), training_weights(frame))
                      for frame in (train, validation)]
        best = None
        best_score = float("inf")
        trials = []
        best_parameters: dict[str, float | int] = {}
        settings = config.baseline.training
        for depth in settings.xgboost_depths:
            for rate in settings.xgboost_learning_rates:
                regressor = build_xgboost_regressor(settings, depth, rate)
                fit_regressor(regressor, *partitions)
                predictor = EtaPredictor(spec.name, imputer, regressor, spec.columns, spec.clock)
                score = condition_error(predictor.predict(validation))
                trials.append({"depth": depth, "learning_rate": rate, "development_mae_minutes": score,
                               "best_iteration": int(regressor.best_iteration)})
                logger.info("%s depth=%s rate=%s development MAE %.3f min", spec.name, depth, rate, score)
                if score < best_score:
                    best, best_score = predictor, score
                    best_parameters = {"depth": depth, "learning_rate": rate}
        if best is None:
            raise ValueError(f"No finite candidate selected for {spec.name}.")
        joblib.dump(best, output / f"{spec.name}.joblib")
        pd.DataFrame(trials).to_csv(output / f"{spec.name}_tuning.csv", index=False)
        best.predict(validation).to_csv(output / f"{spec.name}_development_predictions.csv", index=False)
        report = {
            "name": spec.name, "feature_columns": spec.columns, "target_clock": spec.clock,
            "input_view": spec.input_view, "nominal_training_only": spec.nominal_only,
            "train_rows": len(train), "train_approaches": train["approach_id"].nunique(),
            "train_unavailable_rows": (int(train_views["condition"].eq("nominal").sum())
                                       if spec.nominal_only else len(train_views)) - len(train),
            "development_rows": len(validation),
            "development_approaches": validation["approach_id"].nunique(),
            "development_mae_minutes": best_score, "selected_parameters": best_parameters,
            "fit_seconds": time.perf_counter() - started,
            "versions": {name: version(name) for name in ("xgboost", "scikit-learn", "numpy", "pandas", "joblib")},
            "model_sha256": file_digest(output / f"{spec.name}.joblib"),
            "replay_manifest": json.loads((config.output_directory / "manifest.json").read_text()),
            "training_view_sha256": file_digest(config.output_directory / "views" / "training.csv"),
            "development_view_sha256": file_digest(config.output_directory / "views" / "development.csv"),
            "feature_schema_version": 1,
            "inference_implementation": inference_implementation(),
            "config": config.snapshot(), "seed": settings.seed,
        }
        (output / f"{spec.name}_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

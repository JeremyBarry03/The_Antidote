"""One tuning/evaluation lifecycle shared by the two baseline strategies."""

from dataclasses import asdict, dataclass
from importlib.metadata import version
import json
import logging
import time
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from Simple_baseline.model import build_quadratic_regressor
from XGBoost_Model.model import build_xgboost_regressor

from .configuration import ExperimentConfig
from .dataset import file_digest
from .evaluation import approach_weights, score_predictions
from .features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, TARGET_COLUMN
from .fitting import FitPartition, fit_imputer, fit_regressor
from .prediction import EtaPredictor

logger = logging.getLogger(__name__)
ModelName = Literal["quadratic", "xgboost"]
ModelParameter = float | int


@dataclass
class PreparedPartition:
    examples: pd.DataFrame
    features: np.ndarray
    target: np.ndarray
    weights: np.ndarray


def load_examples(config: ExperimentConfig) -> pd.DataFrame:
    path = config.output_directory / "examples.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Prepared examples missing: {path}. Run the prepare command first.")
    # Avoid reusing examples prepared under a different gate/feature/split configuration.
    saved = json.loads((config.output_directory / "config_snapshot.json").read_text())
    for name in ("gate", "features", "splits"):
        if saved[name] != asdict(getattr(config, name)):
            raise ValueError(f"Prepared {name} differs from config. Rerun prepare.")
    manifest = json.loads((config.output_directory / "data_manifest.json").read_text())
    if (manifest.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
            or manifest.get("feature_columns") != list(FEATURE_COLUMNS)):
        raise ValueError("Prepared feature schema is outdated. Rerun prepare in a versioned output directory.")
    if (manifest["input_csv"] != str(config.input_csv)
            or manifest["input_sha256"] != file_digest(config.input_csv)):
        raise ValueError("Source CSV changed since preparation. Rerun prepare.")
    examples = pd.read_csv(path, dtype={"mmsi": str})
    for column in ("observation_time", "decision_time", "arrival_time", "episode_start",
                   "crossing_before", "crossing_after"):
        examples[column] = pd.to_datetime(examples[column])
    if examples.groupby("approach_id")["split"].nunique().max() != 1:
        raise ValueError("An approach appears in multiple partitions.")
    if (examples["observation_time"] > examples["decision_time"]).any():
        raise ValueError("Prepared examples contain future observations.")
    if not np.isfinite(examples[TARGET_COLUMN]).all() or (examples[TARGET_COLUMN] <= 0).any():
        raise ValueError("Arrival targets must be finite positive durations.")
    if np.isinf(examples[list(FEATURE_COLUMNS)].to_numpy()).any():
        raise ValueError("Feature values must be finite or missing, not infinite.")
    for split in ("train", "validation", "test"):
        count = examples.loc[examples["split"] == split, "approach_id"].nunique()
        if count < 2:
            raise ValueError(f"{split} has only {count} approaches. Extend data or revise declared splits.")
        if count < 30:
            logger.warning("%s has only %s approaches; results are preliminary", split, count)
    return examples


class BaselineTrainer:
    """Fit preprocessing once per run; select candidates using validation only."""

    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config

    def train(self, examples: pd.DataFrame, model_names: list[ModelName]) -> None:
        train = examples.loc[examples["split"] == "train"]
        imputer = fit_imputer(train, FEATURE_COLUMNS)
        partitions = {}
        for split in ("train", "validation", "test"):
            subset = examples.loc[examples["split"] == split].copy()
            partitions[split] = PreparedPartition(
                subset, imputer.transform(subset[list(FEATURE_COLUMNS)]),
                subset[TARGET_COLUMN].to_numpy(), approach_weights(subset),
            )
        for name in model_names:
            self._train_model(name, partitions, imputer)

    def _parameters(self, name: ModelName) -> list[dict[str, ModelParameter]]:
        settings = self.config.training
        if name == "quadratic":
            return [{"alpha": alpha} for alpha in settings.ridge_alphas]
        return [{"depth": depth, "learning_rate": rate}
                for depth in settings.xgboost_depths for rate in settings.xgboost_learning_rates]

    def _train_model(
        self, name: ModelName, partitions: dict[str, PreparedPartition], imputer: SimpleImputer,
    ) -> None:
        started = time.perf_counter()
        train, validation = partitions["train"], partitions["validation"]
        best: EtaPredictor | None = None
        best_parameters: dict[str, ModelParameter] = {}
        best_error = float("inf")
        trials = []
        for parameters in self._parameters(name):
            if name == "quadratic":
                regressor = build_quadratic_regressor(float(parameters["alpha"]))
            else:
                regressor = build_xgboost_regressor(
                    self.config.training, int(parameters["depth"]), float(parameters["learning_rate"]),
                )
            fit_regressor(
                regressor, FitPartition(train.features, train.target, train.weights),
                FitPartition(validation.features, validation.target, validation.weights),
            )
            predictor = EtaPredictor(name, imputer, regressor, FEATURE_COLUMNS)
            metrics = score_predictions(predictor.predict(validation.examples))
            error = float(metrics["approach_weighted_mae_minutes"])
            trials.append({**parameters, **metrics})
            logger.info("%s %s validation approach MAE %.3f min", name, parameters, error)
            if error < best_error:
                best, best_parameters, best_error = predictor, parameters, error
        if best is None:
            raise ValueError(f"No valid candidate fitted for {name}.")
        destination = self.config.output_directory / name
        destination.mkdir(parents=True, exist_ok=True)
        joblib.dump(best, destination / "model.joblib")
        pd.DataFrame(trials).to_csv(destination / "tuning.csv", index=False)
        scores = {}
        for split, partition in partitions.items():
            predictions = best.predict(partition.examples)
            predictions.to_csv(destination / f"{split}_predictions.csv", index=False)
            scores[split] = score_predictions(predictions)
        seen = set(train.examples["mmsi"])
        scores["test_seen_vessels"] = len(set(partitions["test"].examples["mmsi"]) & seen)
        report = {
            "model": name, "selected_parameters": best_parameters,
            "feature_columns": list(FEATURE_COLUMNS),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "target": TARGET_COLUMN, "scores": scores,
            "fit_and_export_seconds": time.perf_counter() - started,
            "versions": {package: version(package) for package in
                         ("numpy", "pandas", "scikit-learn", "xgboost", "joblib", "duckdb")},
            "seed": self.config.training.seed,
        }
        if not isinstance(best.regressor, Pipeline):
            report["best_boosting_iteration"] = int(best.regressor.best_iteration)
        (destination / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        logger.info("Saved %s; test approach MAE %.3f min", name,
                    scores["test"]["approach_weighted_mae_minutes"])

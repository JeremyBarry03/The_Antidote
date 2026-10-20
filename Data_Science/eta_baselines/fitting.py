"""Small shared fitting operations; no split selection or test access here."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from .evaluation import approach_weights


@dataclass(frozen=True)
class FitPartition:
    features: np.ndarray
    targets: np.ndarray
    weights: np.ndarray


def fit_imputer(examples: pd.DataFrame, columns: tuple[str, ...]) -> SimpleImputer:
    return SimpleImputer(
        strategy="median", add_indicator=True, keep_empty_features=True,
    ).fit(examples[list(columns)])


def training_weights(examples: pd.DataFrame) -> np.ndarray:
    """Equal approach totals, then equal decisions, conditions and replicas."""
    if "condition" not in examples:
        return approach_weights(examples)
    grouping = examples.groupby("approach_id", sort=False)
    decisions = grouping["decision_id"].transform("nunique")
    decision_groups = examples.groupby(["approach_id", "decision_id"], sort=False)
    conditions = decision_groups["condition"].transform("nunique")
    replicas = examples.groupby(
        ["approach_id", "decision_id", "condition"], sort=False,
    )["condition"].transform("size")
    weights = (1 / (decisions * conditions * replicas)).to_numpy(dtype=float)
    return weights / weights.mean()


def fit_regressor(
    regressor: Pipeline | XGBRegressor, train: FitPartition, validation: FitPartition,
) -> Pipeline | XGBRegressor:
    if isinstance(regressor, Pipeline):
        regressor.fit(train.features, train.targets, ridge__sample_weight=train.weights)
    else:
        regressor.fit(
            train.features, train.targets, sample_weight=train.weights,
            eval_set=[(validation.features, validation.targets)],
            sample_weight_eval_set=[validation.weights], verbose=False,
        )
    return regressor

"""Serializable preprocessing/model bundle and timestamp-correct inference."""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from .features import FEATURE_COLUMNS


class Regressor(Protocol):
    def predict(self, features: np.ndarray) -> np.ndarray: ...


@dataclass
class EtaPredictor:
    model_name: str
    imputer: SimpleImputer
    regressor: Regressor

    def predict(self, snapshots: pd.DataFrame) -> pd.DataFrame:
        required = set(FEATURE_COLUMNS) | {"observation_time", "decision_time"}
        missing = required - set(snapshots.columns)
        if missing:
            raise ValueError(f"Missing inference columns: {sorted(missing)}")
        observation_time = pd.to_datetime(snapshots["observation_time"])
        decision_time = pd.to_datetime(snapshots["decision_time"])
        if (observation_time > decision_time).any():
            raise ValueError("Observation timestamps cannot be later than decision timestamps.")
        features = self.imputer.transform(snapshots[list(FEATURE_COLUMNS)])
        duration = self.regressor.predict(features)
        age_minutes = (decision_time - observation_time).dt.total_seconds() / 60
        result = snapshots.copy()
        result["model"] = self.model_name
        result["predicted_observation_duration_minutes"] = duration
        result["predicted_remaining_minutes"] = duration - age_minutes
        result["report_age_minutes"] = age_minutes
        result["predicted_arrival_time"] = observation_time + pd.to_timedelta(duration, unit="min")
        if "arrival_time" in result:
            actual = pd.to_datetime(result["arrival_time"])
            result["error_minutes"] = (result["predicted_arrival_time"] - actual).dt.total_seconds() / 60
        return result

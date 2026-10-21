"""Serializable preprocessing/model bundle and timestamp-correct inference."""

from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer

from .features import FEATURE_COLUMNS, LEGACY_FEATURE_COLUMNS


class Regressor(Protocol):
    def predict(self, features: np.ndarray) -> np.ndarray: ...


@dataclass
class EtaPredictor:
    model_name: str
    imputer: SimpleImputer
    regressor: Regressor
    feature_columns: tuple[str, ...] = FEATURE_COLUMNS
    target_clock: Literal["observation", "decision"] = "observation"

    def __setstate__(self, state: dict[str, object]) -> None:
        """Recover the fitted schema of older bundles, not today's class default."""
        self.__dict__.update(state)
        if "feature_columns" not in state:
            self.feature_columns = tuple(getattr(self.imputer, "feature_names_in_", LEGACY_FEATURE_COLUMNS))

    def predict(self, snapshots: pd.DataFrame) -> pd.DataFrame:
        columns = self.__dict__.get("feature_columns")
        if columns is None:
            columns = tuple(getattr(self.imputer, "feature_names_in_", LEGACY_FEATURE_COLUMNS))
        clock = getattr(self, "target_clock", "observation")
        if clock not in ("observation", "decision"):
            raise ValueError(f"Unknown prediction target clock: {clock}")
        required = set(columns) | {"observation_time", "decision_time"}
        missing = required - set(snapshots.columns)
        if missing:
            raise ValueError(f"Missing inference columns: {sorted(missing)}")
        observation_time = pd.to_datetime(snapshots["observation_time"])
        decision_time = pd.to_datetime(snapshots["decision_time"])
        if observation_time.isna().any() or decision_time.isna().any():
            raise ValueError("Observation and decision timestamps must be present.")
        if (observation_time > decision_time).any():
            raise ValueError("Observation timestamps cannot be later than decision timestamps.")
        features = self.imputer.transform(snapshots[list(columns)])
        duration = self.regressor.predict(features)
        if not np.isfinite(duration).all():
            raise ValueError("Regressor returned a non-finite duration.")
        age_minutes = (decision_time - observation_time).dt.total_seconds() / 60
        result = snapshots.copy()
        result["model"] = self.model_name
        remaining = duration - age_minutes if clock == "observation" else duration
        result["predicted_observation_duration_minutes"] = duration if clock == "observation" else duration + age_minutes
        result["predicted_remaining_minutes"] = remaining
        result["report_age_minutes"] = age_minutes
        anchor = observation_time if clock == "observation" else decision_time
        result["predicted_arrival_time"] = anchor + pd.to_timedelta(duration, unit="min")
        if "arrival_time" in result:
            actual = pd.to_datetime(result["arrival_time"])
            result["error_minutes"] = (result["predicted_arrival_time"] - actual).dt.total_seconds() / 60
        return result

"""Typed configuration shared by preparation and both model families."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class GateConfig:
    longitude: float
    south_latitude: float
    north_latitude: float
    approach_east_longitude: float
    approach_south_latitude: float
    approach_north_latitude: float
    maximum_crossing_gap_seconds: int
    episode_break_hours: float


@dataclass(frozen=True)
class FeatureConfig:
    history_minutes: int
    decision_interval_minutes: int
    minimum_episode_minutes: int


@dataclass(frozen=True)
class SplitConfig:
    start: str
    validation_start: str
    test_start: str
    end_exclusive: str


@dataclass(frozen=True)
class TrainingConfig:
    seed: int
    cpu_threads: int
    ridge_alphas: list[float]
    xgboost_depths: list[int]
    xgboost_learning_rates: list[float]
    xgboost_max_rounds: int
    xgboost_early_stopping_rounds: int


@dataclass(frozen=True)
class ExperimentConfig:
    input_csv: Path
    output_directory: Path
    gate: GateConfig
    features: FeatureConfig
    splits: SplitConfig
    training: TrainingConfig

    @classmethod
    def load(cls, path: Path, *, require_input: bool = True) -> "ExperimentConfig":
        contents = json.loads(path.read_text(encoding="utf-8"))
        base = path.resolve().parent
        config = cls(
            input_csv=(base / contents["input_csv"]).resolve(),
            output_directory=(base / contents["output_directory"]).resolve(),
            gate=GateConfig(**contents["gate"]),
            features=FeatureConfig(**contents["features"]),
            splits=SplitConfig(**contents["splits"]),
            training=TrainingConfig(**contents["training"]),
        )
        config.validate(require_input=require_input)
        return config

    def validate(self, *, require_input: bool = True) -> None:
        if require_input and not self.input_csv.is_file():
            raise FileNotFoundError(f"AIS CSV not found: {self.input_csv}")
        gate = self.gate
        if not (-180 <= gate.longitude < gate.approach_east_longitude <= 180):
            raise ValueError("Gate must lie west of the approach area's eastern edge.")
        if not (-90 <= gate.approach_south_latitude <= gate.south_latitude
                < gate.north_latitude <= gate.approach_north_latitude <= 90):
            raise ValueError("Gate latitude range must lie inside the approach area.")
        positive = [gate.maximum_crossing_gap_seconds, gate.episode_break_hours,
                    self.features.history_minutes, self.features.decision_interval_minutes,
                    self.features.minimum_episode_minutes, self.training.cpu_threads,
                    self.training.xgboost_max_rounds,
                    self.training.xgboost_early_stopping_rounds]
        if any(value <= 0 for value in positive):
            raise ValueError("Durations, thread counts and boosting limits must be positive.")
        dates = [pd.Timestamp(value) for value in asdict(self.splits).values()]
        if any(left >= right for left, right in zip(dates, dates[1:])):
            raise ValueError("Split dates must be strictly increasing.")
        if not self.training.ridge_alphas or any(x <= 0 for x in self.training.ridge_alphas):
            raise ValueError("Supply positive ridge penalties.")
        if not self.training.xgboost_depths or any(x < 1 for x in self.training.xgboost_depths):
            raise ValueError("Supply positive XGBoost depths.")
        if (not self.training.xgboost_learning_rates
                or any(not 0 < x <= 1 for x in self.training.xgboost_learning_rates)):
            raise ValueError("Supply XGBoost learning rates in (0, 1].")

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), default=str, indent=2), encoding="utf-8")

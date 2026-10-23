"""Configuration for replay, guard, independent periods and review policy."""

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import pandas as pd

from eta_baselines.configuration import ExperimentConfig


@dataclass(frozen=True)
class GuardConfig:
    bin_seconds: int
    maximum_speed_knots: float
    maximum_bin_spread_meters: float
    maximum_velocity_gap_seconds: int


@dataclass(frozen=True)
class ReviewConfig:
    coverage_target: float
    maximum_half_width_minutes: float
    minimum_calibration_approaches: int
    minimum_evaluation_approaches: int
    age_only_threshold_minutes: float
    bootstrap_samples: int


@dataclass(frozen=True)
class OptimizedConfig:
    baseline_config: Path
    output_directory: Path
    later_csv: Path
    calibration_start: str
    evaluation_start: str
    evaluation_end: str
    training_delays_minutes: list[int]
    offsets_nautical_miles: list[float]
    affected_fractions: list[float]
    evaluation_seeds: list[int]
    guard: GuardConfig
    review: ReviewConfig

    @classmethod
    def load(cls, path: Path) -> "OptimizedConfig":
        contents = json.loads(path.read_text(encoding="utf-8"))
        for name in ("baseline_config", "output_directory", "later_csv"):
            contents[name] = (path.resolve().parent / contents[name]).resolve()
        contents["guard"] = GuardConfig(**contents["guard"])
        contents["review"] = ReviewConfig(**contents["review"])
        config = cls(**contents)
        dates = [pd.Timestamp(config.baseline.splits.end_exclusive),
                 pd.Timestamp(config.calibration_start), pd.Timestamp(config.evaluation_start),
                 pd.Timestamp(config.evaluation_end)]
        if dates[0] > dates[1] or any(a >= b for a, b in zip(dates[1:], dates[2:])):
            raise ValueError("Calibration/evaluation must follow baseline data and be disjoint.")
        positive = [*config.training_delays_minutes, *config.offsets_nautical_miles,
                    *asdict(config.guard).values(), config.review.maximum_half_width_minutes,
                    config.review.minimum_calibration_approaches,
                    config.review.minimum_evaluation_approaches, config.review.bootstrap_samples]
        if not positive or any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("Durations, thresholds and sample counts must be positive.")
        if (not config.affected_fractions or any(not 0 < x <= 1 for x in config.affected_fractions)
                or not 0 < config.review.coverage_target < 1 or not config.evaluation_seeds
                or len(set(config.evaluation_seeds)) != len(config.evaluation_seeds)):
            raise ValueError("Invalid fault fractions, coverage target or repeated seeds.")
        return config

    @property
    def baseline(self) -> ExperimentConfig:
        # Serving frozen checkpoints does not need the original training CSV;
        # fitting and replay preparation still validate their inputs directly.
        return ExperimentConfig.load(self.baseline_config, require_input=False)

    def snapshot(self) -> dict[str, object]:
        return json.loads(json.dumps(asdict(self), default=str))

    def frozen_baseline_model(self, name: str) -> Path:
        if name not in ("quadratic", "xgboost"):
            raise ValueError(f"Unknown baseline model: {name}")
        return self.output_directory / "frozen_baselines" / name / "model.joblib"

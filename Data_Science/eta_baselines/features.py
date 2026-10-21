"""One causal feature contract for model A, model B and saved-model inference."""

import numpy as np
import pandas as pd

from .approaches import Approach
from .configuration import FeatureConfig, GateConfig

METERS_PER_DEGREE = 111_195.0
LEGACY_FEATURE_COLUMNS = (
    "east_meters", "north_meters", "speed_knots", "course_sin", "course_cos",
    "mean_speed_knots", "mean_east_meters", "speed_trend_knots_per_minute",
    "is_tanker", "history_missing",
)
VESSEL_CLASS_COLUMNS = ("is_cargo", "is_tanker", "vessel_class_unknown")
FEATURE_COLUMNS = LEGACY_FEATURE_COLUMNS + ("is_cargo", "vessel_class_unknown")
FEATURE_SCHEMA_VERSION = "vessel_class_v2"
TARGET_COLUMN = "observation_to_arrival_minutes"


def vessel_class_features(value: object) -> dict[str, float]:
    """Encode known cargo/tanker and unavailable class as three distinct states.

    Missing, unspecified and unsupported codes carry no cargo/tanker assertion.
    Keep flags explicit so numeric imputation cannot turn unknown into cargo.
    """
    numeric = isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))
    valid = numeric and np.isfinite(value) and value % 1 == 0
    cargo = bool(valid and 70 <= value <= 79)
    tanker = bool(valid and 80 <= value <= 89)
    return {"is_cargo": float(cargo), "is_tanker": float(tanker),
            "vessel_class_unknown": float(not (cargo or tanker))}


class FeatureBuilder:
    """Summarize only history ending at the latest available observation."""

    def __init__(self, gate: GateConfig, config: FeatureConfig) -> None:
        self.gate = gate
        self.config = config

    def summarize(self, reports: pd.DataFrame) -> dict[str, float]:
        if reports.empty:
            raise ValueError("At least one available observation is required.")
        latest = reports.iloc[-1]
        start = latest["time"] - pd.Timedelta(minutes=self.config.history_minutes)
        recent = reports.loc[reports["time"] >= start]
        latitude_origin = (self.gate.south_latitude + self.gate.north_latitude) / 2
        longitude_scale = METERS_PER_DEGREE * np.cos(np.deg2rad(latitude_origin))
        valid_speeds = recent.dropna(subset=["sog"])
        trend = float("nan")
        if len(valid_speeds) >= 2:
            minutes = (valid_speeds["time"] - valid_speeds["time"].iloc[0]).dt.total_seconds() / 60
            if minutes.iloc[-1] > 0:
                trend = float(np.polyfit(minutes, valid_speeds["sog"], 1)[0])
        course = np.deg2rad(latest["cog"])
        return {
            "east_meters": float((latest["longitude"] - self.gate.longitude) * longitude_scale),
            "north_meters": float((latest["latitude"] - latitude_origin) * METERS_PER_DEGREE),
            "speed_knots": float(latest["sog"]),
            "course_sin": float(np.sin(course)),
            "course_cos": float(np.cos(course)),
            "mean_speed_knots": float(recent["sog"].mean()),
            "mean_east_meters": float(((recent["longitude"] - self.gate.longitude) * longitude_scale).mean()),
            "speed_trend_knots_per_minute": trend,
            **vessel_class_features(latest["vessel_type"]),
            "history_missing": float(len(recent) < 2 or len(valid_speeds) < 2),
        }

    def snapshot(self, reports: pd.DataFrame, decision_time: pd.Timestamp) -> pd.DataFrame:
        """Public inference entry: future observations cannot influence this snapshot."""
        available = reports.loc[reports["time"] <= decision_time].sort_values("time")
        if available.empty:
            raise ValueError(f"No reports available by {decision_time}.")
        row = self.summarize(available)
        row["observation_time"] = available["time"].iloc[-1]
        row["decision_time"] = decision_time
        return pd.DataFrame([row])

    def examples(self, approach: Approach) -> pd.DataFrame:
        reports = approach.observations
        first_time = reports["time"].iloc[0]
        start = first_time + pd.Timedelta(minutes=self.config.minimum_episode_minutes)
        frequency = f"{self.config.decision_interval_minutes}min"
        decisions = pd.date_range(start.ceil(frequency), approach.arrival_time, freq=frequency)
        examples: list[dict[str, object]] = []
        for decision in decisions:
            if decision >= approach.arrival_time:
                continue
            snapshot = self.snapshot(reports, decision).iloc[0].to_dict()
            observation_time = snapshot["observation_time"]
            snapshot.update({
                "approach_id": approach.approach_id,
                "mmsi": approach.mmsi,
                "episode_start": first_time,
                "arrival_time": approach.arrival_time,
                "crossing_before": approach.crossing_before,
                "crossing_after": approach.crossing_after,
                TARGET_COLUMN: (approach.arrival_time - observation_time).total_seconds() / 60,
            })
            examples.append(snapshot)
        return pd.DataFrame(examples)

"""One observable feature extractor used in training, replay and live verification."""

import numpy as np
import pandas as pd

from eta_baselines.configuration import ExperimentConfig
from eta_baselines.features import FEATURE_COLUMNS, FeatureBuilder
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, circular_summary, history_velocity

from .configuration import GuardConfig
from .quality import GuardResult, InputGuard

MOTION_COLUMNS = (
    "speed_median", "speed_q25", "speed_q75", "speed_iqr", "speed_variability",
    "low_speed_fraction", "course_dispersion", "recent_turn_degrees",
    "history_east_velocity_mps", "history_north_velocity_mps", "motion_fit_residual_meters",
)
QUALITY_COLUMNS = (
    "latest_received_age_minutes", "latest_usable_age_minutes", "maximum_gap_seconds",
    "occupied_minute_bins", "history_span_seconds", "missing_speed_fraction",
    "missing_course_fraction", "velocity_disagreement_mps", "flagged_fraction",
    "maximum_bin_spread_meters", "velocity_unavailable",
)
RICH_COLUMNS = FEATURE_COLUMNS + MOTION_COLUMNS
OPTIMIZED_COLUMNS = RICH_COLUMNS + QUALITY_COLUMNS


class OptimizedFeatures:
    def __init__(self, baseline: ExperimentConfig, guard_config: GuardConfig) -> None:
        self.baseline = baseline
        self.guard_config = guard_config
        self.base_builder = FeatureBuilder(baseline.gate, baseline.features)
        self.guard = InputGuard(baseline.gate, guard_config)

    def snapshot(
        self, available: pd.DataFrame, decision_time: pd.Timestamp, *, guarded: bool,
    ) -> tuple[pd.DataFrame, GuardResult]:
        delivered = available.loc[available["time"] <= decision_time].sort_values("time")
        if "delivered_time" in delivered:
            delivered = delivered.loc[delivered["delivered_time"] <= decision_time]
        delivered = delivered.drop_duplicates(
            ["mmsi", "time", "longitude", "latitude", "sog", "cog", "vessel_type"]
        )
        if delivered.empty:
            return pd.DataFrame(), GuardResult(delivered, 0, 0, 0, 0, ("no_reports",))
        latest_received = delivered["time"].max()
        # Bounded history is measured back from evidence, not shifted by hidden future reports.
        start = latest_received - pd.Timedelta(minutes=self.baseline.features.history_minutes)
        recent = delivered.loc[delivered["time"] >= start]
        result = self.guard.apply(recent) if guarded else GuardResult(recent, len(recent), 0, 0, 0, ())
        if result.reports.empty:
            return pd.DataFrame(), result
        usable = result.reports.sort_values("time")
        summary = self.base_builder.summarize(usable)
        summary.update({"observation_time": usable["time"].iloc[-1], "decision_time": decision_time})
        speeds = usable["sog"].dropna()
        for column, value in self._motion(usable, speeds).items():
            summary[column] = value
        gaps = usable["time"].diff().dt.total_seconds().dropna()
        span = (usable["time"].iloc[-1] - usable["time"].iloc[0]).total_seconds()
        east, north = summary["history_east_velocity_mps"], summary["history_north_velocity_mps"]
        last = usable.iloc[-1]
        direction = np.deg2rad(last["cog"])
        reported = last["sog"] * KNOTS_TO_METERS_PER_SECOND * np.array([np.sin(direction), np.cos(direction)])
        summary["latest_received_age_minutes"] = (decision_time - latest_received).total_seconds() / 60
        summary["latest_usable_age_minutes"] = (decision_time - last["time"]).total_seconds() / 60
        summary["maximum_gap_seconds"] = float(gaps.max()) if len(gaps) else np.nan
        summary["occupied_minute_bins"] = usable["time"].dt.floor("min").nunique()
        summary["history_span_seconds"] = span
        summary["missing_speed_fraction"] = usable["sog"].isna().mean()
        summary["missing_course_fraction"] = usable["cog"].isna().mean()
        summary["velocity_disagreement_mps"] = float(np.linalg.norm(np.array([east, north]) - reported))
        summary["flagged_fraction"] = result.flagged_fraction
        summary["maximum_bin_spread_meters"] = result.maximum_bin_spread_meters
        summary["velocity_unavailable"] = float(not np.isfinite(east + north))
        return pd.DataFrame([summary]), result

    def _motion(self, usable: pd.DataFrame, speeds: pd.Series) -> dict[str, float]:
        quantiles = speeds.quantile([.25, .5, .75])
        direction_valid = usable.loc[usable["sog"] > .5, "cog"].dropna().to_numpy()
        dispersion = circular_summary(direction_valid)[1]
        turn = (abs((direction_valid[-1] - direction_valid[0] + 180) % 360 - 180)
                if len(direction_valid) >= 2 else np.nan)
        gaps = usable["time"].diff().dt.total_seconds()
        continuous = gaps.dropna().le(self.guard_config.maximum_velocity_gap_seconds).all()
        east, north, residual = history_velocity(usable, self.baseline.gate) if continuous else (np.nan, np.nan, np.nan)
        if np.isfinite(east + north) and np.hypot(east, north) < .05:
            east, north = np.nan, np.nan
        mean = speeds.mean()
        return {
            "speed_median": float(quantiles.loc[.5]), "speed_q25": float(quantiles.loc[.25]),
            "speed_q75": float(quantiles.loc[.75]),
            "speed_iqr": float(quantiles.loc[.75] - quantiles.loc[.25]),
            "speed_variability": float(speeds.std() / mean) if mean > 0 else np.nan,
            "low_speed_fraction": float((speeds <= .5).mean()) if len(speeds) else np.nan,
            "course_dispersion": dispersion, "recent_turn_degrees": float(turn),
            "history_east_velocity_mps": east, "history_north_velocity_mps": north,
            "motion_fit_residual_meters": residual,
        }

"""Optional inference adapter around C's unchanged feature extractor and model."""

from dataclasses import dataclass

import pandas as pd

from Optimized_Model.features import OptimizedFeatures
from Optimized_Model.quality import GuardResult
from ..navigation_features import repaired_navigation_features
from .missing_speed_mitigation import MissingSpeedMitigation, SpeedRepair, SpeedStatus

SPEED_FEATURES = (
    "speed_knots", "mean_speed_knots", "speed_trend_knots_per_minute", "speed_median",
    "speed_q25", "speed_q75", "speed_iqr", "speed_variability", "low_speed_fraction",
    "course_dispersion", "recent_turn_degrees", "velocity_disagreement_mps",
)


@dataclass(frozen=True)
class MissingSpeedSnapshot:
    original_features: pd.DataFrame
    mitigated_features: pd.DataFrame
    guard: GuardResult
    repair: SpeedRepair


def missing_speed_snapshot(reports: pd.DataFrame, decision_time: pd.Timestamp | str,
                           extractor: OptimizedFeatures,
                           mitigation: MissingSpeedMitigation) -> MissingSpeedSnapshot:
    """Guard actual reports once, then derive only supported speed-related features.

    Preserve observed missing-speed fraction, history_missing, real clocks and all
    guard/position diagnostics. Never re-run the position guard on repaired SOG.
    Audit and effective report tables are separate from the 34-feature model input.
    """
    if mitigation.gate != extractor.baseline.gate:
        raise ValueError("Mitigation and feature extractor must use the same geographic reference.")
    received, clock = mitigation._prepare(reports, decision_time)
    original, guard = extractor.snapshot(received, clock, guarded=True)
    repair = mitigation.repair_reports(guard.reports, clock)
    features = original.copy(deep=True)
    if original.empty or not any(row.status == SpeedStatus.ESTIMATED for row in repair.audit):
        return MissingSpeedSnapshot(original, features, guard, repair)
    features = repaired_navigation_features(original, repair.reports, extractor, SPEED_FEATURES)
    return MissingSpeedSnapshot(original, features, guard, repair)

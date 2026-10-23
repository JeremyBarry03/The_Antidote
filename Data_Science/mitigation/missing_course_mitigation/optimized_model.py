"""Opt-in missing-course adapter around the unchanged optimized XGBoost."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from Optimized_Model.features import OptimizedFeatures
from Optimized_Model.quality import GuardResult
from ..navigation_features import repaired_navigation_features
from .missing_course_mitigation import CourseRepair, CourseStatus, MissingCourseMitigation

COURSE_FEATURES = (
    "course_sin", "course_cos", "course_dispersion", "recent_turn_degrees", "velocity_disagreement_mps",
)


@dataclass(frozen=True)
class MissingCourseSnapshot:
    original_features: pd.DataFrame
    mitigated_features: pd.DataFrame
    guard: GuardResult
    repair: CourseRepair


def missing_course_snapshot(reports: pd.DataFrame, decision_time: pd.Timestamp | str,
                            extractor: OptimizedFeatures,
                            mitigation: MissingCourseMitigation) -> MissingCourseSnapshot:
    """Guard once; derive course features while retaining original missingness/clocks."""
    if mitigation.gate != extractor.baseline.gate:
        raise ValueError("Mitigation and feature extractor must use the same geographic reference.")
    received, clock = mitigation._prepare(reports, decision_time)
    courses = mitigation._numeric_field(received, "cog")
    invalid = ~np.isfinite(courses) | (courses < 0) | (courses >= 360)
    if invalid.any():
        # AIS 360 means unavailable; circular aggregation must not turn it into north.
        received["cog"] = np.where(invalid, np.nan, courses)
    original, guard = extractor.snapshot(received, clock, guarded=True)
    repair = mitigation.repair_reports(guard.reports, clock)
    features = original.copy(deep=True)
    if not original.empty and any(row.status == CourseStatus.ESTIMATED for row in repair.audit):
        features = repaired_navigation_features(original, repair.reports, extractor, COURSE_FEATURES)
    return MissingCourseSnapshot(original, features, guard, repair)

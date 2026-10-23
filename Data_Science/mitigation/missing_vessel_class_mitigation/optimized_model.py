"""Optional three-feature adapter; source reports and frozen models stay intact."""

from dataclasses import dataclass

import pandas as pd

from Optimized_Model.features import OptimizedFeatures
from Optimized_Model.quality import GuardResult
from .missing_vessel_class_mitigation import MissingVesselClassMitigation, MissingVesselClassResult, VesselClassStatus

CLASS_FEATURES = ("is_cargo", "is_tanker", "vessel_class_unknown")


@dataclass(frozen=True)
class VesselClassSnapshot:
    original_features: pd.DataFrame
    mitigated_features: pd.DataFrame
    guard: GuardResult
    mitigation: MissingVesselClassResult


def vessel_class_snapshot(reports: pd.DataFrame, decision_time: pd.Timestamp | str,
                          extractor: OptimizedFeatures,
                          mitigation: MissingVesselClassMitigation) -> VesselClassSnapshot:
    received, clock = mitigation._prepare_reports(reports, decision_time)
    result = mitigation.apply(received, clock)
    original, guard = extractor.snapshot(received, clock, guarded=True)
    features = original.copy(deep=True)
    if not original.empty and original.vessel_class_unknown.iloc[0] == 1 and result.status == VesselClassStatus.RECOVERED:
        features["is_cargo"] = float(result.recovered_class == "cargo")
        features["is_tanker"] = float(result.recovered_class == "tanker")
        features["vessel_class_unknown"] = 0.0
    elif not original.empty and "conflicting_current_class" in result.reasons:
        features["is_cargo"], features["is_tanker"], features["vessel_class_unknown"] = 0.0, 0.0, 1.0
    return VesselClassSnapshot(original, features, guard, result)

"""Recompute explicitly selected navigation features without changing provenance."""

import numpy as np
import pandas as pd

from Optimized_Model.features import OptimizedFeatures
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND


def repaired_navigation_features(original: pd.DataFrame, effective: pd.DataFrame,
                                 extractor: OptimizedFeatures, columns: tuple[str, ...]) -> pd.DataFrame:
    """Caller supplies the original guarded snapshot and a private repaired feed."""
    values = extractor.base_builder.summarize(effective)
    values.update(extractor._motion(effective, effective.sog.dropna()))
    east = original.history_east_velocity_mps.iloc[0]
    north = original.history_north_velocity_mps.iloc[0]
    last = effective.iloc[-1]
    direction = np.deg2rad(last.cog)
    reported = last.sog * KNOTS_TO_METERS_PER_SECOND * np.array([np.sin(direction), np.cos(direction)])
    values["velocity_disagreement_mps"] = float(np.linalg.norm(np.array([east, north]) - reported))
    features = original.copy(deep=True)
    for name in columns:
        features[name] = values[name]
    return features

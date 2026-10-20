"""Bound repeated-report influence and screen impossible jumps without future data."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, circular_summary, local_positions

from .configuration import GuardConfig


@dataclass(frozen=True)
class GuardResult:
    reports: pd.DataFrame
    received_count: int
    removed_count: int
    flagged_fraction: float
    maximum_bin_spread_meters: float
    reasons: tuple[str, ...]


class InputGuard:
    def __init__(self, gate: GateConfig, config: GuardConfig) -> None:
        self.gate = gate
        self.config = config

    def apply(self, reports: pd.DataFrame) -> GuardResult:
        if reports.empty:
            return GuardResult(reports.copy(), 0, 0, 0, 0, ("no_reports",))
        # Exact duplicate values have equal treatment in guarded and unguarded paths.
        columns = ["mmsi", "time", "longitude", "latitude", "sog", "cog", "vessel_type"]
        unique = reports.drop_duplicates(columns).sort_values("time").copy()
        positions = local_positions(unique, self.gate)
        seconds = unique["time"].to_numpy(dtype="datetime64[ns]").astype(np.int64) / 1e9
        bins = np.floor(seconds / self.config.bin_seconds)
        boundaries = np.r_[0, np.flatnonzero(np.diff(bins)) + 1, len(unique)]
        values = unique[["longitude", "latitude", "sog", "cog"]].to_numpy(dtype=float)
        summaries = []
        spread_flags = 0
        maximum_spread = 0.0
        for start, stop in zip(boundaries[:-1], boundaries[1:]):
            group = values[start:stop]
            medians = [float(np.median(column[np.isfinite(column)])) if np.isfinite(column).any()
                       else float("nan") for column in group[:, :3].T]
            summaries.append([*medians, circular_summary(group[:, 3])[0]])
            points = positions[start:stop]
            spread = float(np.linalg.norm(points - np.median(points, axis=0), axis=1).max())
            maximum_spread = max(maximum_spread, spread)
            span = seconds[stop - 1] - seconds[start]
            speeds = group[:, 2][np.isfinite(group[:, 2])]
            expected_motion = max(0, speeds.max() if len(speeds) else 0) * KNOTS_TO_METERS_PER_SECOND * span
            spread_flags += int(spread > self.config.maximum_bin_spread_meters + expected_motion)
        binned = unique.iloc[boundaries[1:] - 1].reset_index(drop=True).copy()
        binned[["longitude", "latitude", "sog", "cog"]] = np.asarray(summaries)
        positions = local_positions(binned, self.gate)
        times = seconds[boundaries[1:] - 1]
        accepted: list[int] = []
        rejected = 0
        for index, coordinates in enumerate(binned[["longitude", "latitude"]].to_numpy()):
            if not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90):
                rejected += 1
                continue
            if accepted:
                last = accepted[-1]
                elapsed_seconds = times[index] - times[last]
                distance = float(np.linalg.norm(positions[index] - positions[last]))
                if (0 < elapsed_seconds <= self.config.maximum_velocity_gap_seconds
                        and distance / elapsed_seconds > self.config.maximum_speed_knots * KNOTS_TO_METERS_PER_SECOND):
                    rejected += 1
                    continue
            accepted.append(index)
        reasons = []
        if rejected:
            reasons.append("implausible_position_jump")
        if spread_flags:
            reasons.append("conflicting_bin_positions")
        if len(unique) > len(binned):
            reasons.append("bounded_repeated_report_weight")
        return GuardResult(
            binned.iloc[accepted].reset_index(drop=True), len(reports),
            len(reports) - len(accepted), min(1.0, (rejected + spread_flags) / len(binned)),
            maximum_spread, tuple(reasons),
        )

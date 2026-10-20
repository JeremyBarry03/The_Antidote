"""Directional gate-crossing labels and approach enrollment."""

from dataclasses import dataclass

import pandas as pd

from .configuration import GateConfig


@dataclass(frozen=True)
class Approach:
    approach_id: str
    mmsi: str
    observations: pd.DataFrame
    arrival_time: pd.Timestamp
    crossing_before: pd.Timestamp
    crossing_after: pd.Timestamp


def crossing_time(
    before: pd.Series, after: pd.Series, gate: GateConfig,
) -> pd.Timestamp | None:
    """Interpolate only short, east-to-west intersections with the gate segment."""
    gap_seconds = (after["time"] - before["time"]).total_seconds()
    if not 0 < gap_seconds <= gate.maximum_crossing_gap_seconds:
        return None
    if not before["longitude"] > gate.longitude >= after["longitude"]:
        return None
    fraction = ((before["longitude"] - gate.longitude)
                / (before["longitude"] - after["longitude"]))
    latitude = before["latitude"] + fraction * (after["latitude"] - before["latitude"])
    if not gate.south_latitude <= latitude <= gate.north_latitude:
        return None
    return before["time"] + pd.Timedelta(seconds=fraction * gap_seconds)


class ApproachBuilder:
    """Enroll on an observed east-side entry; reset on crossing, exit or long gap."""

    def __init__(self, gate: GateConfig) -> None:
        self.gate = gate

    def build(self, observations: pd.DataFrame) -> tuple[list[Approach], dict[str, int]]:
        approaches: list[Approach] = []
        audit = {"enrollments": 0, "unresolved_episodes": 0, "qualifying_crossings": 0}
        for mmsi, vessel in observations.groupby("mmsi", sort=False):
            vessel = vessel.reset_index(drop=True)
            start: int | None = None
            for index in range(len(vessel)):
                current = vessel.iloc[index]
                if index and start is not None:
                    previous = vessel.iloc[index - 1]
                    gap_hours = (current["time"] - previous["time"]).total_seconds() / 3600
                    if gap_hours > self.gate.episode_break_hours:
                        audit["unresolved_episodes"] += 1
                        start = None
                    else:
                        arrival = crossing_time(previous, current, self.gate)
                        if arrival is not None:
                            approaches.append(Approach(
                                approach_id=f"{mmsi}_{current['time'].strftime('%Y%m%dT%H%M%S')}",
                                mmsi=str(mmsi),
                                observations=vessel.iloc[start:index].copy(),
                                arrival_time=arrival,
                                crossing_before=previous["time"],
                                crossing_after=current["time"],
                            ))
                            audit["qualifying_crossings"] += 1
                            start = None
                inside = (
                    self.gate.longitude < current["longitude"] <= self.gate.approach_east_longitude
                    and self.gate.approach_south_latitude <= current["latitude"]
                    <= self.gate.approach_north_latitude
                )
                if start is not None and not inside:
                    audit["unresolved_episodes"] += 1
                    start = None
                if start is None and inside:
                    start = index
                    audit["enrollments"] += 1
            if start is not None:
                audit["unresolved_episodes"] += 1
        return approaches, audit

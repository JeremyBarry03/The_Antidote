"""Deterministic delivered-time replay; hidden fault truth stays in a separate log."""

from dataclasses import dataclass
from enum import Enum
import hashlib

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE


class Condition(str, Enum):
    NOMINAL = "nominal"
    STALE = "stale"
    QUALITY = "quality"
    COMBINED = "combined"


@dataclass(frozen=True)
class Scenario:
    name: str
    condition: Condition = Condition.NOMINAL
    delay_minutes: float = 0
    offset_nautical_miles: float = 0
    affected_fraction: float = 0
    repetition: int = 1
    total_repetition: int = 1
    drift: bool = False
    repetition_jitter_meters: float = 0

    def __post_init__(self) -> None:
        if (self.delay_minutes < 0 or self.offset_nautical_miles < 0
                or not 0 <= self.affected_fraction <= 1
                or self.repetition < 1 or self.total_repetition < 1 or self.repetition_jitter_meters < 0):
            raise ValueError("Scenario delay, offset, fraction and repetition are invalid.")
        if self.condition == Condition.NOMINAL and (
            self.delay_minutes or self.offset_nautical_miles or self.affected_fraction
        ):
            raise ValueError("Nominal scenarios cannot introduce faults.")
        if self.condition == Condition.STALE and (self.offset_nautical_miles or self.affected_fraction):
            raise ValueError("Stale-only scenarios must preserve observed values.")
        if self.condition == Condition.QUALITY and self.delay_minutes:
            raise ValueError("Quality-only scenarios must preserve timing.")


@dataclass(frozen=True)
class ReportStream:
    reports: pd.DataFrame
    modification_log: pd.DataFrame

    def available(self, decision_time: pd.Timestamp) -> pd.DataFrame:
        reports = self.reports
        return reports.loc[
            (reports["time"] <= decision_time) & (reports["delivered_time"] <= decision_time)
        ].copy()


def seeded_generator(seed: int, identity: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{identity}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


def create_stream(
    reports: pd.DataFrame, scenario: Scenario, seed: int, gate: GateConfig,
) -> ReportStream:
    """Fault selection is stable per event, even when later observations are appended."""
    changed = reports.sort_values("time").reset_index(drop=True).copy()
    changed["record_id"] = [f"{row.mmsi}:{row.time.isoformat()}" for row in changed.itertuples()]
    changed["delivered_time"] = changed["time"] + pd.Timedelta(minutes=scenario.delay_minutes)
    # Hash each identity instead of drawing a length-dependent batch of random numbers.
    fractions = np.array([
        int.from_bytes(hashlib.sha256(f"{seed}:{identity}".encode()).digest()[:8], "little") / 2**64
        for identity in changed["record_id"]
    ])
    affected = fractions < scenario.affected_fraction
    direction = seeded_generator(seed, "offset-direction").uniform(0, 2 * np.pi)
    offset = np.full(len(changed), scenario.offset_nautical_miles * 1852, dtype=float)
    if scenario.drift:
        # A fixed clock scale, never the future episode duration, sets the drift rate.
        elapsed = (changed["time"] - changed["time"].iloc[0]).dt.total_seconds().to_numpy()
        offset *= np.clip(elapsed / 3600, 0, 1)
    east = affected * offset * np.sin(direction)
    north = affected * offset * np.cos(direction)
    if scenario.drift:
        # Along-route direction uses this event and its predecessor, never future positions.
        delta = changed[["longitude", "latitude"]].diff().to_numpy()
        latitude_origin = (gate.south_latitude + gate.north_latitude) / 2
        delta[:, 0] *= np.cos(np.deg2rad(latitude_origin))
        lengths = np.linalg.norm(delta, axis=1)
        valid = np.isfinite(lengths) & (lengths > 0)
        east[valid] = affected[valid] * offset[valid] * delta[valid, 0] / lengths[valid]
        north[valid] = affected[valid] * offset[valid] * delta[valid, 1] / lengths[valid]
    latitude_origin = (gate.south_latitude + gate.north_latitude) / 2
    changed["longitude"] += east / (METERS_PER_DEGREE * np.cos(np.deg2rad(latitude_origin)))
    changed["latitude"] += north / METERS_PER_DEGREE
    log = changed[["record_id", "time", "delivered_time"]].copy()
    log["fault_applied"] = affected & (offset > 0)
    log["east_offset_meters"] = east
    log["north_offset_meters"] = north
    log["scenario"] = scenario.name
    log["seed"] = seed
    copies = [changed]
    audit_copies = [log]
    for replica in range(1, scenario.repetition):
        repeat = changed.loc[affected].copy()
        repeat["record_id"] += f":repeat-{replica}"
        repeat["latitude"] += scenario.repetition_jitter_meters * replica / METERS_PER_DEGREE
        copies.append(repeat)
        repeated_log = log.loc[affected].copy()
        repeated_log["record_id"] += f":repeat-{replica}"
        repeated_log["north_offset_meters"] += scenario.repetition_jitter_meters * replica
        audit_copies.append(repeated_log)
    for replica in range(1, scenario.total_repetition):
        repeat = changed.copy()
        repeat["record_id"] += f":volume-{replica}"
        repeat["latitude"] += scenario.repetition_jitter_meters * replica / METERS_PER_DEGREE
        copies.append(repeat)
        repeated_log = log.copy()
        repeated_log["record_id"] += f":volume-{replica}"
        repeated_log["north_offset_meters"] += scenario.repetition_jitter_meters * replica
        audit_copies.append(repeated_log)
    delivered = pd.concat(copies, ignore_index=True).sort_values(["time", "record_id"])
    return ReportStream(delivered, pd.concat(audit_copies, ignore_index=True))

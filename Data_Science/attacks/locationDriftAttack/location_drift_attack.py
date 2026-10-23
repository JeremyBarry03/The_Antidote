"""Smooth coordinate bias with source motion, clocks and reference labels intact."""

from dataclasses import dataclass
import math
from typing import ClassVar

import numpy as np
import pandas as pd

from Optimized_Model.replay import Condition, ReportStream, seeded_generator
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.drift_profile import smooth_bias
from attacks.positionJumpAttack.position_jump_attack import EARTH_RADIUS_METERS, _coordinates, _destination, _distance
from attacks.sensorDriftAttack import SensorDriftConfig


@dataclass(frozen=True)
class LocationDriftConfig:
    drift_rate_meters_per_minute: float = 20.
    maximum_bias_meters: float = 1852.
    rate_variation_fraction: float = .25
    variation_period_minutes: float = 20.
    bearing_degrees: float | None = None
    seed: int = 42
    target_mmsi: str | None = None
    start_time: pd.Timestamp | str | None = None

    def __post_init__(self) -> None:
        # Reuse common smooth-profile/identity/time validation; no attack is run.
        validated = SensorDriftConfig(rate_variation_fraction=self.rate_variation_fraction,
            variation_period_minutes=self.variation_period_minutes, seed=self.seed,
            target_mmsi=self.target_mmsi, start_time=self.start_time)
        object.__setattr__(self, "start_time", validated.start_time)
        for name in ("drift_rate_meters_per_minute", "maximum_bias_meters"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative.")
        if self.maximum_bias_meters > math.pi * EARTH_RADIUS_METERS:
            raise ValueError("maximum_bias_meters cannot exceed half the Earth's circumference.")
        bearing = self.bearing_degrees
        if bearing is not None and (isinstance(bearing, bool) or not isinstance(bearing, (float, int))
                                   or not math.isfinite(bearing) or not 0 <= bearing < 360):
            raise ValueError("bearing_degrees must be finite in [0, 360), or None.")


@dataclass(frozen=True)
class LocationDriftAttack(BaseAttack):
    config: LocationDriftConfig = LocationDriftConfig()
    name: ClassVar[str] = "LocationDriftAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        settings = self.config
        return {"drift_rate_meters_per_minute": settings.drift_rate_meters_per_minute,
                "maximum_bias_meters": settings.maximum_bias_meters,
                "rate_variation_fraction": settings.rate_variation_fraction,
                "variation_period_minutes": settings.variation_period_minutes,
                "bearing_degrees": settings.bearing_degrees, "seed": settings.seed,
                "target_mmsi": settings.target_mmsi,
                "start_time": settings.start_time.isoformat() if settings.start_time is not None else None}

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        latitude, longitude = (_coordinates(prepared, field) for field in ("latitude", "longitude"))
        eligible = (np.isfinite(latitude) & np.isfinite(longitude)
                    & (np.abs(latitude) <= 90) & (np.abs(longitude) <= 180))
        magnitude = np.zeros(len(prepared))
        bearings = np.zeros(len(prepared))
        settings = self.config
        for mmsi, positions in prepared.groupby(prepared.mmsi.astype(str), sort=False).indices.items():
            if settings.target_mmsi is not None and mmsi != settings.target_mmsi:
                continue
            times = prepared.time.iloc[positions]
            start = settings.start_time if settings.start_time is not None else times.min()
            try:
                elapsed = ((times - start).dt.total_seconds() / 60).to_numpy().clip(min=0)
            except TypeError as error:
                raise ValueError("start_time and report times must use compatible timezones.") from error
            magnitude[positions] = smooth_bias(elapsed, rate=settings.drift_rate_meters_per_minute,
                variation=settings.rate_variation_fraction, period_minutes=settings.variation_period_minutes,
                maximum=settings.maximum_bias_meters, seed=settings.seed, identity=f"location-drift:{mmsi}")
            direction = settings.bearing_degrees
            if direction is None:
                direction = float(seeded_generator(settings.seed, f"location-drift-bearing:{mmsi}").uniform(0, 360))
            bearings[positions] = direction
        reported_latitude, reported_longitude = latitude.copy(), longitude.copy()
        selected = eligible & (magnitude > 0)
        if selected.any():
            reported_latitude[selected], reported_longitude[selected] = _destination(
                latitude[selected], longitude[selected], magnitude[selected], bearings[selected])
        affected = selected & ((reported_latitude != latitude) | (reported_longitude != longitude))
        if affected.any():
            prepared["latitude"], prepared["longitude"] = reported_latitude, reported_longitude
        applied_distance = np.zeros(len(prepared))
        applied_distance[affected] = _distance(latitude[affected], longitude[affected],
                                              reported_latitude[affected], reported_longitude[affected])
        audit = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        audit["eligible_position"] = eligible
        audit["original_latitude"], audit["original_longitude"] = latitude, longitude
        audit["reported_latitude"], audit["reported_longitude"] = reported_latitude, reported_longitude
        audit["requested_displacement_meters"], audit["applied_displacement_meters"] = magnitude, applied_distance
        audit["bearing_degrees"], audit["fault_applied"] = bearings, affected
        audit["action"] = np.where(affected, "location_drifted", "retained")
        audit["attack"], audit["seed"] = self.name, settings.seed
        return ReportStream(prepared.sort_values("time", kind="stable"), audit)

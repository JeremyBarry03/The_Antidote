"""Displace selected reported locations without changing the reference voyage."""

from dataclasses import dataclass
import math
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_numeric_dtype

from Optimized_Model.replay import Condition, ReportStream, seeded_generator
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.missing_field import MissingFieldConfig, select_reports
from attacks.reportingGapAttack import ReportingGapConfig

EARTH_RADIUS_METERS = 6_371_000.


@dataclass(frozen=True)
class PositionJumpConfig:
    """Report prevalence, displacement severity and active window are independent."""

    displacement_meters: float = 2000.
    affected_fraction: float = .25
    seed: int = 42
    target_mmsi: str | None = None
    bearing_degrees: float | None = None
    start_time: pd.Timestamp | str | None = None
    end_time: pd.Timestamp | str | None = None

    def __post_init__(self) -> None:
        self.selection  # Reuse the existing prevalence/identity validation.
        distance = self.displacement_meters
        if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                or not math.isfinite(distance) or not 0 <= distance <= math.pi*EARTH_RADIUS_METERS):
            raise ValueError("displacement_meters must be finite and between zero and half the Earth's circumference.")
        bearing = self.bearing_degrees
        if bearing is not None and (isinstance(bearing, bool) or not isinstance(bearing, (int, float))
                or not math.isfinite(bearing) or not 0 <= bearing < 360):
            raise ValueError("bearing_degrees must be a finite number in [0, 360), or None.")
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("Provide both start_time and end_time, or neither.")
        if self.start_time is not None:
            window = ReportingGapConfig(self.start_time, self.end_time, self.target_mmsi)
            object.__setattr__(self, "start_time", window.start_time)
            object.__setattr__(self, "end_time", window.end_time)

    @property
    def selection(self) -> MissingFieldConfig:
        return MissingFieldConfig(self.affected_fraction, self.seed, self.target_mmsi)


def _coordinates(reports: pd.DataFrame, field: str) -> np.ndarray:
    if field not in reports:
        raise ValueError(f"Missing position column: {field}.")
    values = reports[field]
    if not is_numeric_dtype(values) or is_bool_dtype(values) or is_complex_dtype(values):
        raise ValueError(f"{field} must contain parsed real numeric coordinates or missing values.")
    return values.to_numpy(dtype=float, na_value=np.nan, copy=True)


def _destination(latitude: np.ndarray, longitude: np.ndarray, distance_meters: float,
                 bearing_degrees: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Spherical forward geodesic keeps meter distances meaningful at any latitude."""
    lat, lon, bearing = np.deg2rad(latitude), np.deg2rad(longitude), np.deg2rad(bearing_degrees)
    angle = distance_meters/EARTH_RADIUS_METERS
    new_lat = np.arcsin(np.clip(np.sin(lat)*np.cos(angle)
                               + np.cos(lat)*np.sin(angle)*np.cos(bearing), -1., 1.))
    new_lon = lon+np.arctan2(np.sin(bearing)*np.sin(angle)*np.cos(lat),
                           np.cos(angle)-np.sin(lat)*np.sin(new_lat))
    return np.rad2deg(new_lat), (np.rad2deg(new_lon)+180) % 360-180


def _distance(latitude: np.ndarray, longitude: np.ndarray,
              other_latitude: np.ndarray, other_longitude: np.ndarray) -> np.ndarray:
    lat, other_lat = np.deg2rad(latitude), np.deg2rad(other_latitude)
    delta_lat, delta_lon = other_lat-lat, np.deg2rad(other_longitude-longitude)
    haversine = np.sin(delta_lat/2)**2+np.cos(lat)*np.cos(other_lat)*np.sin(delta_lon/2)**2
    return 2*EARTH_RADIUS_METERS*np.arcsin(np.sqrt(np.clip(haversine, 0., 1.)))


@dataclass(frozen=True)
class PositionJumpAttack(BaseAttack):
    """Change only latitude/longitude; subsequent unselected fixes recover naturally."""

    config: PositionJumpConfig = PositionJumpConfig()
    name: ClassVar[str] = "PositionJumpAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return {**self.config.selection.as_parameters(), "displacement_meters": self.config.displacement_meters,
                "bearing_degrees": self.config.bearing_degrees,
                "start_time": self.config.start_time.isoformat() if self.config.start_time is not None else None,
                "end_time": self.config.end_time.isoformat() if self.config.end_time is not None else None}

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        latitude, longitude = (_coordinates(prepared, column) for column in ("latitude", "longitude"))
        eligible = (np.isfinite(latitude) & np.isfinite(longitude)
                    & (latitude >= -90) & (latitude <= 90) & (longitude >= -180) & (longitude <= 180))
        in_window = np.ones(len(prepared), dtype=bool)
        if self.config.start_time is not None:
            try:
                in_window = (prepared.time.ge(self.config.start_time) & prepared.time.lt(self.config.end_time)).to_numpy()
            except TypeError as error:
                raise ValueError("Attack window and report times must use compatible timezones.") from error
        selected = select_reports(prepared, self.config.selection).to_numpy() & eligible & in_window
        bearing = np.full(len(prepared), np.nan)
        for mmsi, positions in prepared.groupby(prepared.mmsi.astype(str), sort=False).indices.items():
            direction = self.config.bearing_degrees
            if direction is None:
                direction = float(seeded_generator(self.config.seed, f"position-jump:{mmsi}").uniform(0,360))
            bearing[positions] = direction
        reported_latitude, reported_longitude = latitude.copy(), longitude.copy()
        if self.config.displacement_meters > 0 and selected.any():
            reported_latitude[selected], reported_longitude[selected] = _destination(
                latitude[selected], longitude[selected], self.config.displacement_meters, bearing[selected])
        affected = selected & ((reported_latitude != latitude) | (reported_longitude != longitude))
        if affected.any():
            prepared["latitude"], prepared["longitude"] = reported_latitude, reported_longitude
        applied_distance = np.zeros(len(prepared))
        applied_distance[affected] = _distance(latitude[affected], longitude[affected],
                                              reported_latitude[affected], reported_longitude[affected])
        audit = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        audit["eligible_position"], audit["in_window"], audit["selected"] = eligible, in_window, selected
        audit["original_latitude"], audit["original_longitude"] = latitude, longitude
        audit["reported_latitude"], audit["reported_longitude"] = reported_latitude, reported_longitude
        audit["requested_displacement_meters"] = np.where(selected, self.config.displacement_meters, 0.)
        audit["applied_displacement_meters"] = applied_distance
        audit["bearing_degrees"] = bearing
        audit["fault_applied"] = affected
        audit["action"] = np.where(affected, "position_shifted", "retained")
        audit["attack"], audit["seed"] = self.name, self.config.seed
        return ReportStream(prepared, audit)

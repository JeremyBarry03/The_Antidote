"""Detect coordinate drift and reconstruct briefly from an independent anchor."""

from dataclasses import asdict, dataclass
from enum import Enum
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, local_positions
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult
from .._drift_helpers import angle_difference, ewma_fraction, finite, prepare, validate_config


@dataclass(frozen=True, kw_only=True)
class PositionAnchor:
    """Caller-verified position, with measurement and availability provenance.

    A position from the suspect AIS feed is not independently verified merely
    because a detector accepted it. Source must identify the verification source.
    """

    mmsi: str
    time: pd.Timestamp | str
    longitude: float
    latitude: float
    source: str
    received_time: pd.Timestamp | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mmsi, str) or not self.mmsi.strip():
            raise ValueError("Position anchor requires a nonempty MMSI string.")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("Position anchor requires a verification source.")
        for name, limit in (("longitude", 180), ("latitude", 90)):
            value = getattr(self, name)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not np.isfinite(value) or not -limit <= value <= limit):
                raise ValueError(f"Position anchor {name} must be a valid coordinate.")
        try:
            measured = pd.Timestamp(self.time)
            received = measured if self.received_time is None else pd.Timestamp(self.received_time)
            if pd.isna(measured) or pd.isna(received) or received < measured:
                raise ValueError("Position anchor availability cannot precede measurement.")
        except (TypeError, ValueError) as error:
            raise ValueError("Position anchor requires valid, compatible measurement/availability times.") from error
        object.__setattr__(self, "time", measured)
        object.__setattr__(self, "received_time", received)


class LocationDriftStatus(str, Enum):
    NO_REPORTS = "no_reports"
    WARMING_UP = "warming_up"
    NORMAL = "normal"
    DRIFT = "location_drift"
    RECONSTRUCTED = "reconstructed"
    REVIEW = "requires_review"


@dataclass(frozen=True)
class LocationDriftMitigationConfig:
    """Initial local-motion policy; thresholds need development calibration."""

    ewma_time_constant_minutes: float = 2.
    minimum_disagreement_meters_per_minute: float = 4.
    drift_threshold_meters_per_minute: float = 8.
    minimum_persistent_reports: int = 3
    minimum_persistence_minutes: float = 2.
    minimum_accumulated_disagreement_meters: float = 30.
    maximum_direction_change_degrees: float = 45.
    maximum_gap_seconds: float = 180.
    maximum_report_age_minutes: float = 5.
    maximum_speed_knots: float = 60.
    maximum_course_change_degrees: float = 15.
    maximum_speed_change_knots_per_minute: float = 2.
    stationary_speed_knots: float = .1
    maximum_projection_minutes: float = 5.

    def __post_init__(self) -> None:
        validate_config(self, ("minimum_persistent_reports",))
        if self.minimum_disagreement_meters_per_minute > self.drift_threshold_meters_per_minute:
            raise ValueError("The minimum disagreement cannot exceed the drift threshold.")
        if max(self.maximum_direction_change_degrees, self.maximum_course_change_degrees) > 180:
            raise ValueError("Direction thresholds cannot exceed 180 degrees.")
        if self.stationary_speed_knots >= self.maximum_speed_knots:
            raise ValueError("The stationary threshold must be below maximum_speed_knots.")


@dataclass(frozen=True)
class LocationDriftMitigationResult(MitigationResult):
    status: LocationDriftStatus
    drift_detected: bool = False
    ewma_disagreement_meters_per_minute: float | None = None
    accumulated_disagreement_meters: float = 0.
    persistent_report_count: int = 0
    persistent_minutes: float = 0.
    anomaly_since: pd.Timestamp | None = None
    reference_supported: bool = False
    correction_applied: bool = False
    reported_longitude: float | None = None
    reported_latitude: float | None = None
    longitude: float | None = None
    latitude: float | None = None
    position_source: str = "unavailable"
    anchor_time: pd.Timestamp | None = None
    anchor_source: str | None = None
    projection_minutes: float | None = None

    @property
    def anomaly_detected(self) -> bool:
        return self.drift_detected

    @property
    def can_predict(self) -> bool:
        """Input reliability recommendation; this class never edits an ETA."""
        return ((self.status == LocationDriftStatus.NORMAL and not self.drift_detected)
                or (self.status == LocationDriftStatus.RECONSTRUCTED and self.correction_applied))

    @property
    def requires_review(self) -> bool:
        return not self.can_predict

    def to_dict(self) -> dict[str, object]:
        return {**super().to_dict(), "anomaly_detected": self.anomaly_detected,
                "requires_review": self.requires_review,
                "recommended_action": "use_estimated_position" if self.correction_applied else
                "verify_position" if self.drift_detected else "review_inputs" if self.requires_review else "monitor"}


@dataclass(frozen=True)
class LocationDriftMitigation(BaseMitigation):
    """Compare displacement with SOG/COG motion over a complete received session.

    A detected drift remains flagged through this session, even once its offset
    stops growing. Start a new session only after a genuinely verified position.
    Correction requires a separately verified position and caller-confirmed
    trustworthy speed/course over the projection interval. Constant offsets and
    coordinated corruption may be unobservable to the detector.
    """

    gate: GateConfig
    config: LocationDriftMitigationConfig = LocationDriftMitigationConfig()
    name: ClassVar[str] = "LocationDriftMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate), "scope": "location_drift",
                "action": "bounded_reconstruction_from_verified_anchor_or_review",
                "history": "complete_received_session"}

    def _navigation(self, row: pd.Series) -> np.ndarray | None:
        speed, course = row.sog, row.cog
        if not np.isfinite(speed) or not 0 <= speed <= self.config.maximum_speed_knots:
            return None
        if speed <= self.config.stationary_speed_knots:
            return np.zeros(2)
        if not np.isfinite(course) or not 0 <= course < 360:
            return None
        radians = np.deg2rad(course)
        return speed * KNOTS_TO_METERS_PER_SECOND * np.array([np.sin(radians), np.cos(radians)])

    def _navigation_reason(self, previous, current, before, after) -> str | None:
        minutes = (current.time - previous.time).total_seconds() / 60
        if minutes * 60 > self.config.maximum_gap_seconds:
            return "position_history_gap"
        if before is None or after is None:
            return "unavailable_navigation_reference"
        if (abs(current.sog - previous.sog) / minutes > self.config.maximum_speed_change_knots_per_minute
                or (min(previous.sog, current.sog) > self.config.stationary_speed_knots
                    and angle_difference(current.cog, previous.cog) > self.config.maximum_course_change_degrees)):
            return "maneuvering_navigation_reference"
        return None

    def _project(self, received, navigation, clock, anchor, navigation_trusted):
        """Integrate trusted reported velocity; never integrate coordinate residuals."""
        if anchor is None:
            return None, "verified_position_anchor_required"
        if not navigation_trusted:
            return None, "trusted_navigation_required_for_position_correction"
        try:
            if anchor.received_time > clock or anchor.time > clock:
                return None, "position_anchor_not_yet_available"
            if clock - anchor.time > pd.Timedelta(minutes=self.config.maximum_projection_minutes):
                return None, "position_anchor_expired"
            if anchor.time < received.time.iloc[0] or anchor.time > received.time.iloc[-1]:
                return None, "navigation_history_does_not_cover_anchor"
        except TypeError as error:
            raise ValueError("Position anchor and reports must use compatible timezones.") from error
        start = int(received.time.searchsorted(anchor.time, side="right") - 1)
        offset = np.zeros(2)
        if navigation[start] is None:
            return None, "unavailable_navigation_reference"
        for index in range(start + 1, len(received)):
            previous, current = received.iloc[index - 1], received.iloc[index]
            reason = self._navigation_reason(previous, current, navigation[index - 1], navigation[index])
            if reason is not None:
                return None, reason
            seconds = (current.time - previous.time).total_seconds()
            segment_start = max(anchor.time, previous.time)
            fraction = (segment_start - previous.time).total_seconds() / seconds
            start_velocity = navigation[index - 1] + fraction * (navigation[index] - navigation[index - 1])
            offset += (start_velocity + navigation[index]) * .5 * (current.time - segment_start).total_seconds()
        origin = (self.gate.south_latitude + self.gate.north_latitude) / 2
        longitude = anchor.longitude + offset[0] / (METERS_PER_DEGREE * np.cos(np.deg2rad(origin)))
        latitude = anchor.latitude + offset[1] / METERS_PER_DEGREE
        if not np.isfinite([longitude, latitude]).all() or not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            return None, "projected_position_out_of_bounds"
        return (float(longitude), float(latitude)), None

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None,
              anchor: PositionAnchor | None = None,
              navigation_trusted: bool = False) -> LocationDriftMitigationResult:
        if anchor is not None and not isinstance(anchor, PositionAnchor):
            raise ValueError("anchor must be a PositionAnchor or None.")
        if type(navigation_trusted) is not bool:
            raise ValueError("navigation_trusted must be boolean.")
        received, clock = prepare(reports, decision_time, ("longitude", "latitude", "sog", "cog"))
        if received.empty:
            return LocationDriftMitigationResult(LocationDriftStatus.NO_REPORTS, decision_time=clock)
        config = self.config
        last = received.iloc[-1]
        if anchor is not None and anchor.mmsi != str(last.mmsi):
            raise ValueError("Position anchor must belong to the observed vessel.")
        latest = self._latest_received_time(received, clock, latest_received_time)
        common = dict(decision_time=clock, mmsi=str(last.mmsi), observation_time=last.time,
            latest_received_time=latest, report_age_minutes=(clock - last.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - latest).total_seconds() / 60,
            reported_longitude=finite(last.longitude), reported_latitude=finite(last.latitude),
            longitude=finite(last.longitude), latitude=finite(last.latitude),
            position_source="reported" if (finite(last.longitude) is not None and finite(last.latitude) is not None
                and -180 <= last.longitude <= 180 and -90 <= last.latitude <= 90) else "unavailable")
        if received.time.duplicated().any():
            return LocationDriftMitigationResult(LocationDriftStatus.REVIEW, **common, reasons=("conflicting_same_time_reports",))
        coordinates = local_positions(received, self.gate)
        positions_valid = (np.isfinite(received.longitude) & np.isfinite(received.latitude)
                           & received.longitude.between(-180, 180) & received.latitude.between(-90, 90)).to_numpy()
        navigation = [self._navigation(row) for _, row in received.iterrows()]
        ewma, accumulated = np.zeros(2), np.zeros(2)
        count, valid_segments = 0, 0
        streak_start, detected_at = None, None
        latched = False
        last_reason = "insufficient_navigation_history"
        latest_delivery = received.iloc[0].get("delivered_time", received.time.iloc[0])
        duration = 0.
        for index in range(1, len(received)):
            previous, current = received.iloc[index - 1], received.iloc[index]
            latest_delivery = max(latest_delivery, current.get("delivered_time", current.time))
            seconds = (current.time - previous.time).total_seconds()
            minutes = seconds / 60
            reason = None
            if not positions_valid[index - 1:index + 1].all():
                reason = "invalid_position"
            else:
                reason = self._navigation_reason(previous, current, navigation[index - 1], navigation[index])
                if (reason is None and np.linalg.norm(coordinates[index] - coordinates[index - 1]) / seconds
                        > config.maximum_speed_knots * KNOTS_TO_METERS_PER_SECOND):
                    reason = "implausible_position_motion"
            if reason is not None:
                ewma, accumulated = np.zeros(2), np.zeros(2)
                count, valid_segments, streak_start, duration = 0, 0, None, 0.
                last_reason = reason
                continue
            expected = (navigation[index - 1] + navigation[index]) * .5 * seconds
            residual = coordinates[index] - coordinates[index - 1] - expected
            rate = residual / minutes
            ewma += ewma_fraction(minutes, config.ewma_time_constant_minutes) * (rate - ewma)
            valid_segments += 1
            last_reason = None
            magnitude = np.linalg.norm(rate)
            if magnitude <= config.minimum_disagreement_meters_per_minute:
                count, accumulated, streak_start, duration = 0, np.zeros(2), None, 0.
                continue
            aligned = count and np.dot(rate, accumulated) >= (
                magnitude * np.linalg.norm(accumulated) * np.cos(np.deg2rad(config.maximum_direction_change_degrees)))
            if aligned:
                count += 1
                accumulated += residual
            else:
                count, accumulated, streak_start = 1, residual.copy(), previous.time
            duration = (current.time - streak_start).total_seconds() / 60
            detected = (count >= config.minimum_persistent_reports and duration >= config.minimum_persistence_minutes
                        and np.linalg.norm(ewma) > config.drift_threshold_meters_per_minute
                        and np.linalg.norm(accumulated) > config.minimum_accumulated_disagreement_meters)
            if detected and not latched:
                latched, detected_at = True, latest_delivery
        stale = latest > last.time or common["report_age_minutes"] > config.maximum_report_age_minutes
        reasons = ["persistent_position_navigation_disagreement"] if latched else []
        if stale:
            last_reason = "stale_or_unusable_navigation_history"
        if last_reason is not None:
            reasons.append(last_reason)
        status = (LocationDriftStatus.REVIEW if last_reason is not None else LocationDriftStatus.DRIFT if latched
                  else LocationDriftStatus.NORMAL if valid_segments >= config.minimum_persistent_reports
                  else LocationDriftStatus.WARMING_UP)
        if len(received) == 1 and not stale:
            status = LocationDriftStatus.WARMING_UP
        correction_applied = False
        if latched and last_reason is None:
            position, correction_reason = self._project(received, navigation, clock, anchor, navigation_trusted)
            if position is not None:
                common.update(longitude=position[0], latitude=position[1], position_source="estimated",
                    anchor_time=anchor.time, anchor_source=anchor.source,
                    projection_minutes=float((clock - anchor.time) / pd.Timedelta(minutes=1)))
                correction_applied, status = True, LocationDriftStatus.RECONSTRUCTED
            else:
                reasons.append(correction_reason)
        return LocationDriftMitigationResult(status, **common, drift_detected=latched,
            ewma_disagreement_meters_per_minute=float(np.linalg.norm(ewma)) if valid_segments else None,
            accumulated_disagreement_meters=float(np.linalg.norm(accumulated)),
            persistent_report_count=count, persistent_minutes=duration, anomaly_since=detected_at,
            reference_supported=last_reason is None and valid_segments >= config.minimum_persistent_reports,
            correction_applied=correction_applied,
            reasons=tuple(reasons))

    def reconstruct_reports(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
                            anchor: PositionAnchor | None = None, navigation_trusted: bool = False
                            ) -> tuple[pd.DataFrame, LocationDriftMitigationResult]:
        """Return derived coordinates; later evidence cannot backfill earlier repairs."""
        received, _ = self._prepare_reports(reports, decision_time)
        result = self.apply(received, decision_time, anchor=anchor, navigation_trusted=navigation_trusted)
        derived = received.copy(deep=True).reset_index(drop=True)
        for column in ("longitude", "latitude"):
            derived[column] = self._numeric_field(derived, column)
        delivered = received.get("delivered_time", received.time)
        for index, (_, row) in enumerate(received.iterrows()):
            at = row.get("delivered_time", row.time)
            history = received.loc[received.time.le(row.time) & delivered.le(at)]
            reading = self.apply(history, at, anchor=anchor, navigation_trusted=navigation_trusted)
            if reading.correction_applied:
                derived.at[index, "longitude"] = reading.longitude
                derived.at[index, "latitude"] = reading.latitude
        return derived, result

"""Check noisy navigation readings against received positions, never attack truth."""

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND, history_velocity, local_positions
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult

Source = Literal["reported", "estimated", "unavailable"]


class SensorNoiseStatus(str, Enum):
    NO_REPORTS = "no_reports"
    WARMING_UP = "warming_up"
    REVIEW = "requires_review"
    NORMAL = "normal"
    RECONSTRUCTED = "reconstructed"


@dataclass(frozen=True)
class SensorNoiseConfig:
    """Initial research settings; tune on development data before claiming reliability."""

    window_minutes: float = 5.
    minimum_reports: int = 3
    minimum_span_seconds: float = 60.
    maximum_gap_seconds: float = 180.
    maximum_report_age_minutes: float = 5.
    maximum_speed_knots: float = 60.
    maximum_fit_residual_meters: float = 50.
    maximum_segment_speed_difference_knots: float = 2.
    maximum_track_turn_degrees: float = 30.
    speed_difference_knots: float = 2.
    course_difference_degrees: float = 15.
    minimum_course_speed_knots: float = 1.

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "minimum_reports":
                if type(value) is not int or value < 3:
                    raise ValueError("minimum_reports must be an integer of at least three.")
            elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if self.minimum_span_seconds > self.window_minutes * 60:
            raise ValueError("The history window must cover minimum_span_seconds.")
        if max(self.maximum_track_turn_degrees, self.course_difference_degrees) > 180:
            raise ValueError("Angular thresholds cannot exceed 180 degrees.")


@dataclass(frozen=True)
class SensorNoiseResult(MitigationResult):
    status: SensorNoiseStatus
    speed_knots: float | None = None
    course_degrees: float | None = None
    speed_source: Source = "unavailable"
    course_source: Source = "unavailable"
    estimated_speed_knots: float | None = None
    estimated_course_degrees: float | None = None
    speed_difference_knots: float | None = None
    course_difference_degrees: float | None = None
    speed_suspect: bool = False
    course_suspect: bool = False
    position_supported: bool = False
    reference_report_count: int = 0
    reference_span_seconds: float | None = None
    fit_residual_meters: float | None = None

    @property
    def anomaly_detected(self) -> bool:
        return self.speed_suspect or self.course_suspect

    @property
    def can_predict(self) -> bool:
        """Input support only; this is not calibrated ETA acceptance."""
        return self.status in (SensorNoiseStatus.NORMAL, SensorNoiseStatus.RECONSTRUCTED)

    @property
    def requires_review(self) -> bool:
        return not self.can_predict

    def to_dict(self) -> dict[str, object]:
        return {**super().to_dict(), "anomaly_detected": self.anomaly_detected,
                "requires_review": self.requires_review}


def _angle_difference(left: float, right: float) -> float:
    return abs((left - right + 180) % 360 - 180)


@dataclass(frozen=True)
class SensorNoiseMitigation(BaseMitigation):
    """A causal, stateless strategy for the SensorDeteriorationAttack path.

    Position consistency is a conditional reference, not independent ground truth.
    No fault classifier can prove random sensor noise from disagreement alone.
    """

    gate: GateConfig
    config: SensorNoiseConfig = SensorNoiseConfig()
    name: ClassVar[str] = "SensorNoiseMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate),
                "scope": "sensor_deterioration_noise"}

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> SensorNoiseResult:
        received, clock = self._prepare_reports(reports, decision_time)
        for name in ("longitude", "latitude", "sog", "cog"):
            received[name] = self._numeric_field(received, name)
        if received.empty:
            return SensorNoiseResult(SensorNoiseStatus.NO_REPORTS, decision_time=clock)
        latest = self._latest_received_time(received, clock, latest_received_time)
        # Ignore unused/audit columns. Exact copies never add independent evidence.
        fields = ["mmsi", "time", "longitude", "latitude", "sog", "cog"]
        if "delivered_time" in received:
            received = received.sort_values(["time", "delivered_time"], kind="stable")
        received = received.drop_duplicates(fields, keep="first")
        observation = received.time.max()
        recent = received.loc[received.time >= observation - pd.Timedelta(minutes=self.config.window_minutes)]
        last = recent.iloc[-1]
        sog, cog = float(last.sog), float(last.cog)
        # Missing/sentinel readings are outside this noise-only repair contract.
        speed_present = np.isfinite(sog) and sog >= 0 and sog != 102.3
        course_present = np.isfinite(cog) and 0 <= cog < 360
        common = dict(decision_time=clock, mmsi=str(last.mmsi), observation_time=observation,
                      latest_received_time=latest, report_age_minutes=(clock - observation).total_seconds() / 60,
                      latest_received_age_minutes=(clock - latest).total_seconds() / 60,
                      speed_knots=sog if speed_present else None,
                      course_degrees=cog if course_present else None,
                      speed_source="reported" if speed_present else "unavailable",
                      course_source="reported" if course_present else "unavailable",
                      reference_report_count=recent.time.nunique())
        if latest > observation:
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("newer_unusable_report",))
        if common["report_age_minutes"] > self.config.maximum_report_age_minutes:
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("stale_position_history",))
        if recent.time.duplicated().any():
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("conflicting_same_time_reports",))
        if len(recent) < self.config.minimum_reports:
            return SensorNoiseResult(SensorNoiseStatus.WARMING_UP, **common, reasons=("insufficient_position_history",))
        span = (recent.time.iloc[-1] - recent.time.iloc[0]).total_seconds()
        common["reference_span_seconds"] = span
        if span < self.config.minimum_span_seconds:
            return SensorNoiseResult(SensorNoiseStatus.WARMING_UP, **common, reasons=("short_position_history",))
        positions_valid = (np.isfinite(recent.longitude) & np.isfinite(recent.latitude)
                           & recent.longitude.between(-180, 180) & recent.latitude.between(-90, 90))
        if not positions_valid.all():
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("invalid_position",))
        gaps = recent.time.diff().dt.total_seconds().dropna().to_numpy()
        if np.max(gaps) > self.config.maximum_gap_seconds:
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("position_history_gap",))
        segments = np.diff(local_positions(recent, self.gate), axis=0) / gaps[:, None]
        segment_speeds = np.linalg.norm(segments, axis=1) / KNOTS_TO_METERS_PER_SECOND
        if np.max(segment_speeds) > self.config.maximum_speed_knots:
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("implausible_position_motion",))
        east, north, residual = history_velocity(recent, self.gate)
        speed = float(np.hypot(east, north) / KNOTS_TO_METERS_PER_SECOND)
        common["fit_residual_meters"] = residual
        if not np.isfinite([east, north, residual]).all() or residual > self.config.maximum_fit_residual_meters:
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("inconsistent_position_track",))
        moving = speed >= self.config.minimum_course_speed_knots
        course = float(np.rad2deg(np.arctan2(east, north)) % 360) if moving else None
        turns = [
            _angle_difference(float(np.rad2deg(np.arctan2(vector[0], vector[1])) % 360), course)
            for vector, value in zip(segments, segment_speeds)
            if course is not None and value >= self.config.minimum_course_speed_knots
        ]
        if (np.max(np.abs(segment_speeds - speed)) > self.config.maximum_segment_speed_difference_knots
                or (turns and max(turns) > self.config.maximum_track_turn_degrees)):
            return SensorNoiseResult(SensorNoiseStatus.REVIEW, **common, reasons=("maneuvering_position_track",))
        speed_difference = abs(sog - speed) if speed_present else None
        course_difference = _angle_difference(cog, course) if course_present and course is not None else None
        speed_suspect = speed_difference is not None and speed_difference > self.config.speed_difference_knots
        course_suspect = course_difference is not None and course_difference > self.config.course_difference_degrees
        if speed_suspect:
            common.update(speed_knots=speed, speed_source="estimated")
        if course_suspect:
            common.update(course_degrees=course, course_source="estimated")
        reasons = tuple(reason for enabled, reason in (
            (speed_suspect, "speed_position_disagreement"),
            (course_suspect, "course_position_disagreement"),
            (not speed_present, "unavailable_speed_not_noise_repaired"),
            (moving and not course_present, "unavailable_course_not_noise_repaired"),
        ) if enabled)
        status = (SensorNoiseStatus.REVIEW if not speed_present or (moving and not course_present)
                  else SensorNoiseStatus.RECONSTRUCTED if speed_suspect or course_suspect else SensorNoiseStatus.NORMAL)
        return SensorNoiseResult(status, **common, estimated_speed_knots=speed,
            estimated_course_degrees=course, speed_difference_knots=speed_difference,
            course_difference_degrees=course_difference, speed_suspect=bool(speed_suspect),
            course_suspect=bool(course_suspect), position_supported=True, reasons=reasons)

    def reconstruct_reports(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str
                            ) -> tuple[pd.DataFrame, SensorNoiseResult]:
        """Return a derived received-feed copy and current diagnostics.

        Each reconstruction uses only reports available when that reading was
        delivered and measured no later than that reading. No backfilled future fixes.
        """
        received, _ = self._prepare_reports(reports, decision_time)
        result = self.apply(received, decision_time)
        derived = received.copy(deep=True).reset_index(drop=True)
        for field in ("sog", "cog"):
            derived[field] = self._numeric_field(derived, field)
        delivered = received.get("delivered_time", received.time)
        for index, (_, report) in enumerate(received.iterrows()):
            at = report.get("delivered_time", report.time)
            history = received.loc[received.time.le(report.time) & delivered.le(at)]
            reading = self.apply(history, at)
            if not reading.can_predict:
                continue
            if reading.speed_source == "estimated":
                derived.at[index, "sog"] = reading.speed_knots
            if reading.course_source == "estimated":
                derived.at[index, "cog"] = reading.course_degrees
        return derived, result

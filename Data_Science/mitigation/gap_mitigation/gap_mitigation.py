"""Detect silence on an observed active approach, independently for each vessel."""

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import ClassVar

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult


class GapStatus(str, Enum):
    INACTIVE = "inactive"
    WARMING_UP = "warming_up"
    NORMAL = "normal"
    REPORTING_GAP = "reporting_gap"
    ARRIVED = "arrived"
    LEFT_AREA = "left_area"
    STREAM_ENDED = "stream_ended"


@dataclass(frozen=True)
class GapMitigationConfig:
    """Configurable detection policy; defaults are provisional, not calibrated."""

    minimum_silence_minutes: float = 5.0
    cadence_multiplier: float = 3.0
    minimum_reports: int = 3
    cadence_window_reports: int = 10

    def __post_init__(self) -> None:
        for name in ("minimum_silence_minutes", "cadence_multiplier"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        for name in ("minimum_reports", "cadence_window_reports"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 3:
                raise ValueError(f"{name} must be an integer of at least three.")
        if self.cadence_window_reports < self.minimum_reports:
            raise ValueError("cadence_window_reports must cover minimum_reports.")


@dataclass(frozen=True)
class GapMitigationResult(MitigationResult):
    status: GapStatus
    silence_minutes: float | None = None
    timeout_minutes: float | None = None
    recent_cadence_minutes: float | None = None
    active_report_count: int = 0
    anomaly_since: pd.Timestamp | None = None

    @property
    def anomaly_detected(self) -> bool:
        return self.status == GapStatus.REPORTING_GAP

    @property
    def can_predict(self) -> bool:
        """Reliability recommendation only; this detector never changes forecasts."""
        return self.status == GapStatus.NORMAL

    def to_dict(self) -> dict[str, object]:
        return {**super().to_dict(), "anomaly_detected": self.anomaly_detected}


@dataclass(frozen=True)
class GapMitigation(BaseMitigation):
    """Replay received history at a clock; no labels, attack logs or future fixes.

    Call periodically even with unchanged reports. Supply the active session's
    history and explicitly end monitoring at stream end. The last supplied row
    alone cannot distinguish an outage from the end of a recording.
    """

    gate: GateConfig
    config: GapMitigationConfig = GapMitigationConfig()
    name: ClassVar[str] = "GapMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return {"config": asdict(self.config), "gate": asdict(self.gate)}

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None,
              stream_ended: bool = False) -> GapMitigationResult:
        received, clock = self._prepare_reports(reports, decision_time)
        self._numeric_field(received, "latitude")
        self._numeric_field(received, "longitude")
        if type(stream_ended) is not bool:
            raise ValueError("stream_ended must be boolean.")
        identity = str(received.mmsi.iloc[0]) if len(received) else None
        if stream_ended:
            return GapMitigationResult(GapStatus.STREAM_ENDED, decision_time=clock, mmsi=identity)
        if received.empty:
            return GapMitigationResult(GapStatus.INACTIVE, decision_time=clock)
        if latest_received_time is not None:
            self._latest_received_time(received, clock, latest_received_time)
        # Repeated delivery of the same measurement cannot restart its clock.
        if "delivered_time" in received:
            received = received.sort_values(["time", "delivered_time"], kind="stable")
        received = received.drop_duplicates("time", keep="first")
        usable = received.loc[np.isfinite(received.latitude) & np.isfinite(received.longitude)
                              & received.latitude.between(-90, 90) & received.longitude.between(-180, 180)]
        active: list[pd.Series] = []
        status = GapStatus.INACTIVE
        gate = self.gate
        for _, report in usable.iterrows():
            arrived = (report.longitude <= gate.longitude
                       and gate.south_latitude <= report.latitude <= gate.north_latitude)
            inside = (gate.longitude < report.longitude <= gate.approach_east_longitude
                      and gate.approach_south_latitude <= report.latitude <= gate.approach_north_latitude)
            if active and arrived:
                active = []
                status = GapStatus.ARRIVED
            elif inside:
                active.append(report)
                status = GapStatus.WARMING_UP
            elif active:
                active = []
                status = GapStatus.LEFT_AREA
        if not active:
            return GapMitigationResult(status, decision_time=clock, mmsi=identity)
        last = active[-1]
        received_at = last.get("delivered_time", last.time)
        silence = (clock - received_at).total_seconds() / 60
        times = pd.Series([row.time for row in active[-self.config.cadence_window_reports:]])
        cadence = float(times.diff().dt.total_seconds().dropna().median() / 60) if len(times) > 1 else None
        timeout = max(self.config.minimum_silence_minutes,
                      self.config.cadence_multiplier * cadence) if cadence is not None else None
        if len(active) >= self.config.minimum_reports:
            status = GapStatus.REPORTING_GAP if silence > timeout else GapStatus.NORMAL
        return GapMitigationResult(
            status, decision_time=clock, mmsi=identity, observation_time=last.time,
            latest_received_time=last.time, report_age_minutes=(clock - last.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - last.time).total_seconds() / 60,
            silence_minutes=silence, timeout_minutes=timeout, recent_cadence_minutes=cadence,
            active_report_count=len(active),
            anomaly_since=received_at + pd.Timedelta(minutes=timeout) if status == GapStatus.REPORTING_GAP else None,
            reasons=("unexpected_reporting_silence",) if status == GapStatus.REPORTING_GAP else (),
        )

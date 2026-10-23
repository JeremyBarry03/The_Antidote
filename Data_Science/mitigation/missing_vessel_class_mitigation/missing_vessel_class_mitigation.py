"""Conservative class carry-forward; no motion inference or report rewriting."""

from dataclasses import asdict, dataclass, replace
from enum import Enum
import math
from typing import ClassVar, Literal

import numpy as np
import pandas as pd

from ..base_mitigation import BaseMitigation, MitigationParameters, MitigationResult


class VesselClassStatus(str, Enum):
    NO_REPORTS = "no_reports"
    OBSERVED = "observed"
    RECOVERED = "recovered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MissingVesselClassMitigationConfig:
    minimum_reports: int = 3
    history_minutes: float = 60.0

    def __post_init__(self) -> None:
        if type(self.minimum_reports) is not int or self.minimum_reports < 1:
            raise ValueError("minimum_reports must be a positive integer.")
        if (isinstance(self.history_minutes, bool) or not isinstance(self.history_minutes, (int, float))
                or not math.isfinite(self.history_minutes) or self.history_minutes <= 0):
            raise ValueError("history_minutes must be finite and positive.")


@dataclass(frozen=True)
class MissingVesselClassResult(MitigationResult):
    status: VesselClassStatus
    original_type: float | None = None
    recovered_class: Literal["cargo", "tanker"] | None = None
    evidence_count: int = 0
    evidence_time: pd.Timestamp | None = None
    classification_age_minutes: float | None = None

    @property
    def can_predict(self) -> bool:
        """Class supported; unknown class still follows C's existing feature path."""
        return self.status in (VesselClassStatus.OBSERVED, VesselClassStatus.RECOVERED)


@dataclass(frozen=True)
class MissingVesselClassMitigation(BaseMitigation):
    config: MissingVesselClassMitigationConfig = MissingVesselClassMitigationConfig()
    name: ClassVar[str] = "MissingVesselClassMitigation"

    @property
    def parameters(self) -> MitigationParameters:
        return asdict(self.config)

    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> MissingVesselClassResult:
        received, clock = self._prepare_reports(reports, decision_time)
        values = self._numeric_field(received, "vessel_type")
        if received.empty:
            return MissingVesselClassResult(VesselClassStatus.NO_REPORTS, decision_time=clock)
        latest_time = self._latest_received_time(received, clock, latest_received_time)
        last = received.iloc[-1]
        raw = float(last.vessel_type) if pd.notna(last.vessel_type) else float("nan")
        finite = np.isfinite(values)
        known = np.zeros(len(values), dtype=bool)
        known[finite] = (values[finite] > 0) & (values[finite] % 1 == 0)
        broad = np.where((values >= 70) & (values <= 79), "cargo",
                         np.where((values >= 80) & (values <= 89), "tanker", "other"))
        # Contradictory class messages at the latest timestamp must not depend on row order.
        current_classes = set(broad[known & received.time.eq(last.time).to_numpy()])
        base = MissingVesselClassResult(VesselClassStatus.UNKNOWN, decision_time=clock, mmsi=str(last.mmsi),
            observation_time=last.time, latest_received_time=latest_time,
            report_age_minutes=(clock - last.time).total_seconds() / 60,
            latest_received_age_minutes=(clock - latest_time).total_seconds() / 60,
            original_type=raw if np.isfinite(raw) else None)
        if len(current_classes) > 1:
            return replace(base, reasons=("conflicting_current_class",))
        if known[-1]:
            return replace(base, status=VesselClassStatus.OBSERVED) if broad[-1] != "other" else replace(
                base, reasons=("known_unsupported_class",))
        recent = known & received.time.lt(last.time).to_numpy() & received.time.ge(
            clock - pd.Timedelta(minutes=self.config.history_minutes)).to_numpy()
        evidence = received.loc[recent]
        classes = set(broad[recent])
        base = replace(base, evidence_count=evidence.time.nunique(),
            evidence_time=evidence.time.max() if len(evidence) else None,
            classification_age_minutes=(clock - evidence.time.max()).total_seconds() / 60 if len(evidence) else None)
        if len(classes) > 1 or "other" in classes:
            return replace(base, reasons=("conflicting_class_history",))
        if base.evidence_count < self.config.minimum_reports:
            return replace(base, reasons=("insufficient_recent_class_history",))
        return replace(base, status=VesselClassStatus.RECOVERED, recovered_class=next(iter(classes)))

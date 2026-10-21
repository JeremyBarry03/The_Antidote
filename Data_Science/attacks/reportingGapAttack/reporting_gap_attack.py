"""Drop reports measured inside an explicit outage window; preserve source truth."""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from Optimized_Model.replay import Condition, ReportStream
from attacks.base_attack import AttackParameters, BaseAttack


@dataclass(frozen=True)
class ReportingGapConfig:
    """Window is [start_time, end_time); target all MMSIs when omitted."""

    start_time: pd.Timestamp
    end_time: pd.Timestamp
    target_mmsi: str | None = None

    def __post_init__(self) -> None:
        for field in ("start_time", "end_time"):
            value = getattr(self, field)
            if not isinstance(value, (str, pd.Timestamp)):
                raise ValueError(f"{field} must be an ISO timestamp string or pandas Timestamp.")
            try:
                timestamp = pd.Timestamp(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Invalid {field}: {value!r}.") from error
            if pd.isna(timestamp):
                raise ValueError(f"{field} cannot be missing.")
            object.__setattr__(self, field, timestamp)
        try:
            valid_order = self.end_time > self.start_time
        except TypeError as error:
            raise ValueError("Gap start and end must use compatible timezones.") from error
        if not valid_order:
            raise ValueError("end_time must be later than start_time.")
        if self.target_mmsi is not None:
            if (not isinstance(self.target_mmsi, str) or not self.target_mmsi.isascii()
                    or not self.target_mmsi.isdigit() or len(self.target_mmsi) != 9):
                raise ValueError("target_mmsi must be a nine-digit string or None.")


@dataclass(frozen=True)
class ReportingGapAttack(BaseAttack):
    """Simulate missing transmissions, not changed motion or a delayed queue."""

    config: ReportingGapConfig
    name: ClassVar[str] = "ReportingGapAttack"
    condition: ClassVar[Condition] = Condition.STALE

    @property
    def parameters(self) -> AttackParameters:
        return {"start_time": self.config.start_time.isoformat(),
                "end_time": self.config.end_time.isoformat(),
                "target_mmsi": self.config.target_mmsi}

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        prepared = self._prepare_reports(reports)
        try:
            affected = reports["time"].ge(self.config.start_time) & reports["time"].lt(self.config.end_time)
        except TypeError as error:
            raise ValueError("Gap window and report times must use compatible timezones.") from error
        if self.config.target_mmsi is not None:
            affected &= reports["mmsi"].astype(str).eq(self.config.target_mmsi)
        audit = prepared[["record_id", "mmsi", "time", "delivered_time"]].copy()
        audit["fault_applied"] = affected.to_numpy()
        audit["action"] = affected.map({True: "dropped", False: "retained"}).to_numpy()
        audit["attack"] = self.name
        # The reports exclude dropped rows entirely; their original values stay
        # exclusively in the reference and this audience/evaluation audit.
        retained = prepared.loc[~affected].sort_values("time", kind="stable").copy()
        return ReportStream(retained, audit)

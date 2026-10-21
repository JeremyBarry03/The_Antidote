"""Small strategy contract shared by report-level fault injections."""

from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype

from Optimized_Model.replay import Condition, ReportStream

AttackParameters = dict[str, str | int | float | bool | None]


class BaseAttack(ABC):
    """Return copied reports and separate evaluator-only modification truth.

    Implementations preserve measurement times, never mutate the input, and keep
    attack labels out of reports. Audit logs include `record_id`, `time`,
    `fault_applied`, and `action`; inspection excludes records not yet measured
    at the replay clock. Actions identify actual changes, such as `dropped` or
    `speed_removed`, rather than attributing every change to a reporting outage.
    """

    name: ClassVar[str]
    condition: ClassVar[Condition]

    @property
    @abstractmethod
    def parameters(self) -> AttackParameters:
        """Return JSON-safe settings needed to reproduce this injection."""

    @abstractmethod
    def apply(self, reports: pd.DataFrame) -> ReportStream:
        """Transform reports without loading models, performing I/O, or scoring."""

    @staticmethod
    def _prepare_reports(reports: pd.DataFrame) -> pd.DataFrame:
        """Validate common report fields and copy nominal delivery metadata."""
        missing = {"mmsi", "time"} - set(reports.columns)
        if missing:
            raise ValueError(f"Missing report columns: {sorted(missing)}.")
        if reports.columns.duplicated().any():
            raise ValueError("Report column names must be unique.")
        if not is_datetime64_any_dtype(reports["time"]) or reports["time"].isna().any():
            raise ValueError("Report time must contain parsed, nonmissing datetimes.")
        if reports["mmsi"].isna().any():
            raise ValueError("Report MMSI cannot be missing.")
        prepared = reports.copy(deep=True)
        if "delivered_time" not in prepared:
            prepared["delivered_time"] = prepared["time"]
        delivered = prepared["delivered_time"]
        if not is_datetime64_any_dtype(delivered) or delivered.isna().any():
            raise ValueError("delivered_time must contain parsed, nonmissing datetimes.")
        try:
            arrives_early = delivered.lt(prepared["time"]).any()
        except TypeError as error:
            raise ValueError("Measurement and delivery times must use compatible timezones.") from error
        if arrives_early:
            raise ValueError("Reports cannot be delivered before their measurement time.")
        if "record_id" not in prepared:
            prepared["record_id"] = [f"{row.mmsi}:{row.time.isoformat()}" for row in prepared.itertuples()]
        return prepared

"""Shared causal-input and result contracts for observable-data mitigations."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from enum import Enum
from typing import ClassVar

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_complex_dtype, is_datetime64_any_dtype, is_numeric_dtype

MitigationParameters = dict[str,object]


@dataclass(frozen=True,kw_only=True)
class MitigationResult(ABC):
    """Real observation provenance shared by every mitigation's derived result."""

    decision_time: pd.Timestamp
    mmsi: str | None = None
    observation_time: pd.Timestamp | None = None
    latest_received_time: pd.Timestamp | None = None
    report_age_minutes: float | None = None
    latest_received_age_minutes: float | None = None
    reasons: tuple[str,...] = ()

    @property
    @abstractmethod
    def can_predict(self) -> bool:
        """Whether this result supports an ETA at the current decision time."""

    def to_dict(self) -> dict[str,object]:
        result = asdict(self)
        for key,value in result.items():
            if isinstance(value,pd.Timestamp):
                result[key] = value.isoformat()
            elif isinstance(value,Enum):
                result[key] = value.value
        result["can_predict"] = self.can_predict
        return result


class BaseMitigation(ABC):
    """Return a derived state without mutating reports or accessing attack truth.

    Apply per vessel and decision clock. Model loading, scoring and file writing
    belong to adapters/experiments. Field-specific validity and reconstruction
    belong to subclasses; metadata-only mitigations need no coordinate columns.
    """

    name: ClassVar[str]

    @property
    @abstractmethod
    def parameters(self) -> MitigationParameters:
        """JSON-safe settings required to reproduce this mitigation."""

    @abstractmethod
    def apply(self, reports: pd.DataFrame, decision_time: pd.Timestamp | str, *,
              latest_received_time: pd.Timestamp | None = None) -> MitigationResult:
        """Use only already measured and delivered observations."""

    @staticmethod
    def _prepare_reports(reports: pd.DataFrame, decision_time: pd.Timestamp | str) -> tuple[pd.DataFrame,pd.Timestamp]:
        """Validate common fields, select causal reports, and return a private copy."""
        try:
            clock = pd.Timestamp(decision_time)
        except (TypeError,ValueError) as error:
            raise ValueError("decision_time must be a valid timestamp.") from error
        if pd.isna(clock):
            raise ValueError("decision_time cannot be missing.")
        if reports.columns.duplicated().any() or not {"mmsi","time"}.issubset(reports):
            raise ValueError("Reports require unique mmsi/time columns.")
        if not is_datetime64_any_dtype(reports.time) or reports.time.isna().any():
            raise ValueError("Report time must contain parsed nonmissing datetimes.")
        if reports.mmsi.isna().any():
            raise ValueError("Report MMSI cannot be missing.")
        delivered = reports.get("delivered_time",reports.time)
        if not is_datetime64_any_dtype(delivered) or delivered.isna().any():
            raise ValueError("Delivery times must contain parsed nonmissing datetimes.")
        try:
            if delivered.lt(reports.time).any():
                raise ValueError("Reports cannot be delivered before measurement.")
            received = reports.loc[reports.time.le(clock) & delivered.le(clock)].sort_values("time",kind="stable").copy(deep=True)
        except TypeError as error:
            raise ValueError("Report, delivery and decision times must use compatible timezones.") from error
        if received.mmsi.astype(str).nunique() > 1:
            raise ValueError("Apply a mitigation to one vessel at a time.")
        return received,clock

    @staticmethod
    def _numeric_field(reports: pd.DataFrame, field: str) -> np.ndarray:
        if field not in reports:
            raise ValueError(f"Missing numeric measurement column: {field}.")
        values = reports[field]
        if not is_numeric_dtype(values) or is_bool_dtype(values) or is_complex_dtype(values):
            raise ValueError(f"{field} must contain parsed real numeric measurements.")
        return values.to_numpy(dtype=float,na_value=np.nan,copy=True)

    @staticmethod
    def _latest_received_time(reports: pd.DataFrame, clock: pd.Timestamp,
                              value: pd.Timestamp | None) -> pd.Timestamp:
        latest = reports.time.max() if value is None else pd.Timestamp(value)
        try:
            if pd.isna(latest) or latest > clock or latest < reports.time.max():
                raise ValueError("latest_received_time must cover trusted reports and cannot be in the future.")
        except TypeError as error:
            raise ValueError("latest_received_time must use a compatible timezone.") from error
        return latest

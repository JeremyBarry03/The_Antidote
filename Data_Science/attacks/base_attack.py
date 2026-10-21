"""Small strategy contract shared by report-level fault injections."""

from abc import ABC, abstractmethod
from typing import ClassVar

import pandas as pd

from Optimized_Model.replay import Condition, ReportStream


class BaseAttack(ABC):
    """Return copied reports and separate evaluator-only modification truth.

    Implementations preserve measurement times, never mutate the input, and keep
    attack labels out of reports. Logs include `time` so inspection can exclude
    records not yet measured at the replay clock.
    """

    name: ClassVar[str]
    condition: ClassVar[Condition]

    @property
    @abstractmethod
    def parameters(self) -> dict[str, str | None]:
        """Return JSON-safe settings needed to reproduce this injection."""

    @abstractmethod
    def apply(self, reports: pd.DataFrame) -> ReportStream:
        """Transform reports without loading models, performing I/O, or scoring."""

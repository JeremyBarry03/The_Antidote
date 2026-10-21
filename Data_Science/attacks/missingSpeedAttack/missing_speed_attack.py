"""Mask selected measured speeds while retaining every report and its timing."""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from Optimized_Model.replay import Condition, ReportStream
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.missing_field import MissingFieldConfig, mask_field


@dataclass(frozen=True)
class MissingSpeedConfig(MissingFieldConfig):
    """Prevalence selects original reports; naturally missing speeds stay missing."""


@dataclass(frozen=True)
class MissingSpeedAttack(BaseAttack):
    """Remove speed evidence; never substitute zero or remove the vessel position."""

    config: MissingSpeedConfig
    name: ClassVar[str] = "MissingSpeedAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return self.config.as_parameters()

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        return mask_field(self._prepare_reports(reports), self.config, 'sog', self.name)

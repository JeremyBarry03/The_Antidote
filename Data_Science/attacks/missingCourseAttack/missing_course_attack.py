"""Remove course evidence without substituting north or altering vessel motion."""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from Optimized_Model.replay import Condition, ReportStream
from attacks.base_attack import AttackParameters, BaseAttack
from attacks.missing_field import MissingFieldConfig, mask_field


@dataclass(frozen=True)
class MissingCourseConfig(MissingFieldConfig):
    """Prevalence selects original reports; naturally missing courses stay missing."""


@dataclass(frozen=True)
class MissingCourseAttack(BaseAttack):
    """Mask course-over-ground values; retain reports, positions, speeds and times."""

    config: MissingCourseConfig
    name: ClassVar[str] = 'MissingCourseAttack'
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return self.config.as_parameters()

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        return mask_field(self._prepare_reports(reports), self.config, 'cog', self.name)

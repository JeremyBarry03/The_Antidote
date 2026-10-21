"""Remove vessel type without editing motion, identity, timing or outcomes."""

from dataclasses import dataclass
from typing import ClassVar, Literal

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

from Optimized_Model.replay import Condition, ReportStream
from ..base_attack import AttackParameters, BaseAttack
from ..missing_field import MissingFieldConfig, mask_field


@dataclass(frozen=True)
class MissingVesselClassConfig(MissingFieldConfig):
    """Mask individual reports or all records of deterministically chosen vessels."""

    selection_unit: Literal["report", "vessel"] = "report"

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.selection_unit not in ("report", "vessel"):
            raise ValueError("selection_unit must be 'report' or 'vessel'.")

    def as_parameters(self) -> AttackParameters:
        return {**super().as_parameters(), "selection_unit": self.selection_unit}


@dataclass(frozen=True)
class MissingVesselClassAttack(BaseAttack):
    """Mask vessel_type only; keep every report available for ETA inference."""

    config: MissingVesselClassConfig
    name: ClassVar[str] = "MissingVesselClassAttack"
    condition: ClassVar[Condition] = Condition.QUALITY

    @property
    def parameters(self) -> AttackParameters:
        return self.config.as_parameters()

    def apply(self, reports: pd.DataFrame) -> ReportStream:
        return mask_field(self._prepare_reports(reports), self.config, "vessel_type", self.name,
                          selection_unit=self.config.selection_unit)


def classified_cargo_tanker_reports(reports: pd.DataFrame) -> pd.DataFrame:
    """Historical row-filter policy, retained to reproduce the earlier experiment.

    Active vessel-class attacks retain all reports and do not call this helper.
    Source cohort selection still happens before replay injection.
    """
    if "vessel_type" not in reports:
        raise ValueError("Missing vessel_class column: vessel_type.")
    values = reports["vessel_type"]
    if not is_numeric_dtype(values) or is_bool_dtype(values):
        raise ValueError("vessel_type must contain parsed numeric values or missing values.")
    return reports.loc[values.between(70, 89).fillna(False)].copy()

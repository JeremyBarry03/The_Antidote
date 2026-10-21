"""Random navigation-measurement corruption, separate from gradual drift."""

from .sensor_deterioration_attack import SEVERITY_LEVELS, SensorDeteriorationAttack, SensorDeteriorationConfig

__all__ = ["SEVERITY_LEVELS", "SensorDeteriorationAttack", "SensorDeteriorationConfig"]

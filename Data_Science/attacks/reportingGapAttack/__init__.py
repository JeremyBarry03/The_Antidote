"""Temporary loss of vessel reports, without delayed backlog delivery."""

from .reporting_gap_attack import ReportingGapAttack, ReportingGapConfig

__all__ = ["ReportingGapAttack", "ReportingGapConfig"]

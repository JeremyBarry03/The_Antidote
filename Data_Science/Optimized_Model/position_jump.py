"""Position-jump replay presets and audience-only inspection."""

from dataclasses import asdict

import pandas as pd

from attacks import PositionJumpConfig
from .presentation import VISIBLE_REPORT_LIMIT, recent_reports
from .replay import Condition, ReportStream, Scenario

POSITION_JUMP_FRACTIONS = (.1, .2, .25, .5, 1.)


def position_jump_presets(seed: int) -> dict[str, PositionJumpConfig]:
    return {f"position_jump_{fraction:.0%}".replace("%", "pct"):
            PositionJumpConfig(affected_fraction=fraction, seed=seed) for fraction in POSITION_JUMP_FRACTIONS}


def position_jump_options(seed: int) -> list[dict[str, object]]:
    return [{**asdict(Scenario(name, Condition.QUALITY, affected_fraction=config.affected_fraction)),
             "label": f"Position jumps · {config.affected_fraction:.0%} · 2 km", "group": "position_jump",
             "displacement_meters": config.displacement_meters}
            for name, config in position_jump_presets(seed).items()]


def inspect_position_jump(stream: ReportStream, available: pd.DataFrame,
                          history_minutes: float) -> dict[str, object]:
    """Join original positions after prediction, limited to already delivered fixes."""
    recent = recent_reports(available, history_minutes)
    truth = stream.modification_log.drop(columns=["mmsi", "time", "delivered_time",
                                                    "reported_latitude", "reported_longitude"])
    joined = recent.merge(truth, on="record_id", how="left", validate="one_to_one")
    joined["offset_meters"] = joined.applied_displacement_meters
    return {"kind": "position_jump", "audience_only": True,
            "affected_in_window": int(joined.fault_applied.sum()),
            "actual_affected_share": float(joined.fault_applied.mean()) if len(joined) else None,
            "records": joined.tail(VISIBLE_REPORT_LIMIT).to_dict(orient="records"),
            "visible_limit": VISIBLE_REPORT_LIMIT}

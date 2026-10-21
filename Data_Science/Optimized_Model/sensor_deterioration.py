"""Replay presets and audience-only inspection for the navigation-noise attack."""

from dataclasses import asdict

import pandas as pd

from attacks.sensorDeteriorationAttack import SEVERITY_LEVELS, SensorDeteriorationConfig
from .presentation import VISIBLE_REPORT_LIMIT, recent_reports
from .replay import Condition, ReportStream, Scenario


def deterioration_presets(seed: int) -> dict[str, SensorDeteriorationConfig]:
    return {f"sensor_deterioration_{level}": SensorDeteriorationConfig.from_severity(level, seed=seed)
            for level in SEVERITY_LEVELS}


def deterioration_options(seed: int) -> list[dict[str, object]]:
    return [{**asdict(Scenario(name, Condition.QUALITY, affected_fraction=1.)),
             "label": f"Sensor deterioration · {name.removeprefix('sensor_deterioration_').title()}",
             "group": "deterioration", "sog_sigma_knots": config.sog_sigma_knots,
             "cog_sigma_degrees": config.cog_sigma_degrees}
            for name, config in deterioration_presets(seed).items()]


def inspect_deterioration(stream: ReportStream, available: pd.DataFrame,
                          history_minutes: float) -> dict[str, object]:
    """Join truth only for delivered records, after prediction has completed."""
    recent = recent_reports(available, history_minutes)
    truth = stream.modification_log.drop(columns=["mmsi", "time", "delivered_time", "reported_sog", "reported_cog"])
    joined = recent.merge(truth, on="record_id", how="left", validate="one_to_one")
    joined["original_longitude"], joined["original_latitude"] = joined.longitude, joined.latitude
    joined["offset_meters"] = 0.
    return {"kind": "sensor_deterioration", "audience_only": True,
            "affected_in_window": int(joined.fault_applied.sum()),
            "actual_affected_share": float(joined.fault_applied.mean()) if len(joined) else None,
            "records": joined.tail(VISIBLE_REPORT_LIMIT).to_dict(orient="records"),
            "visible_limit": VISIBLE_REPORT_LIMIT}

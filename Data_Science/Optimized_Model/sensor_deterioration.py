"""Replay presets and audience-only inspection for the navigation-noise attack."""

from dataclasses import asdict, replace

import pandas as pd

from attacks.sensorDeteriorationAttack import SEVERITY_LEVELS, SensorDeteriorationConfig
from mitigation.sensor_noise_mitigation import SensorNoiseMitigation, SensorNoiseStatus
from .features import RICH_COLUMNS, OptimizedFeatures
from .presentation import VISIBLE_REPORT_LIMIT, recent_reports
from .replay import Condition, ReportStream, Scenario
from .views import view_row


def mitigated_noise_view(reports: pd.DataFrame, decision: pd.Series, extractor: OptimizedFeatures,
                        mitigation: SensorNoiseMitigation) -> tuple[dict[str, object], dict[str, object]]:
    """Change only C's derived motion inputs; retain A/B and raw quality evidence."""
    row = view_row(reports, decision, extractor)
    received = reports.loc[reports.time.le(decision.decision_time)].sort_values("time", kind="stable")
    if "delivered_time" in received:
        received = received.loc[received.delivered_time.le(decision.decision_time)]
    # Bound repeated prefix fits to the model window plus its causal warmup.
    if len(received):
        cutoff = received.time.max() - pd.Timedelta(
            minutes=extractor.baseline.features.history_minutes + mitigation.config.window_minutes)
        received = received.loc[received.time.ge(cutoff)]
    derived, result = mitigation.reconstruct_reports(received, decision.decision_time)
    changed = 0
    if result.can_predict and row["supported"]:
        corrected, _ = extractor.snapshot(derived, decision.decision_time, guarded=True)
        # A sensor repair must not silently change which position fix anchors the ETA.
        if not corrected.empty and corrected.iloc[0].observation_time == row["observation_time"]:
            for column in RICH_COLUMNS:
                row[column] = corrected.iloc[0][column]
            left, right = received[["sog", "cog"]].reset_index(drop=True), derived[["sog", "cog"]]
            in_model_window = derived.time.ge(derived.time.max() - pd.Timedelta(minutes=extractor.baseline.features.history_minutes))
            changed = int(((left.ne(right) & ~(left.isna() & right.isna())).any(axis=1) & in_model_window).sum())
        else:
            result = replace(result, status=SensorNoiseStatus.REVIEW,
                             reasons=(*result.reasons, "reconstruction_changed_model_anchor"))
    elif result.can_predict:
        result = replace(result, status=SensorNoiseStatus.REVIEW,
                         reasons=(*result.reasons, "unsupported_model_inputs"))
    # Quality columns, support, raw_* features, timestamps, guard counts and reasons
    # above come from the original received feed. Repair never erases its warning.
    metadata = {**result.to_dict(), "applied": changed > 0,
                "reconstructed_report_count": changed, "policy": mitigation.parameters,
                "eta_policy_calibrated": False}
    return row, metadata


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

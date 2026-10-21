"""Audience-only inspection and saved evaluation evidence for the replay page.

Nothing in this module constructs model inputs. Fault truth is joined only after
the shared predictor has run, and only when the audience requests inspection.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from eta_baselines.configuration import GateConfig
from eta_baselines.features import METERS_PER_DEGREE

from .replay import ReportStream, Scenario
from .scenarios import primary_scenarios, volume_scenarios

VISIBLE_REPORT_LIMIT = 150
TIMELINE_CHUNK_ROWS = 50_000
DISPLAY_SYSTEMS = ("A", "B", "C")
REPORT_VALUE_COLUMNS = ("mmsi", "time", "longitude", "latitude", "sog", "cog", "vessel_type")
TIMELINE_COLUMNS = ("approach_id", "decision_id", "decision_time", "system", "scenario", "seed",
                    "available", "predicted_arrival_time", "error_minutes")
PRIMARY_LABELS = ("Normal reports", "Delayed 15 minutes", "Incorrect positions · 25%",
                  "Delay + incorrect positions", "Reserved gradual drift")


def demo_scenarios() -> dict[str, Scenario]:
    return {scenario.name: scenario for scenario in [*primary_scenarios(), *volume_scenarios()]}


def scenario_options() -> list[dict[str, object]]:
    labels = dict(zip((item.name for item in primary_scenarios()), PRIMARY_LABELS))
    choices = []
    for scenario in demo_scenarios().values():
        if scenario.name in labels:
            label, group = labels[scenario.name], "primary"
        elif scenario.name.startswith("fixed_volume_share_"):
            label = f"Incorrect positions · {scenario.affected_fraction:.0%}"
            group = "prevalence"
        else:
            copies = max(scenario.repetition, scenario.total_repetition)
            all_reports = scenario.name.startswith(("all_volume_", "nonidentical_all_volume_"))
            subject = ("Normal reports" if not scenario.affected_fraction else
                       "All reports" if all_reports else "Affected reports")
            detail = " · slightly different copies" if scenario.repetition_jitter_meters else " · exact copies"
            label, group = f"{subject} ×{copies}{detail}", "volume"
        choices.append({**asdict(scenario), "label": label, "group": group})
    return choices


def recent_reports(available: pd.DataFrame, history_minutes: float) -> pd.DataFrame:
    if available.empty:
        return available.copy()
    start = available["time"].max() - pd.Timedelta(minutes=history_minutes)
    return available.loc[available["time"] >= start].copy()


def feed_counts(available: pd.DataFrame, history_minutes: float, bin_seconds: int) -> dict[str, object]:
    recent = recent_reports(available, history_minutes)
    unique = recent.drop_duplicates(list(REPORT_VALUE_COLUMNS))
    bins = unique["time"].dt.floor(f"{bin_seconds}s").nunique() if len(unique) else 0
    return {"received_total": len(available), "received_in_window": len(recent),
            "unique_in_window": len(unique), "exact_duplicates_in_window": len(recent) - len(unique),
            "occupied_bins": bins, "history_minutes": history_minutes, "bin_seconds": bin_seconds}


def inspect_feed(
    stream: ReportStream, available: pd.DataFrame, gate: GateConfig, history_minutes: float,
) -> dict[str, object]:
    """Inspect delivered records only, including each repeated copy in the counts."""
    recent = recent_reports(available, history_minutes)
    joined = recent.merge(stream.modification_log.drop(columns=["time", "delivered_time"]),
                          on="record_id", how="left", validate="one_to_one")
    joined["fault_applied"] = joined["fault_applied"].eq(True)
    east = joined["east_offset_meters"].fillna(0)
    north = joined["north_offset_meters"].fillna(0)
    latitude_origin = (gate.south_latitude + gate.north_latitude) / 2
    joined["original_longitude"] = joined["longitude"] - east / (
        METERS_PER_DEGREE * np.cos(np.deg2rad(latitude_origin)))
    joined["original_latitude"] = joined["latitude"] - north / METERS_PER_DEGREE
    joined["offset_meters"] = np.hypot(east, north)
    columns = ["record_id", "time", "delivered_time", "longitude", "latitude", "sog", "fault_applied",
               "original_longitude", "original_latitude", "offset_meters"]
    return {"audience_only": True, "affected_in_window": int(joined["fault_applied"].sum()),
            "actual_affected_share": float(joined["fault_applied"].mean()) if len(joined) else None,
            "records": joined.tail(VISIBLE_REPORT_LIMIT)[columns].to_dict(orient="records"),
            "visible_limit": VISIBLE_REPORT_LIMIT}


@dataclass
class EvaluationEvidence:
    """Read saved forecasts once per suite, with a bounded two-table cache."""

    output_directory: Path
    seed: int
    _tables: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)

    def _table(self, suite: str) -> pd.DataFrame | None:
        path = self.output_directory / "results" / f"evaluation_{suite}" / "predictions.csv"
        if not path.exists():
            return None
        if suite not in self._tables:
            batches = []
            for chunk in pd.read_csv(path, usecols=list(TIMELINE_COLUMNS), chunksize=TIMELINE_CHUNK_ROWS,
                                     dtype={"approach_id": str, "decision_id": str}):
                batches.append(chunk.loc[chunk["system"].isin(DISPLAY_SYSTEMS) & chunk["seed"].eq(self.seed)])
            table = pd.concat(batches, ignore_index=True)
            table["decision_time"] = pd.to_datetime(table["decision_time"])
            self._tables[suite] = table
        return self._tables[suite]

    def timeline(self, approach_id: str, scenario: str, until: pd.Timestamp, *, reveal: bool) -> dict[str, object]:
        suite = "primary" if scenario in {item.name for item in primary_scenarios()} else "volume"
        table = self._table(suite)
        if table is None:
            return {"available": False, "points": [], "seed": self.seed}
        points = table.loc[table["approach_id"].eq(approach_id) & table["scenario"].eq(scenario)
                           & table["decision_time"].le(until)].sort_values(["decision_time", "system"])
        columns = ["decision_id", "decision_time", "system", "available", "predicted_arrival_time"]
        if reveal:
            columns.append("error_minutes")
        return {"available": not points.empty, "points": points[columns].to_dict(orient="records"),
                "seed": self.seed, "human_assisted": False, "source": "saved evaluation forecasts"}

    def failure_examples(self) -> list[dict[str, object]]:
        """Choose explicit C failures on the displayed seed, across distinct approaches.

        The all-model top-100 failure CSV can contain only A/B extremes, so it
        cannot reliably supply C examples. Reuse the same cached forecast table.
        """
        table = self._table("primary")
        if table is None:
            return []
        candidates = table.loc[table["system"].eq("C") & table["available"] & table["error_minutes"].notna()].copy()
        candidates["absolute_error"] = candidates["error_minutes"].abs()
        worst = candidates.sort_values("absolute_error", ascending=False).drop_duplicates("approach_id").head(3)
        columns = ["approach_id", "decision_id", "scenario", "error_minutes", "decision_time", "seed"]
        return worst[columns].to_dict(orient="records")

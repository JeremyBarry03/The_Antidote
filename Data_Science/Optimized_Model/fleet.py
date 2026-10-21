"""Month-wide historical fleet replay using the fitted predictors and causal reports.

March is an exploratory product demonstration, never a new held-out evaluation.
Fault audit fields and crossing truth are joined only after feature extraction.
"""

from collections import OrderedDict
import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from .evaluation import predict_systems
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS
from .replay import Condition, Scenario, create_stream
from .views import view_row

if TYPE_CHECKING:
    from .service import DemoService


def epoch(value: object) -> float:
    return pd.Timestamp(value).value / 1e9


class FleetReplay:
    """Read-only replay; interactive controls never train or alter saved artifacts."""

    def __init__(self, service: "DemoService") -> None:
        self.service = service
        self.start = pd.Timestamp("2024-03-01")
        self.end = pd.Timestamp("2024-04-01")
        decisions = service.dataset.decisions
        march = decisions.loc[decisions["decision_time"].between(self.start, self.end, inclusive="left")]
        self.approaches = {identity: group.sort_values("decision_time").iloc[0].to_dict()
                           for identity, group in march.groupby("approach_id")}
        self.ordered = sorted(self.approaches.values(), key=lambda item: item["decision_time"])
        self.systems = [system for system in service.systems if system.name in ("A", "B", "C")]
        self.streams: OrderedDict = OrderedDict()
        self.frames: OrderedDict = OrderedDict()
        self.names, self.crossings = self._archive_metadata()
        self.initial = self.ordered[0]["decision_time"] if self.ordered else self.start
        for item in self.ordered:
            clock = item["decision_time"]
            if sum(row["decision_time"] <= clock < row["arrival_time"] for row in self.ordered) >= 3:
                self.initial = clock
                break

    def _archive_metadata(self) -> tuple[dict, dict]:
        """Read names and recorded crossing brackets; these are display/scoring only."""
        names, after_points = {}, {}
        vessels = {str(item["mmsi"]) for item in self.ordered}
        after_keys = {(str(item["mmsi"]), pd.Timestamp(item["crossing_after"])) for item in self.ordered}
        source = self.service.config.baseline.input_csv
        columns = ["mmsi", "base_date_time", "longitude", "latitude", "vessel_name"]
        for chunk in pd.read_csv(source, usecols=columns, dtype={"mmsi": str}, chunksize=100_000):
            selected = chunk.loc[chunk["mmsi"].isin(vessels)].copy()
            for row in selected[["mmsi", "vessel_name"]].dropna().drop_duplicates("mmsi").itertuples():
                names.setdefault(row.mmsi, str(row.vessel_name).strip())
            selected["time"] = pd.to_datetime(selected["base_date_time"])
            for row in selected.itertuples():
                key = (row.mmsi, row.time)
                if key in after_keys:
                    after_points[key] = (row.longitude, row.latitude)
        gate = self.service.config.baseline.gate
        crossings = {}
        for identity, item in self.approaches.items():
            before = self.service.dataset.histories[identity].iloc[-1]
            after = after_points.get((str(item["mmsi"]), pd.Timestamp(item["crossing_after"])))
            latitude = float(before["latitude"])
            if after is not None and after[0] != before["longitude"]:
                fraction = np.clip((gate.longitude - before["longitude"]) / (after[0] - before["longitude"]), 0, 1)
                latitude += float(fraction * (after[1] - before["latitude"]))
            crossings[identity] = [gate.longitude, latitude]
        return names, crossings

    def catalog(self) -> dict:
        baseline = self.service.config.baseline
        return {"start": epoch(self.start), "end": epoch(self.end) - 60,
                "initial_time": epoch(self.initial), "approaches": len(self.approaches),
                "vessels": len({item["mmsi"] for item in self.ordered}),
                "seed": self.service.config.evaluation_seeds[0],
                "windows": [{"id": item["approach_id"], "start": epoch(item["decision_time"]),
                             "arrival": epoch(item["arrival_time"])} for item in self.ordered],
                "gate": {"longitude": baseline.gate.longitude, "south": baseline.gate.south_latitude,
                         "north": baseline.gate.north_latitude},
                "partitions": {"training": [baseline.splits.start, baseline.splits.validation_start],
                               "development": [baseline.splits.validation_start, baseline.splits.test_start],
                               "exploratory": [baseline.splits.test_start, baseline.splits.end_exclusive],
                               "calibration": [self.service.config.calibration_start, self.service.config.evaluation_start],
                               "evaluation": [self.service.config.evaluation_start, self.service.config.evaluation_end]},
                "note": "March includes training, development and inspected exploratory data. Live charts are exploratory, not protected test results."}

    @staticmethod
    def scenario(delay: float, fraction: float, offset: float) -> Scenario:
        if not all(math.isfinite(value) for value in (delay, fraction, offset)):
            raise ValueError("Replay controls must be finite numbers.")
        if not (0 <= delay <= 60 and 0 <= fraction <= 1 and 0 <= offset <= 2):
            raise ValueError("Use delay 0–60 min, affected share 0–100%, and offset 0–2 nautical miles.")
        quality = fraction > 0 and offset > 0
        condition = (Condition.COMBINED if delay and quality else Condition.STALE if delay
                     else Condition.QUALITY if quality else Condition.NOMINAL)
        return Scenario("interactive", condition, delay_minutes=delay,
                        affected_fraction=fraction if quality else 0, offset_nautical_miles=offset if quality else 0)

    def frame(self, seconds: float, delay: float = 0, fraction: float = 0, offset: float = .5,
              guard: bool = True) -> dict:
        scenario = self.scenario(delay, fraction, offset)
        if not math.isfinite(seconds) or not epoch(self.start) <= seconds < epoch(self.end):
            raise ValueError("Choose a replay time within March 2024.")
        seconds = math.floor(seconds / 60) * 60
        key = (seconds, delay, fraction, offset, guard)
        if key in self.frames:
            return self.frames[key]
        clock = pd.Timestamp(seconds, unit="s")
        rows, ships = [], []
        for item in self.ordered:
            if not item["decision_time"] <= clock < item["arrival_time"] + pd.Timedelta(minutes=8):
                continue
            identity = item["approach_id"]
            stream_key = (identity, delay, fraction, offset)
            if stream_key not in self.streams:
                self.streams[stream_key] = create_stream(self.service.dataset.histories[identity], scenario,
                    self.service.config.evaluation_seeds[0], self.service.config.baseline.gate)
                if len(self.streams) > 256:
                    self.streams.popitem(last=False)
            stream = self.streams[stream_key]
            # An arrived vessel retains its final pre-crossing prediction as it fades.
            decision_clock = min(clock, item["arrival_time"] - pd.Timedelta(seconds=1))
            available = stream.available(decision_clock)
            row = {**item, "decision_time": decision_clock, "decision_id": f"{identity}:fleet:{seconds}",
                   "scenario": scenario.name, "condition": scenario.condition.value,
                   "seed": self.service.config.evaluation_seeds[0]}
            row.update(view_row(available, pd.Series(row), self.service.extractor))
            if not guard:
                unguarded, _ = self.service.extractor.snapshot(available, decision_clock, guarded=False)
                row["supported"] = not unguarded.empty
                if not unguarded.empty:
                    row.update(unguarded.iloc[0].to_dict())
            rows.append(row)
            ships.append((item, available, stream, row))
        predictions = pd.DataFrame()
        if rows:
            features = pd.DataFrame(rows)
            for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
                if column not in features:
                    features[column] = np.nan
            for column in ("observation_time", "raw_observation_time"):
                if column not in features:
                    features[column] = pd.NaT
            predictions = predict_systems(features, self.systems)
        result = []
        for item, available, stream, row in ships:
            identity = item["approach_id"]
            outputs = predictions.loc[predictions["approach_id"].eq(identity)]
            cards = {output["system"]: {"available": bool(output["available"]),
                     "eta": epoch(output["predicted_arrival_time"]) if pd.notna(output["predicted_arrival_time"]) else None,
                     "error": float(output["error_minutes"]) if pd.notna(output["error_minutes"]) else None}
                     for output in outputs.to_dict(orient="records")}
            # The simulator audit is attached here, after all predictors have run.
            audit = stream.modification_log.set_index("record_id")
            original = self.service.dataset.histories[identity].set_index("time")
            reports = []
            for report in available.itertuples():
                truth = audit.loc[report.record_id]
                raw = original.loc[report.time]
                if isinstance(raw, pd.DataFrame):
                    raw = raw.iloc[0]
                reports.append({"time": epoch(report.time), "delivered": epoch(report.delivered_time),
                    "longitude": report.longitude, "latitude": report.latitude, "speed": report.sog,
                    "course": report.cog, "altered": bool(truth.fault_applied),
                    "original_longitude": raw["longitude"], "original_latitude": raw["latitude"]})
            arrived = clock >= item["arrival_time"]
            age = (row["decision_time"] - available["time"].max()).total_seconds() / 60 if len(available) else None
            reasons = str(row.get("reasons", "")).split("|")
            inconsistent = any(reason in reasons for reason in ("implausible_position_jump", "conflicting_bin_positions"))
            if not cards.get("C", {}).get("available") or age is None or age > 15:
                alert = "review"
            elif inconsistent:
                alert = "handled" if guard else "review"
            else:
                alert = "clear"
            result.append({"id": identity, "mmsi": str(item["mmsi"]),
                "name": self.names.get(str(item["mmsi"]), f"Vessel {item['mmsi']}"),
                "type": "Tanker" if len(available) and available["vessel_type"].iloc[-1] >= 80 else "Cargo",
                "arrival": epoch(item["arrival_time"]), "split": item["split"], "arrived": arrived,
                "fade": max(0., 1 - max(0., seconds - epoch(item["arrival_time"])) / 480),
                "crossing_position": self.crossings[identity] if arrived else None,
                "reports": reports, "predictions": cards, "age_minutes": age,
                "diagnostics": {"state": alert, "reasons": [reason for reason in reasons if reason],
                                "received": row.get("guard_received_count", 0),
                                "consolidated_or_removed": row.get("guard_removed_count", 0),
                                "guard_enabled": guard}})
        payload = {"time": seconds, "ships": result, "condition": scenario.condition.value,
                   "delay_minutes": delay, "affected_fraction": fraction, "offset_nm": offset,
                   "guard": guard, "seed": self.service.config.evaluation_seeds[0],
                   "scoring": "Historical crossing truth is retrospective and never a predictor input."}
        self.frames[key] = payload
        if len(self.frames) > 96:
            self.frames.popitem(last=False)
        return payload

    def history(self, seconds: float, delay: float = 0, fraction: float = 0, offset: float = .5,
                guard: bool = True) -> dict:
        """Seed the comparison with measured past frames, never future forecasts."""
        self.frame(seconds, delay, fraction, offset, guard)  # Validate before constructing a range.
        end = math.floor(seconds / 60) * 60
        start = max(int(epoch(self.start)), end - 1800)
        samples = []
        for clock in sorted(set([*range(start, end + 1, 300), end])):
            frame = self.frame(clock, delay, fraction, offset, guard)
            cases = []
            for ship in frame["ships"]:
                outputs = ship["predictions"]
                if not ship["arrived"] and all(outputs[model]["available"] and outputs[model]["error"] is not None
                                                for model in ("A", "B", "C")):
                    cases.append({"id": ship["id"], "errors": {model: outputs[model]["error"] for model in ("A", "B", "C")}})
            if cases:
                samples.append({"time": clock, "cases": cases})
        return {"samples": samples, "window_minutes": 30, "source": "fitted_models_on_causal_historical_reports"}

"""Matched checkpoint summaries for the interactive fleet analysis charts."""

from collections import defaultdict
import math

import numpy as np
import pandas as pd

from .fleet import FleetService, poisoning_settings, unix_seconds
from .fleet_mitigations import FleetPolicy


MODEL_NAMES = ("A", "B", "C")
METHODOLOGY = "Daily summaries use 15-minute checkpoints; final-hour convergence and 30-minute stability use the original 5-minute checkpoints. Each approach has equal weight within daily means."
COVERAGE_NOTE = "Unavailable predictions remain in scheduled denominators and are omitted from error means."
CAVEAT = "Historical AIS and injected faults are exploratory; this comparison is not operational validation."


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    return float(np.quantile(values, quantile)) if values else None


class FleetAnalysis:
    """Compute chart aggregates from matched causal model forecasts."""

    def __init__(self, fleet: FleetService) -> None:
        self.fleet = fleet
        self.catalog = fleet.catalog()
        self.start = pd.Timestamp(self.catalog["evaluation_start"], unit="s", tz="UTC")
        self.end = pd.Timestamp(self.catalog["evaluation_end"], unit="s", tz="UTC")
        self.cutover = pd.Timestamp(self.catalog["poisoning_cutover"], unit="s", tz="UTC")
        self.evaluation_decisions = fleet.dataset.partition(fleet.split).copy()
        self.evaluation_decisions["decision_time"] = pd.to_datetime(self.evaluation_decisions["decision_time"], utc=True)
        self.evaluation_decisions["arrival_time"] = pd.to_datetime(self.evaluation_decisions["arrival_time"], utc=True)
        self.evaluation_decisions = self.evaluation_decisions.loc[
            self.evaluation_decisions.decision_time.ge(self.start)
            & self.evaluation_decisions.decision_time.lt(self.end)
        ].sort_values(["decision_time", "approach_id"])

        grouped = self.evaluation_decisions.groupby("approach_id", sort=False)
        elapsed = (self.evaluation_decisions["decision_time"]
                   - grouped["decision_time"].transform("min")).dt.total_seconds().div(60)
        is_last = self.evaluation_decisions.index.isin(grouped.tail(1).index)
        self.monthly_decisions = self.evaluation_decisions.loc[elapsed.mod(15).eq(0) | is_last].copy()
        self.sequence_decisions = self.evaluation_decisions.loc[elapsed.le(30)].copy()
        remaining = (self.evaluation_decisions["arrival_time"]
                     - self.evaluation_decisions["decision_time"]).dt.total_seconds().div(60)
        self.convergence_decisions = self.evaluation_decisions.loc[remaining.ge(0) & remaining.lt(60)].copy()
        sampled = pd.concat([self.monthly_decisions, self.sequence_decisions, self.convergence_decisions])
        self.decisions = sampled.drop_duplicates("decision_id").sort_values(["decision_time", "approach_id"])
        self.monthly_ids = set(self.monthly_decisions.decision_id.astype(str))
        self.sequence_ids = set(self.sequence_decisions.decision_id.astype(str))
        self.convergence_ids = set(self.convergence_decisions.decision_id.astype(str))

    def _forecast_rows(self, settings: object, *, decisions: pd.DataFrame | None = None,
                       delivery_delay_minutes: float = 0,
                       include_clean: bool = True,
                       progress=lambda _done, _total: None) -> list[dict[str, object]]:
        settings_tuple = poisoning_settings(settings)
        named_settings = dict(zip((item["id"] for item in self.catalog["attack_controls"]), settings_tuple))
        active = any(settings_tuple)
        policy = FleetPolicy(
            enabled=True,
            position_faults=bool(named_settings["location_drift"] or named_settings["position_jump"]),
            noise=bool(named_settings["sensor_deterioration"]),
            speed_drift=bool(named_settings["sensor_drift"]),
        )
        rows: list[dict[str, object]] = []
        selected_decisions = self.decisions if decisions is None else decisions
        total = len(selected_decisions)
        for index, decision in enumerate(selected_decisions.itertuples(index=False), start=1):
            decision_row = pd.Series(decision._asdict())
            identity = str(decision_row["approach_id"])
            clock = decision_row["decision_time"]
            arrival = decision_row["arrival_time"]
            report_clock = clock.tz_convert(None) if clock.tzinfo is not None else clock
            attack_active = active and clock >= self.cutover
            applied = settings_tuple if attack_active else (0.0,) * len(settings_tuple)
            attack_start = self.cutover.tz_convert(None) if attack_active else None
            nominal, changed, _ = self.fleet._stream(identity, applied, attack_start=attack_start)
            if delivery_delay_minutes:
                nominal = nominal.copy()
                changed = changed.copy()
                nominal["delivered_time"] = nominal["delivered_time"] + pd.Timedelta(minutes=delivery_delay_minutes)
                changed["delivered_time"] = changed["delivered_time"] + pd.Timedelta(minutes=delivery_delay_minutes)
            normal = nominal.loc[nominal.time.le(report_clock) & nominal.delivered_time.le(report_clock)]
            received = changed.loc[changed.time.le(report_clock) & changed.delivered_time.le(report_clock)]
            decision_row["decision_time"] = report_clock
            decision_row["arrival_time"] = arrival.tz_convert(None) if arrival.tzinfo is not None else arrival
            clean_predictions = (self.fleet._predict(normal, decision_row, FleetPolicy(enabled=True),
                                                     system_names=MODEL_NAMES)[0]
                                 if include_clean else {})
            selected_predictions = (self.fleet._predict(received, decision_row, policy,
                                                       system_names=MODEL_NAMES)[0]
                                    if attack_active or delivery_delay_minutes or not include_clean
                                    else clean_predictions)
            rows.append({
                "decision_id": str(decision_row["decision_id"]),
                "approach_id": identity,
                "mmsi": str(decision_row["mmsi"]),
                "decision_time": clock,
                "arrival_time": arrival,
                "remaining_minutes": (arrival - clock).total_seconds() / 60,
                "poisoned": attack_active,
                "selected": selected_predictions,
                "clean": clean_predictions,
            })
            if index % 20 == 0 or index == total:
                progress(index, total)
        return rows

    @staticmethod
    def _errors(rows: list[dict[str, object]], model: str, arm: str = "selected") -> list[float]:
        values = [entry["error"] for row in rows
                  if (entry := row[arm][model]).get("available") and entry.get("error") is not None
                  and math.isfinite(entry["error"])]
        return values

    @staticmethod
    def _mae(rows: list[dict[str, object]], model: str, arm: str = "selected") -> float | None:
        values = FleetAnalysis._errors(rows, model, arm)
        return _mean([abs(value) for value in values])

    def _daily(self, rows: list[dict[str, object]], active: bool) -> list[dict[str, object]]:
        grouped: dict[pd.Timestamp, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            grouped[row["decision_time"].normalize()].append(row)
        days: list[dict[str, object]] = []
        for day in sorted(grouped):
            group = grouped[day]
            models: dict[str, object] = {}
            matched = [row for row in group if all(row[arm][name].get("available")
                       for name in MODEL_NAMES for arm in ("selected", "clean"))]
            for model in MODEL_NAMES:
                per_approach: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"selected": [], "clean": []})
                for row in matched:
                    for arm in ("selected", "clean"):
                        per_approach[row["approach_id"]][arm].append(row[arm][model]["error"])
                chosen = [_mean(values["selected"]) for values in per_approach.values()]
                clean = [_mean(values["clean"]) for values in per_approach.values()]
                chosen_absolute = [_mean([abs(value) for value in values["selected"]])
                                   for values in per_approach.values()]
                clean_absolute = [_mean([abs(value) for value in values["clean"]])
                                  for values in per_approach.values()]
                models[model] = {
                    "mean_error": _mean([value for value in chosen if value is not None]),
                    "mae": _mean([value for value in chosen_absolute if value is not None]),
                    "clean_mean_error": _mean([value for value in clean if value is not None]),
                    "clean_mae": _mean([value for value in clean_absolute if value is not None]),
                    "unavailable_decisions": len(group) - sum(row["selected"][model].get("available") for row in group),
                }
            days.append({
                "day": unix_seconds(day), "poisoned": bool(active and day >= self.cutover),
                "matched_decisions": sum(all(row[arm][model].get("available") for model in MODEL_NAMES
                                             for arm in ("selected", "clean")) for row in group),
                "scheduled_decisions": len(group), "approaches": len({row["approach_id"] for row in group}),
                "models": models,
            })
        return days

    def _convergence(self, rows: list[dict[str, object]]) -> dict[str, object]:
        samples = []
        for minute in range(60, -1, -5):
            low, high = (0, 5) if minute == 0 else (minute - 5, minute)
            group = [row for row in rows if low <= row["remaining_minutes"] < high]
            matched = [row for row in group if all(row[arm][model].get("available")
                       for model in MODEL_NAMES for arm in ("selected", "clean"))]
            models = {}
            for model in MODEL_NAMES:
                by_approach: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"selected": [], "clean": []})
                for row in matched:
                    for arm in ("selected", "clean"):
                        by_approach[row["approach_id"]][arm].append(row[arm][model]["error"])
                chosen = [_mean(values["selected"]) for values in by_approach.values()]
                clean = [_mean(values["clean"]) for values in by_approach.values()]
                models[model] = {
                    "mae": _mean([abs(value) for value in chosen if value is not None]),
                    "clean_mae": _mean([abs(value) for value in clean if value is not None]),
                    "unavailable_decisions": len(group) - len(chosen),
                }
            samples.append({
                "minute": minute, "from_minutes": low, "to_minutes": high,
                "matched_decisions": sum(all(row[arm][model].get("available")
                                             for model in MODEL_NAMES for arm in ("selected", "clean"))
                                          for row in group),
                "scheduled_decisions": len(group), "approaches": len({row["approach_id"] for row in group}),
                "models": models,
            })
        return {"samples": samples, "matched_decisions": sum(item["matched_decisions"] for item in samples),
                "scheduled_decisions": sum(item["scheduled_decisions"] for item in samples),
                "methodology": "Approach-weighted five-minute bins by minutes to the recorded analytical crossing.",
                "coverage_note": COVERAGE_NOTE, "approaches": len({row["approach_id"] for row in rows}),
                "caveat": CAVEAT}

    def _sequences(self, rows: list[dict[str, object]]) -> tuple[dict[str, object], dict[str, object]]:
        by_approach: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            by_approach[row["approach_id"]].append(row)
        offsets = list(range(0, 31, 5))
        complete: dict[str, list[dict[str, object]]] = {}
        short_or_incomplete = 0
        unsupported = 0
        for identity, group in by_approach.items():
            group.sort(key=lambda item: item["decision_time"])
            first = group[0]["decision_time"]
            sequence = []
            for offset in offsets:
                target = first + pd.Timedelta(minutes=offset)
                closest = min(group, key=lambda item: abs((item["decision_time"] - target).total_seconds()))
                if abs((closest["decision_time"] - target).total_seconds()) > 150:
                    sequence = []
                    break
                sequence.append(closest)
            if len(sequence) != len(offsets):
                short_or_incomplete += 1
            elif not all(item[arm][model].get("available")
                         for item in sequence for arm in ("selected", "clean") for model in MODEL_NAMES):
                unsupported += 1
            else:
                complete[identity] = sequence

        sequence_samples = []
        stability_samples = []
        for index, offset in enumerate(offsets):
            movement_models: dict[str, object] = {}
            shift_models: dict[str, object] = {}
            for model in MODEL_NAMES:
                shifts, clean_shifts, movements, updates, clean_movements = [], [], [], [], []
                for sequence in complete.values():
                    base, current = sequence[0], sequence[index]
                    shift = (current["selected"][model]["eta"] - base["selected"][model]["eta"]) / 60
                    clean_shift = (current["clean"][model]["eta"] - base["clean"][model]["eta"]) / 60
                    shifts.append(shift); clean_shifts.append(clean_shift); movements.append(abs(shift))
                    clean_movements.append(abs(clean_shift))
                    if index:
                        updates.append(abs((current["selected"][model]["eta"] - sequence[index - 1]["selected"][model]["eta"]) / 60))
                shift_models[model] = {"mean_eta_shift": _mean(shifts), "clean_mean_eta_shift": _mean(clean_shifts)}
                movement_models[model] = {
                    "movement": {"mean": _mean(movements), "p10": _percentile(movements, .1),
                                 "p90": _percentile(movements, .9), "clean_mean": _mean(clean_movements)},
                    "updates": {"mean": _mean(updates), "p10": _percentile(updates, .1),
                                "p90": _percentile(updates, .9), "clean_mean": None},
                }
            sequence_samples.append({"minute": offset, "matched_instances": len(complete),
                                     "scheduled_instances": len(by_approach),
                                     "vessels": len({row[0]["mmsi"] for row in complete.values()}),
                                     "models": shift_models})
            stability_samples.append({"minute": offset, "instances": len(complete),
                                      "models": movement_models})
        total_vessels = len({row[0]["mmsi"] for row in by_approach.values()})
        methodology = "Approach-weighted forecasts at 0–30 minutes from each approach’s first checkpoint."
        return (
            {"samples": sequence_samples, "matched_instances": len(complete),
             "scheduled_instances": len(by_approach), "approaches": len(by_approach), "vessels": total_vessels,
             "methodology": methodology, "coverage_note": "Only complete sequences with all three models are included."},
            {"samples": stability_samples, "instances": len(complete), "total_approaches": len(by_approach),
             "vessels": total_vessels, "short_or_incomplete": short_or_incomplete, "unsupported": unsupported,
             "methodology": "Complete matched 30-minute sequences; spread is across observed approaches.",
             "coverage_note": "Only approaches with all seven checkpoints and all three models are included."},
        )

    def monthly(self, settings: object, progress=lambda _done, _total: None) -> dict[str, object]:
        settings_tuple = poisoning_settings(settings)
        active = any(settings_tuple)
        rows = self._forecast_rows(settings, progress=progress)
        monthly_rows = [row for row in rows if row["decision_id"] in self.monthly_ids]
        convergence_rows = [row for row in rows if row["decision_id"] in self.convergence_ids]
        sequence_rows = [row for row in rows if row["decision_id"] in self.sequence_ids]
        days = self._daily(monthly_rows, active)
        cutover_rows = [row for row in monthly_rows if row["decision_time"] >= self.cutover]
        impact_models = {}
        for model in MODEL_NAMES:
            paired = [row for row in cutover_rows if row["clean"][model].get("available")
                      and row["selected"][model].get("available")]
            clean = [abs(row["clean"][model]["error"]) for row in paired]
            chosen = [abs(row["selected"][model]["error"]) for row in paired]
            impact_models[model] = {"mae_clean": _mean(clean), "mae_scenario": _mean(chosen),
                                    "added_mae": _mean([new - old for old, new in zip(clean, chosen)])}
        paired_count = sum(all(row["clean"][model].get("available") and row["selected"][model].get("available")
                               for model in MODEL_NAMES) for row in cutover_rows)
        sequence, stability = self._sequences(sequence_rows)
        values = [row for row in monthly_rows if all(row["selected"][model].get("available") for model in MODEL_NAMES)]
        affected = 0
        if active:
            identities = {row["approach_id"] for row in monthly_rows if row["poisoned"]}
            for identity in identities:
                _, _, names = self.fleet._stream(identity, settings_tuple, attack_start=self.cutover.tz_convert(None))
                affected += len(names)
        return {
            "status": "ready", "start": unix_seconds(self.start), "end": unix_seconds(self.end),
            "cutover": unix_seconds(self.cutover), "period_label": self.catalog["evaluation_label"],
            "days": days, "matched_decisions": len(values), "scheduled_decisions": len(monthly_rows),
            "approaches": int(self.evaluation_decisions["approach_id"].nunique()),
            "vessels": int(self.evaluation_decisions["mmsi"].nunique()), "methodology": METHODOLOGY,
            "coverage_note": COVERAGE_NOTE, "source": "Historical AIS replay",
            "caveat": CAVEAT, "affected_reports": affected,
            "seed": self.fleet.config.evaluation_seeds[0], "poisoning_active": active,
            "convergence": self._convergence(convergence_rows), "sequence": sequence,
            "insights": {
                "impact": {"models": impact_models, "matched_decisions": paired_count,
                           "scheduled_decisions": len(cutover_rows), "methodology": "Paired clean and selected forecasts at the same post-cutover checkpoints."},
                "stability": stability,
            },
        }

    def stress(self, progress=lambda _done, _total: None) -> dict[str, object]:
        delays = (0, 2, 5, 10, 15)
        runs = []
        total = len(self.monthly_decisions) * len(delays)
        done = 0
        for delay in delays:
            rows = self._forecast_rows({}, decisions=self.monthly_decisions,
                delivery_delay_minutes=delay, include_clean=False,
                progress=lambda current, _size: progress(done + current, total))
            runs.append((delay, rows))
            done += len(rows)
            progress(done, total)
        decisions_by_delay = [{row["decision_id"]: row for row in rows} for _, rows in runs]
        common = set.intersection(*(set(identity for identity, row in run.items()
            if all(row["selected"][model].get("available") for model in MODEL_NAMES))
            for run in decisions_by_delay)) if decisions_by_delay else set()
        samples = []
        for (delay, rows), lookup in zip(runs, decisions_by_delay):
            matched_rows = [lookup[identity] for identity in common]
            models = {}
            for model in MODEL_NAMES:
                errors = self._errors(matched_rows, model)
                models[model] = {"mae": _mean([abs(value) for value in errors]),
                                 "unavailable_decisions": len(rows) - len(common)}
            samples.append({"minute": delay, "matched_decisions": len(common),
                            "scheduled_decisions": len(rows),
                "approaches": len({row["approach_id"] for row in rows}), "models": models})
        return {"status": "ready", "samples": samples,
                "matched_decisions": sum(sample["matched_decisions"] for sample in samples),
                "scheduled_decisions": sum(sample["scheduled_decisions"] for sample in samples),
                "period_label": self.catalog["evaluation_label"],
                "cutover": unix_seconds(self.cutover),
                "methodology": "Forecasts are recomputed after delaying delivered reports; every delay uses the same checkpoints supported by all three models.",
                "coverage_note": COVERAGE_NOTE, "approaches": int(self.monthly_decisions["approach_id"].nunique()),
                "seed": self.fleet.config.evaluation_seeds[0]}

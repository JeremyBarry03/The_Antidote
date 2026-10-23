"""Read-only chart reductions over existing frozen fleet inference.

These are dashboard analyses, not replacements for the research evaluations.
Every forecast is causal; crossing times are used only to score/alignment.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import logging
from threading import RLock, Event
from uuid import uuid4

import numpy as np
import pandas as pd

from Optimized_Model.fleet import ATTACK_CONTROLS, poisoning_settings, unix_seconds
from Optimized_Model.fleet_mitigations import FleetPolicy

MODELS = ("A", "B", "C")
METHOD = "Matched A/B/C and clean/scenario decisions; mean within approach, then equal approach weight."
COVERAGE = "Unavailable forecasts remain null and are excluded jointly, never replaced with zero."
logger = logging.getLogger(__name__)


def mean(values):
    return float(np.mean(values)) if len(values) else None


class Analysis:
    def __init__(self, fleet, lock, progress, cancelled):
        self.fleet, self.lock, self.progress, self.cancelled = fleet, lock, progress, cancelled
        self.start = pd.Timestamp(fleet.config.evaluation_start)
        self.end = pd.Timestamp(fleet.config.evaluation_end)
        self.cutover = self.start.replace(day=15)
        self.completed = 0

    def tick(self, total):
        if self.cancelled.is_set():
            raise InterruptedError("Analysis superseded or server shutting down.")
        self.completed += 1
        self.progress(self.completed, total)

    def streams(self, identity, settings):
        with self.lock:
            nominal, changed, names = self.fleet._stream(identity, settings)
        # Attack only new observations. Pre-cutover report values/delivery stay original.
        selected = pd.concat([nominal.loc[nominal.time.lt(self.cutover)],
                              changed.loc[changed.time.ge(self.cutover)]]).sort_values("time")
        affected = sum(record in names for record in nominal.loc[nominal.time.ge(self.cutover), "record_id"])
        return nominal, selected, affected

    def predict(self, reports, template, identity, clock, policy):
        if self.cancelled.is_set():
            raise InterruptedError()
        received = reports.loc[reports.time.le(clock) & reports.delivered_time.le(clock)]
        decision = template.copy()
        decision["approach_id"], decision["decision_time"] = identity, clock
        decision["decision_id"] = f"{identity}:{clock.isoformat()}"
        with self.lock:
            return self.fleet._predict(received, decision, policy)[0]

    def record(self, identity, template, clock, nominal, selected, policy):
        clean = self.predict(nominal, template, identity, clock, FleetPolicy())
        scenario = self.predict(selected, template, identity, clock, policy)
        return {"identity": identity, "mmsi": str(template.mmsi), "clock": clock,
                "remaining": (template.arrival_time - clock).total_seconds() / 60,
                "clean": clean, "scenario": scenario,
                "matched": all(arm[m]["available"] for arm in (clean, scenario) for m in MODELS)}

    def summary(self, rows):
        matched = [r for r in rows if r["matched"]]
        models = {}
        for model in MODELS:
            entry = {}
            for arm, prefix in (("scenario", ""), ("clean", "clean_")):
                for key, absolute in (("mean_error", False), ("mae", True)):
                    grouped = {}
                    for row in matched:
                        error = row[arm][model]["error"]
                        grouped.setdefault(row["identity"], []).append(abs(error) if absolute else error)
                    entry[prefix + key] = mean([mean(v) for v in grouped.values()])
            entry["available_decisions"] = sum(r["scenario"][model]["available"] for r in rows)
            entry["unavailable_decisions"] = len(rows) - entry["available_decisions"]
            models[model] = entry
        return {"scheduled_decisions": len(rows), "matched_decisions": len(matched),
                "approaches": len({r["identity"] for r in matched}),
                "vessels": len({r["mmsi"] for r in matched}), "models": models}

    def monthly(self, payload):
        settings = poisoning_settings(payload)
        selected = dict(zip((c["id"] for c in ATTACK_CONTROLS), settings))
        policy = FleetPolicy(position_faults=bool(selected["position_jump"] or selected["location_drift"]),
                             noise=bool(selected["sensor_deterioration"]), speed_drift=bool(selected["sensor_drift"]))
        decisions = self.fleet.dataset.partition(self.fleet.split).sort_values("decision_time")
        total = len(decisions) + 31 * len(self.fleet.approaches)
        self.progress(0, total)
        rows, sequences, affected = [], [], 0
        for identity, template in self.fleet.approaches.iterrows():
            nominal, scenario, count = self.streams(identity, settings)
            affected += count
            for _, decision in decisions.loc[decisions.approach_id.eq(identity)].iterrows():
                rows.append(self.record(identity, decision, decision.decision_time, nominal, scenario, policy))
                self.tick(total)
            first = decisions.loc[decisions.approach_id.eq(identity), "decision_time"].min()
            sequence = []
            for minute in range(31):
                clock = first + pd.Timedelta(minutes=minute)
                sequence.append(self.record(identity, template, clock, nominal, scenario, policy)
                                if clock < template.arrival_time and clock < self.end else None)
                self.tick(total)
            sequences.append(sequence)
        days = []
        for day in pd.date_range(self.start, self.end, freq="D", inclusive="left"):
            daily = [r for r in rows if r["clock"].floor("D") == day]
            days.append({"day": unix_seconds(day), "poisoned": bool(any(settings) and day >= self.cutover),
                         **self.summary(daily)})
        convergence = []
        for lower in range(0, 60, 5):
            group = [r for r in rows if lower <= r["remaining"] < lower + 5]
            convergence.append({"minute": lower + 2.5, "from_minutes": lower, "to_minutes": lower + 5,
                                **self.summary(group)})
        # Sequence support is shared across all models and both arms at each point.
        samples = []
        for minute in range(31):
            supported = [s for s in sequences if s[0] and s[minute] and s[0]["matched"] and s[minute]["matched"]]
            models = {}
            for model in MODELS:
                values = {}
                for arm, prefix in (("scenario", ""), ("clean", "clean_")):
                    values[prefix + "mean_eta_shift"] = mean([(s[minute][arm][model]["eta"] - s[0][arm][model]["eta"]) / 60 for s in supported])
                    values[prefix + "mean_remaining_minutes"] = mean([(s[minute][arm][model]["eta"] - unix_seconds(s[minute]["clock"])) / 60 for s in supported])
                models[model] = values
            samples.append({"minute": minute, "scheduled_instances": len(sequences), "matched_instances": len(supported),
                            "vessels": len({s[0]["mmsi"] for s in supported}), "models": models})
        offsets = list(range(0, 31, 5))
        complete = [s for s in sequences if all(s[i] is not None for i in offsets)]
        fixed = [s for s in complete if all(s[i]["matched"] for i in offsets)]
        stability_samples = []
        for i in offsets:
            models = {}
            for model in MODELS:
                metrics = {}
                for metric, prior in (("movement", 0), ("updates", max(0, i - 5))):
                    values = [abs(s[i]["scenario"][model]["eta"] - s[prior]["scenario"][model]["eta"]) / 60 for s in fixed]
                    clean = [abs(s[i]["clean"][model]["eta"] - s[prior]["clean"][model]["eta"]) / 60 for s in fixed]
                    metrics[metric] = {"mean": mean(values), "clean_mean": mean(clean),
                                       **{key: float(np.percentile(values, q)) if values else None
                                          for key, q in (("median", 50), ("p10", 10), ("p90", 90))}}
                models[model] = metrics
            stability_samples.append({"minute": i, "instances": len(fixed), "models": models})
        impact = self.summary([r for r in rows if r["clock"] >= self.cutover])
        for model, entry in impact["models"].items():
            entry.update(mae_clean=entry["clean_mae"], mae_scenario=entry["mae"],
                         added_mae=entry["mae"] - entry["clean_mae"] if entry["mae"] is not None else None)
        summary = self.summary(rows)
        return {"status": "ready", "start": unix_seconds(self.start), "end": unix_seconds(self.end),
                "cutover": unix_seconds(self.cutover), "poisoning_active": any(settings),
                "affected_reports": affected, "seed": self.fleet.config.evaluation_seeds[0],
                **{k: v for k, v in summary.items() if k != "models"}, "days": days,
                "methodology": METHOD, "source": "Hash-verified historical AIS replay and frozen A/B/C models.",
                "caveat": "Simulated disruption; analytical harbor crossing is not docking. No confidence claim.",
                "sequence": {"window_minutes": 30, "approaches": len(sequences),
                             "vessels": len(self.fleet.approaches.mmsi.unique()), "matched_instances": samples[-1]["matched_instances"],
                             "samples": samples, "methodology": "First scheduled decision through minute 30; each model's own initial ETA.", "coverage_note": COVERAGE},
                "convergence": {"samples": convergence, **{k: v for k, v in self.summary([r for r in rows if 0 <= r["remaining"] < 60]).items() if k != "models"},
                                "methodology": METHOD, "coverage_note": COVERAGE},
                "insights": {"impact": {**impact, "methodology": METHOD},
                             "stability": {"samples": stability_samples, "instances": len(fixed), "total_approaches": len(sequences),
                                           "short_or_incomplete": len(sequences) - len(complete), "unsupported": len(complete) - len(fixed),
                                           "vessels": len({s[0]["mmsi"] for s in fixed}),
                                           "methodology": "Same supported cohort at all seven five-minute offsets; absolute ETA changes.", "coverage_note": COVERAGE}}}

    def stress(self):
        delays = (0, 2, 5, 10, 15)
        decisions = self.fleet.dataset.partition(self.fleet.split)
        total = len(decisions) * len(delays)
        self.progress(0, total)
        groups = {d: [] for d in delays}
        for identity, template in self.fleet.approaches.iterrows():
            nominal, _, _ = self.streams(identity, poisoning_settings({}))
            for _, decision in decisions.loc[decisions.approach_id.eq(identity)].iterrows():
                checkpoint = []
                for delay in delays:
                    delayed = nominal.copy()
                    delayed["delivered_time"] = delayed.time + pd.Timedelta(minutes=delay)
                    pred = self.predict(delayed, decision, identity, decision.decision_time, FleetPolicy())
                    checkpoint.append({"identity": identity, "mmsi": str(template.mmsi), "clean": pred, "scenario": pred})
                    self.tick(total)
                matched = all(r["scenario"][m]["available"] for r in checkpoint for m in MODELS)
                for delay, row in zip(delays, checkpoint):
                    row["matched"] = matched
                    groups[delay].append(row)
        samples = [{"minute": d, **self.summary(groups[d])} for d in delays]
        return {"status": "ready", "samples": samples, "seed": self.fleet.config.evaluation_seeds[0],
                **{k: v for k, v in self.summary(groups[0]).items() if k != "models"},
                "methodology": "Simulated constant report delivery delay; identical supported decisions at all five delays. " + METHOD,
                "coverage_note": COVERAGE, "source": "Frozen historical AIS replay; independent of sliders."}


class AnalysisJobs:
    """Bounded single-worker queue and result cache; use exactly one ASGI worker.

    Job IDs expire on restart/eviction; frontend can retry to recreate them.
    """
    def __init__(self, fleet, inference_lock, capacity=8):
        self.fleet, self.inference_lock, self.capacity = fleet, inference_lock, capacity
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self.jobs = OrderedDict()

    def close(self):
        with self.lock:
            for entry in self.jobs.values():
                entry["cancelled"].set()
        self.pool.shutdown(wait=True, cancel_futures=True)

    def poll(self, job):
        with self.lock:
            if job not in self.jobs:
                raise ValueError("Unknown or expired job. Retry the analysis.")
            return dict(self.jobs[job]["payload"])

    def monthly(self, settings, client):
        return self.submit(("monthly", poisoning_settings(settings)), settings)

    def stress(self, retry):
        return self.submit(("stress",), None, retry)

    def submit(self, key, settings, retry=False):
        with self.lock:
            for job, entry in list(self.jobs.items()):
                if entry["key"] == key:
                    if entry["payload"]["status"] != "error" or (key[0] == "stress" and not retry):
                        return dict(entry["payload"])
                    del self.jobs[job]
            if len(self.jobs) >= self.capacity:
                done = next((j for j, e in self.jobs.items() if e["payload"]["status"] in ("ready", "error")), None)
                if done is None:
                    from starlette.exceptions import HTTPException
                    raise HTTPException(429, "Analysis queue is full. Retry after a job completes.")
                del self.jobs[done]
            job = uuid4().hex
            entry = {"key": key, "cancelled": Event(),
                     "payload": {"job_id": job, "status": "queued", "phase": "Waiting for inference", "completed": 0, "total": 0}}
            self.jobs[job] = entry
            self.pool.submit(self.run, entry, settings)
            return dict(entry["payload"])

    def run(self, entry, settings):
        def progress(completed, total):
            with self.lock:
                entry["payload"].update(status="running", phase="Causal frozen-model inference", completed=completed, total=total)
        try:
            analysis = Analysis(self.fleet, self.inference_lock, progress, entry["cancelled"])
            result = analysis.stress() if settings is None else analysis.monthly(settings)
            with self.lock:
                entry["payload"] = {**entry["payload"], **result}
        except Exception:
            logger.exception("Dashboard analysis failed")
            with self.lock:
                entry["payload"].update(status="error", error="Analysis failed; inspect server logs and retry.")

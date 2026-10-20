"""Build matched input views once for all predictors, with labels kept as metadata."""

from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path

import pandas as pd

from eta_baselines.dataset import file_digest
from eta_baselines.configuration import ExperimentConfig

from .configuration import GuardConfig, OptimizedConfig
from .dataset import ReplayDataset
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from .replay import Scenario, create_stream
from .scenarios import training_scenarios

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayTask:
    baseline: ExperimentConfig
    guard: GuardConfig
    decisions: pd.DataFrame
    history: pd.DataFrame
    scenarios: list[Scenario]
    seed: int
    seen_vessel: bool


def view_row(
    reports: pd.DataFrame, decision: pd.Series, extractor: OptimizedFeatures,
) -> dict[str, object]:
    """Training and serving call the same feature extraction paths."""
    raw, _ = extractor.snapshot(reports, decision["decision_time"], guarded=False)
    guarded, diagnostics = extractor.snapshot(reports, decision["decision_time"], guarded=True)
    row: dict[str, object] = {
        "raw_supported": not raw.empty, "supported": not guarded.empty,
        "guard_received_count": diagnostics.received_count,
        "guard_removed_count": diagnostics.removed_count,
        "reasons": "|".join(diagnostics.reasons),
    }
    if not raw.empty:
        row.update({f"raw_{column}": raw.iloc[0][column] for column in RICH_COLUMNS})
        row["raw_observation_time"] = raw.iloc[0]["observation_time"]
    if not guarded.empty:
        row.update(guarded.iloc[0].to_dict())
    return row


def _replay_approach(task: ReplayTask) -> tuple[list[dict[str, object]], pd.DataFrame, list[dict[str, object]]]:
    extractor = OptimizedFeatures(task.baseline, task.guard)
    approach_id = task.decisions["approach_id"].iloc[0]
    rows, modifications, fault_audits = [], [], []
    cached_snapshots: dict[bytes, list[dict[str, object]]] = {}
    for scenario in task.scenarios:
        stream = create_stream(task.history, scenario, task.seed, task.baseline.gate)
        observed_columns = ["mmsi", "time", "delivered_time", "longitude", "latitude", "sog", "cog", "vessel_type"]
        canonical = stream.reports[observed_columns].drop_duplicates()
        key = pd.util.hash_pandas_object(canonical, index=False).to_numpy().tobytes()
        cached = cached_snapshots.get(key)
        snapshots = []
        audit = stream.modification_log.copy()
        audit["approach_id"] = approach_id
        modifications.append(audit)
        for index, (_, decision) in enumerate(task.decisions.iterrows()):
            row = decision.to_dict()
            snapshot = (cached[index] if cached is not None else
                        view_row(stream.available(decision["decision_time"]), decision, extractor))
            snapshots.append(snapshot)
            row.update(snapshot)
            row.update({"scenario": scenario.name, "condition": scenario.condition.value, "seed": task.seed})
            row["seen_training_vessel"] = task.seen_vessel
            row["decision_to_arrival_minutes"] = (
                decision["arrival_time"] - decision["decision_time"]
            ).total_seconds() / 60
            rows.append(row)
            # Evaluator-only provenance never enters the feature table.
            received_truth = audit.loc[(audit["time"] <= decision["decision_time"])
                                       & (audit["delivered_time"] <= decision["decision_time"])]
            if len(received_truth):
                latest = received_truth["time"].max()
                received_truth = received_truth.loc[received_truth["time"] >= latest - pd.Timedelta(
                    minutes=task.baseline.features.history_minutes,
                )]
            fault_audits.append({"decision_id": row["decision_id"], "scenario": scenario.name, "seed": task.seed,
                                 "received_reports_before_deduplication": len(received_truth),
                                 "faulty_reports": int(received_truth["fault_applied"].sum()),
                                 "actual_fault_share": float(received_truth["fault_applied"].mean()) if len(received_truth) else None})
        cached_snapshots[key] = snapshots
    return rows, pd.concat(modifications, ignore_index=True), fault_audits


def materialize_views(
    dataset: ReplayDataset, config: OptimizedConfig, split: str,
    scenarios: list[Scenario] | None, seed: int, name: str,
) -> pd.DataFrame:
    """Persist provenance and reuse matching feature caches on reruns."""
    directory = config.output_directory / "views"
    directory.mkdir(exist_ok=True)
    destination = directory / f"{name}.csv"
    signature = {
        "split": split, "seed": seed, "scenarios": [asdict(item) for item in scenarios] if scenarios else "training_mixture",
        "replay_sha256": file_digest(config.output_directory / "replay_dataset.joblib"),
        "feature_columns": list(OPTIMIZED_COLUMNS),
        "feature_implementation": {str(path): file_digest(path) for path in
                                   [Path(__file__).with_name(name) for name in
                                    ("features.py", "quality.py", "replay.py", "scenarios.py", "views.py")]
                                   + [Path(__file__).resolve().parents[1] / "eta_baselines" / name
                                      for name in ("features.py", "motion.py")]},
    }
    signature_path = destination.with_suffix(".json")
    if destination.exists() and signature_path.exists():
        saved = json.loads(signature_path.read_text())
        if saved == signature:
            return read_views(destination)
    decisions = dataset.partition(split)
    seen_vessels = set(dataset.partition("train")["mmsi"])
    if decisions.empty:
        raise ValueError(f"No approaches available for {split}.")
    rows = []
    modifications = []
    fault_audits = []
    baseline = config.baseline
    tasks = [ReplayTask(baseline, config.guard, group, dataset.histories[approach_id],
                        scenarios if scenarios is not None else training_scenarios(config, approach_id, seed),
                        seed, group["mmsi"].iloc[0] in seen_vessels)
             for approach_id, group in decisions.groupby("approach_id", sort=False)]
    # Feature replay is CPU-bound Python work; processes share the existing CPU budget.
    pool = ProcessPoolExecutor(max_workers=baseline.training.cpu_threads)
    futures = [pool.submit(_replay_approach, task) for task in tasks]
    try:
        for index, future in enumerate(futures):
            batch, audit, prevalence = future.result()
            rows.extend(batch)
            modifications.append(audit)
            fault_audits.extend(prevalence)
            if (index + 1) % 25 == 0:
                logger.info("%s: prepared %s approaches", name, index + 1)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    views = pd.DataFrame(rows)
    for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
        if column not in views:
            views[column] = float("nan")
    for column in ("observation_time", "raw_observation_time"):
        if column not in views:
            views[column] = pd.NaT
    views.to_csv(destination, index=False)
    signature_path.write_text(json.dumps(signature, indent=2), encoding="utf-8")
    # Truth lives outside the feature table. Only scoring tools read this file.
    pd.concat(modifications, ignore_index=True).to_csv(directory / f"{name}_modifications.csv", index=False)
    pd.DataFrame(fault_audits).to_csv(directory / f"{name}_fault_audit.csv", index=False)
    return views


def read_views(path: Path) -> pd.DataFrame:
    views = pd.read_csv(path, dtype={"mmsi": str, "approach_id": str})
    for column in ("observation_time", "raw_observation_time", "decision_time", "arrival_time",
                   "episode_start", "crossing_before", "crossing_after"):
        views[column] = pd.to_datetime(views[column])
    views["reasons"] = views["reasons"].fillna("")
    return views


def predictor_inputs(views: pd.DataFrame, input_view: str) -> pd.DataFrame:
    result = views.copy()
    if input_view == "raw":
        for column in RICH_COLUMNS:
            result[column] = result[f"raw_{column}"]
        result["observation_time"] = result["raw_observation_time"]
    elif input_view != "guarded":
        raise ValueError(f"Unknown input view: {input_view}")
    return result

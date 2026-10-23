"""Reuse nominal reference events; replay inputs never construct their own labels."""

from dataclasses import asdict, dataclass
from collections import Counter
import json
import logging
from pathlib import Path
import shutil

import joblib
import pandas as pd

from eta_baselines.approaches import ApproachBuilder
from eta_baselines.dataset import file_digest
from eta_baselines.features import FeatureBuilder
from eta_baselines.observations import iter_observation_vessels
from eta_baselines.training import load_examples

from .configuration import OptimizedConfig

logger = logging.getLogger(__name__)
METADATA_COLUMNS = (
    "approach_id", "mmsi", "episode_start", "arrival_time", "crossing_before",
    "crossing_after", "decision_time", "split",
)


@dataclass
class ReplayDataset:
    decisions: pd.DataFrame
    histories: dict[str, pd.DataFrame]
    manifest: dict[str, object]

    def partition(self, name: str) -> pd.DataFrame:
        return self.decisions.loc[self.decisions["split"] == name].copy()


def _freeze_baselines(config: OptimizedConfig, expected: dict[str, str] | None) -> dict[str, str]:
    hashes = {}
    for name in ("quadratic", "xgboost"):
        frozen = config.frozen_baseline_model(name)
        if not frozen.exists():
            source = config.baseline.output_directory / name / "model.joblib"
            source_hash = file_digest(source)
            if expected is not None and source_hash != expected[name]:
                raise ValueError(f"Baseline {name} changed before snapshotting; use a versioned comparison.")
            frozen.parent.mkdir(parents=True, exist_ok=True)
            temporary = frozen.with_suffix(".partial")
            try:
                shutil.copy2(source, temporary)
                if file_digest(temporary) != source_hash:
                    raise ValueError(f"Baseline {name} changed while being copied.")
                temporary.replace(frozen)
            finally:
                temporary.unlink(missing_ok=True)
        hashes[name] = file_digest(frozen)
        if expected is not None and hashes[name] != expected[name]:
            raise ValueError(f"Frozen baseline {name} changed; use a versioned comparison.")
    return hashes


def prepare_replay(config: OptimizedConfig) -> Path:
    baseline = config.baseline
    config.output_directory.mkdir(parents=True, exist_ok=True)
    paths = [baseline.input_csv] + ([config.later_csv] if config.later_csv.exists() else [])
    signature = {str(path): file_digest(path) for path in paths}
    cache = config.output_directory / "replay_dataset.joblib"
    existing = joblib.load(cache) if cache.exists() else None
    expected = (existing.manifest.get("frozen_baseline_hashes", existing.manifest["baseline_model_hashes"])
                if existing is not None else None)
    frozen_hashes = _freeze_baselines(config, expected)
    if cache.exists():
        if (existing.manifest["sources"] == signature and existing.manifest["config"] == config.snapshot()
                and existing.manifest.get("baseline_configuration") == json.loads(json.dumps(asdict(baseline), default=str))):
            logger.info("Reusing matching replay dataset")
            return cache
    examples = load_examples(baseline)
    decisions = examples[list(METADATA_COLUMNS)].copy()
    decisions.loc[decisions["split"] == "test", "split"] = "exploratory"
    decisions = decisions.loc[decisions["split"] != "purged"].copy()
    audit: Counter = Counter()
    histories: dict[str, pd.DataFrame] = {}
    vessel_events = {str(identity): group for identity, group in decisions.groupby("mmsi")}
    for vessel, counts in iter_observation_vessels(baseline.input_csv):
        audit.update(counts)
        if vessel.empty:
            continue
        events = vessel_events.get(str(vessel["mmsi"].iloc[0]))
        if events is None:
            continue
        for event in events.drop_duplicates("approach_id").itertuples():
            histories[event.approach_id] = vessel.loc[
                vessel["time"].between(event.episode_start, event.crossing_before)
            ].reset_index(drop=True)
    frames = [decisions]
    later_audit: dict[str, object] = {}
    if config.later_csv.exists():
        later_counts: Counter = Counter()
        episode_counts: Counter = Counter()
        builder = FeatureBuilder(baseline.gate, baseline.features)
        for vessel, counts in iter_observation_vessels(config.later_csv):
            later_counts.update(counts)
            approaches, counts = ApproachBuilder(baseline.gate).build(vessel)
            episode_counts.update(counts)
            for approach in approaches:
                if approach.observations.empty:
                    continue
                first = approach.observations["time"].iloc[0]
                split = None
                if pd.Timestamp(config.calibration_start) <= first and approach.crossing_after < pd.Timestamp(config.evaluation_start):
                    split = "calibration"
                if pd.Timestamp(config.evaluation_start) <= first and approach.crossing_after < pd.Timestamp(config.evaluation_end):
                    split = "evaluation"
                if split is None:
                    continue
                frame = builder.examples(approach)
                if frame.empty:
                    continue
                frame["split"] = split
                frames.append(frame[list(METADATA_COLUMNS)])
                histories[approach.approach_id] = approach.observations
        later_audit = {**later_counts, "episodes": dict(episode_counts)}
    combined = pd.concat(frames, ignore_index=True)
    combined["decision_id"] = combined["approach_id"] + ":" + combined["decision_time"].astype(str)
    if combined["decision_id"].duplicated().any():
        raise ValueError("Duplicate replay decision IDs; source windows must not overlap.")
    counts = combined.groupby("split").agg(
        decisions=("decision_id", "size"), approaches=("approach_id", "nunique"), vessels=("mmsi", "nunique"),
    ).to_dict(orient="index")
    baseline_hashes = {
        name: file_digest(config.frozen_baseline_model(name))
        for name in ("quadratic", "xgboost")
    }
    manifest = {"sources": signature, "config": config.snapshot(), "split_counts": counts,
                "baseline_configuration": json.loads(json.dumps(asdict(baseline), default=str)),
                "baseline_model_hashes": baseline_hashes, "source_audit": audit,
                "frozen_baseline_hashes": frozen_hashes,
                "later_source_audit": later_audit,
                "reference_labels": "Original nominal gate-crossing brackets, never corrupted.",
                "geographic_review": "Analytical gate remains provisional; no official berth-arrival claim.",
                "baseline_test_status": "Inspected by baseline training; exploratory only."}
    joblib.dump(ReplayDataset(combined, histories, manifest), cache)
    combined.to_csv(config.output_directory / "decisions.csv", index=False)
    combined.drop_duplicates("approach_id").to_csv(config.output_directory / "reference_approaches.csv", index=False)
    (config.output_directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Replay partitions: %s", counts)
    return cache


def prepare_evaluation_replay(config: OptimizedConfig) -> Path:
    """Build a replay from the configured evaluation CSV and frozen models.

    This is for a separately supplied evaluation month when the original
    training CSV is unavailable locally. It labels only the configured
    evaluation window and never fits or changes any model.
    """
    source = config.later_csv
    if not source.exists():
        raise FileNotFoundError(f"Evaluation replay source is missing: {source}")
    baseline = config.baseline
    beginning, ending = pd.Timestamp(config.evaluation_start), pd.Timestamp(config.evaluation_end)
    builder = ApproachBuilder(baseline.gate)
    features = FeatureBuilder(baseline.gate, baseline.features)
    decisions: list[pd.DataFrame] = []
    histories: dict[str, pd.DataFrame] = {}
    audit: Counter = Counter()
    for vessel, counts in iter_observation_vessels(source):
        audit.update(counts)
        approaches, approach_counts = builder.build(vessel)
        audit.update(approach_counts)
        for approach in approaches:
            if not beginning <= approach.crossing_after < ending:
                continue
            examples = features.examples(approach)
            if examples.empty:
                continue
            examples["split"] = "evaluation"
            decisions.append(examples[list(METADATA_COLUMNS)])
            histories[approach.approach_id] = approach.observations.copy()
    if not decisions:
        raise ValueError(f"No replay approaches found in {beginning.date()}–{(ending-pd.Timedelta(days=1)).date()}.")
    frame = pd.concat(decisions, ignore_index=True)
    frame["decision_id"] = frame["approach_id"] + ":" + frame["decision_time"].astype(str)
    if frame["decision_id"].duplicated().any():
        raise ValueError("Duplicate evaluation decision IDs; inspect the source records.")
    counts = frame.groupby("split").agg(
        decisions=("decision_id", "size"), approaches=("approach_id", "nunique"),
        vessels=("mmsi", "nunique"),
    ).to_dict(orient="index")
    frozen_hashes = {name: file_digest(config.frozen_baseline_model(name))
                     for name in ("quadratic", "xgboost")}
    manifest = {
        "sources": {str(source): file_digest(source)}, "config": config.snapshot(),
        "split_counts": counts,
        "baseline_configuration": json.loads(json.dumps(asdict(baseline), default=str)),
        "baseline_model_hashes": frozen_hashes, "frozen_baseline_hashes": frozen_hashes,
        "source_audit": audit, "reference_labels": "Original analytical harbor crossing, never corrupted.",
        "geographic_review": "Analytical gate remains provisional; no official berth-arrival claim.",
        "baseline_test_status": "Evaluation-only replay; saved model artifacts are unchanged.",
    }
    config.output_directory.mkdir(parents=True, exist_ok=True)
    dataset = ReplayDataset(frame, histories, manifest)
    cache = config.output_directory / "replay_dataset.joblib"
    joblib.dump(dataset, cache)
    frame.to_csv(config.output_directory / "decisions.csv", index=False)
    frame.drop_duplicates("approach_id").to_csv(config.output_directory / "reference_approaches.csv", index=False)
    (config.output_directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Evaluation replay: %s", counts)
    return cache


def load_replay(config: OptimizedConfig) -> ReplayDataset:
    path = config.output_directory / "replay_dataset.joblib"
    if not path.exists():
        raise FileNotFoundError("Run prepare before fitting or evaluating model C.")
    dataset: ReplayDataset = joblib.load(path)
    if dataset.manifest["config"] != config.snapshot():
        raise ValueError("Replay configuration changed; run prepare again.")
    expected_baseline = json.loads(json.dumps(asdict(config.baseline), default=str))
    if dataset.manifest.get("baseline_configuration") != expected_baseline:
        raise ValueError("Baseline preparation configuration changed; run prepare again.")
    for source, expected in dataset.manifest["sources"].items():
        if file_digest(Path(source)) != expected:
            raise ValueError(f"Replay source changed: {source}; run prepare again.")
    frozen_hashes = dataset.manifest.get("frozen_baseline_hashes", dataset.manifest["baseline_model_hashes"])
    for name, expected in frozen_hashes.items():
        if file_digest(config.frozen_baseline_model(name)) != expected:
            raise ValueError(f"Frozen baseline changed: {name}; create a versioned comparison.")
    return dataset

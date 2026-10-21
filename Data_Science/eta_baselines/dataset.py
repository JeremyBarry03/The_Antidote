"""Prepare reusable examples and purge approaches crossing calendar partitions."""

import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from .approaches import ApproachBuilder
from .configuration import ExperimentConfig, SplitConfig
from .features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, FeatureBuilder
from .observations import load_observations

logger = logging.getLogger(__name__)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assign_splits(examples: pd.DataFrame, config: SplitConfig) -> pd.DataFrame:
    result = examples.copy()
    result["split"] = "purged"
    boundaries = (config.start, config.validation_start, config.test_start, config.end_exclusive)
    for name, start, end in zip(("train", "validation", "test"), boundaries, boundaries[1:]):
        # Include the entire reference bracket, not merely its interpolated midpoint.
        inside = ((result["episode_start"] >= pd.Timestamp(start))
                  & (result["crossing_after"] < pd.Timestamp(end)))
        result.loc[inside, "split"] = name
    return result


def prepare_dataset(config: ExperimentConfig) -> Path:
    observations, audit = load_observations(config.input_csv)
    approaches, approach_audit = ApproachBuilder(config.gate).build(observations)
    builder = FeatureBuilder(config.gate, config.features)
    frames = [builder.examples(approach) for approach in approaches]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise ValueError("No eligible approaches produced examples. Review gate/cohort geometry.")
    examples = assign_splits(pd.concat(frames, ignore_index=True), config.splits)
    output = config.output_directory
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "examples.csv"
    examples.to_csv(destination, index=False)
    episode_columns = ["approach_id", "mmsi", "episode_start", "arrival_time",
                       "crossing_before", "crossing_after", "split"]
    episodes = examples[episode_columns].drop_duplicates("approach_id")
    episodes.to_csv(output / "approaches.csv", index=False)
    summary = examples.groupby("split").agg(
        snapshots=("approach_id", "size"), approaches=("approach_id", "nunique"),
        vessels=("mmsi", "nunique"),
    )
    manifest = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "feature_columns": list(FEATURE_COLUMNS),
        "input_csv": str(config.input_csv), "input_sha256": file_digest(config.input_csv),
        "audit": audit, "approach_audit": approach_audit,
        "crossings_without_examples": len(approaches) - len(episodes),
        "split_counts": summary.to_dict(orient="index"),
        "arrival_definition": "Interpolated east-to-west crossing of the configured analytical gate.",
        "limitations": [
            "Research gate, not an official port entrance or verified berth arrival.",
            "Conditional on an observed qualifying crossing; destination intent is assumed.",
            "Unresolved episodes have no regression label and are counted separately.",
            "No countermeasure or controlled degradation is applied to these nominal baselines.",
            "Same vessels may occur in different calendar partitions; identities are not features.",
        ],
    }
    (output / "data_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    config.save(output / "config_snapshot.json")
    logger.info("Prepared split counts:\n%s", summary.to_string())
    return destination

"""Explicit prepare/train/calibrate/evaluate stages prevent accidental test tuning."""

import argparse
import logging
from pathlib import Path

import pandas as pd

from .calibration import apply_review, fit_calibration, load_calibration, save_review_curves
from .configuration import OptimizedConfig
from .dataset import load_replay, prepare_replay
from .evaluation import load_systems, predict_systems, save_evaluation
from .model import train_models
from .scenarios import primary_scenarios, stress_scenarios, volume_scenarios
from .views import materialize_views

logger = logging.getLogger(__name__)


def evaluate_partition(config: OptimizedConfig, partition: str, suite: str) -> pd.DataFrame:
    dataset = load_replay(config)
    decisions = dataset.partition(partition)
    if decisions.empty:
        raise ValueError(f"No {partition} data; acquire later observations and rerun prepare.")
    if partition == "evaluation" and decisions["approach_id"].nunique() < config.review.minimum_evaluation_approaches:
        raise ValueError("Protected evaluation has too few approaches; extend dates before viewing results.")
    systems = load_systems(config)
    scenarios = {"primary": primary_scenarios, "stress": lambda: stress_scenarios(config),
                 "volume": volume_scenarios}[suite]()
    seeds = config.evaluation_seeds if partition == "evaluation" else [1042]
    if partition == "calibration":
        # Reserved drift must remain unseen during model design and interval calibration.
        scenarios = [scenario for scenario in scenarios if not scenario.drift]
        seeds = [2042]
    predictions = []
    fixed_views = None
    for index, seed in enumerate(seeds):
        # Only nominal/delay-only streams are guaranteed independent of fault seed.
        # Drift's causal fallback direction can vary when a report has zero motion.
        fixed = [scenario for scenario in scenarios if scenario.affected_fraction == 0]
        varying = [scenario for scenario in scenarios if scenario not in fixed]
        selected = scenarios if index == 0 else varying
        views = materialize_views(dataset, config, partition, selected, seed,
                                  f"{partition}_{suite}_{seed}")
        if index == 0:
            fixed_views = views.loc[views["scenario"].isin([scenario.name for scenario in fixed])].copy()
        elif fixed_views is not None:
            views = pd.concat([views, fixed_views.assign(seed=seed)], ignore_index=True)
        predictions.append(predict_systems(views, systems))
    return pd.concat(predictions, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate degradation-aware model C.")
    parser.add_argument("command", choices=("acquire", "prepare", "train", "calibrate", "evaluate", "pilot", "serve"))
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config_vessel_class_v2.json"))
    parser.add_argument("--suite", choices=("primary", "stress", "volume"), default="primary")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = OptimizedConfig.load(args.config)
    if args.command == "acquire":
        from .acquisition import acquire_later_data

        acquire_later_data(config.later_csv, config.calibration_start, config.evaluation_end)
    elif args.command == "prepare":
        prepare_replay(config)
    elif args.command == "train":
        dataset = load_replay(config)
        train = materialize_views(dataset, config, "train", None, 42, "training")
        development = materialize_views(dataset, config, "validation", None, 1042, "development")
        train_models(train, development, config)
    elif args.command == "calibrate":
        predictions = evaluate_partition(config, "calibration", "primary")
        fit_calibration(predictions, config)
        reviewed = apply_review(predictions, load_calibration(config), config)
        save_evaluation(reviewed, config, "calibration")
        save_review_curves(reviewed, config, "calibration")
    elif args.command in ("evaluate", "pilot"):
        calibration = load_calibration(config) if args.command == "evaluate" else None
        partition = "evaluation" if args.command == "evaluate" else "exploratory"
        predictions = evaluate_partition(config, partition, args.suite)
        name = f"{partition}_{args.suite}"
        if calibration is not None:
            predictions = apply_review(predictions, calibration, config)
            save_review_curves(predictions, config, name)
        save_evaluation(predictions, config, name)
    else:
        from .service import serve

        serve(config, args.port)


if __name__ == "__main__":
    main()

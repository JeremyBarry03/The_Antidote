"""Run from Data_Science: python -m eta_baselines prepare|train|all."""

import argparse
import logging
from pathlib import Path

from .configuration import ExperimentConfig
from .dataset import prepare_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare and train nominal arrival-reference baselines.")
    parser.add_argument("command", choices=("prepare", "train", "all"))
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    parser.add_argument("--model", choices=("quadratic", "xgboost", "both"), default="both")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = ExperimentConfig.load(arguments.config)
    if arguments.command in ("prepare", "all"):
        prepare_dataset(config)
    if arguments.command in ("train", "all"):
        from .training import BaselineTrainer, load_examples

        models = ["quadratic", "xgboost"] if arguments.model == "both" else [arguments.model]
        BaselineTrainer(config).train(load_examples(config), models)


if __name__ == "__main__":
    main()

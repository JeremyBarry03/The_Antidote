"""Exercise every fitting/evaluation stage on a small five-period fixture."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from eta_baselines.configuration import ExperimentConfig
from eta_baselines.dataset import prepare_dataset
from eta_baselines.training import BaselineTrainer, load_examples
from experiments.data_eval import run
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay, prepare_replay
from Optimized_Model.model import train_models
from Optimized_Model.views import materialize_views


def point_fixture(days):
    frames = []
    for day in days:
        for mmsi in ("123456789", "234567890"):
            times = pd.date_range(f"{day} 12:00", periods=23, freq="min")
            frames.append(pd.DataFrame({
                "mmsi": mmsi,
                "base_date_time": times.strftime("%Y-%m-%d %H:%M:%S" if day.startswith("2024") else "%Y-%m-%dT%H:%M:%S"),
                "longitude": np.linspace(-76.2, -76.31, len(times)),
                "latitude": 37.0, "sog": 16.0, "cog": 270.0, "vessel_type": 70,
            }))
    return pd.concat(frames, ignore_index=True)


def test_fit_abc_and_score_original_march_with_separate_calibration(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    baseline = json.loads((root / "config_data_eval.json").read_text())
    baseline.update(input_csv=str(tmp_path / "fit.csv"), output_directory=str(tmp_path / "baselines"))
    baseline["training"].update(cpu_threads=1, ridge_alphas=[1.0], xgboost_depths=[2],
                                xgboost_learning_rates=[.1], xgboost_max_rounds=8,
                                xgboost_early_stopping_rounds=2)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    point_fixture(["2023-01-05", "2023-10-05", "2023-11-05"]).to_csv(tmp_path / "fit.csv", index=False)
    point_fixture(["2023-12-05", "2024-03-05"]).to_csv(tmp_path / "later.csv", index=False)
    optimized = json.loads((root / "Optimized_Model/config_data_eval.json").read_text())
    optimized.update(baseline_config=str(baseline_path), later_csv=str(tmp_path / "later.csv"),
                     output_directory=str(tmp_path / "optimized"), evaluation_seeds=[4201])
    optimized["review"].update(minimum_calibration_approaches=2,
                               minimum_evaluation_approaches=2, bootstrap_samples=5)
    optimized_path = tmp_path / "optimized.json"
    optimized_path.write_text(json.dumps(optimized))

    base = ExperimentConfig.load(baseline_path)
    prepare_dataset(base)
    BaselineTrainer(base).train(load_examples(base), ["quadratic", "xgboost"])
    config = OptimizedConfig.load(optimized_path)
    prepare_replay(config)
    dataset = load_replay(config)
    assert dataset.partition("calibration")["approach_id"].nunique() == 2
    assert dataset.partition("evaluation")["approach_id"].nunique() == 2
    train = materialize_views(dataset, config, "train", None, 42, "training")
    validation = materialize_views(dataset, config, "validation", None, 1042, "development")
    train_models(train, validation, config)
    monkeypatch.setattr(run, "OPTIMIZED_CONFIG", optimized_path)
    run.evaluate_nominal("calibration")
    run.evaluate_nominal("evaluation")

    predictions = pd.read_csv(tmp_path / "optimized/results/evaluation_nominal/predictions.csv")
    assert set(predictions["system"]) == {"A", "B", "C"}
    assert set(predictions["scenario"]) == {"nominal"}
    assert set(predictions["split"]) == {"evaluation"}
    assert pd.to_datetime(predictions["decision_time"]).between("2024-03-01", "2024-04-01", inclusive="left").all()
    assert predictions["available"].all()
    assert np.isfinite(predictions["error_minutes"]).all()
    assert (tmp_path / "optimized/models/C.joblib").is_file()
    calibration = json.loads((tmp_path / "optimized/calibration.json").read_text())
    assert calibration["reference_approaches"] == 2

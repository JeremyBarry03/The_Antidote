"""Recompute all prior missing-speed cases without touching their saved outputs."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from eta_baselines.dataset import file_digest
from experiments.missing_speed_mitigation.run import approach_views, score
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import load_systems


def main() -> None:
    reference_path = SCIENCE / "experiments/missing_speed_mitigation/results/predictions.csv"
    reference_hash = file_digest(reference_path)
    reference = pd.read_csv(reference_path, dtype={"mmsi": str})
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    predictor = next(system.predictor for system in load_systems(config) if system.name == "C")
    outputs = []
    for split in ("validation", "evaluation"):
        decisions = dataset.partition(split).sort_values(["approach_id", "decision_time"])
        tasks = [(config.baseline, config.guard, dataset.histories[identity], group)
                 for identity, group in decisions.groupby("approach_id", sort=False)]
        originals, mitigated, metadata = [], [], []
        print(f"Speed regression {split}: {len(tasks)} approaches", flush=True)
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(approach_views, task) for task in tasks]
            for completed, future in enumerate(as_completed(futures), 1):
                original, repaired, meta = future.result()
                originals.extend(original)
                mitigated.extend(repaired)
                metadata.extend(meta)
                if completed % 24 == 0 or completed == len(tasks):
                    print(f"  {completed}/{len(tasks)}", flush=True)
        frame = pd.DataFrame(metadata)
        frame["original_error"] = score(originals, frame, predictor)
        frame["mitigated_error"] = score(mitigated, frame, predictor)
        outputs.append(frame)
    current = pd.concat(outputs, ignore_index=True)
    keys = ["split", "decision_id", "fraction", "seed"]
    old = reference.set_index(keys).sort_index()
    new = current.set_index(keys).sort_index()
    assert old.index.equals(new.index)
    maximum_difference = 0.
    for column in ("original_error", "mitigated_error"):
        np.testing.assert_allclose(new[column], old[column], rtol=0, atol=1e-9, equal_nan=True)
        maximum_difference = max(maximum_difference, float((new[column] - old[column]).abs().max()))
    for column in ("missing_guarded_reports", "estimated_reports", "unsupported_reports", "latest_speed_estimated"):
        assert np.array_equal(new[column].to_numpy(), old[column].to_numpy())
    assert file_digest(reference_path) == reference_hash
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    result = {"passed": True, "prediction_pairs": len(new), "maximum_error_difference_minutes": maximum_difference,
              "tolerance_minutes": 1e-9, "reconstruction_diagnostics_identical": True,
              "saved_speed_results_unchanged": True, "reference_sha256": reference_hash,
              "implementation_hashes": {str(path): file_digest(path) for path in [
                  SCIENCE / "mitigation/trusted_motion.py", SCIENCE / "mitigation/navigation_features.py",
                  SCIENCE / "mitigation/missing_speed_mitigation/missing_speed_mitigation.py",
                  SCIENCE / "mitigation/missing_speed_mitigation/optimized_model.py"]}}
    (output / "speed_regression.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

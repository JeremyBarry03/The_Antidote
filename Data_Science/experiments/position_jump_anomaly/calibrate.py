"""Choose an empirical innovation threshold from March navigation, without ETA labels."""

from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

SCIENCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCIENCE))

from eta_baselines.dataset import file_digest
from mitigation.position_jump_mitigation import PositionJumpMitigationConfig
from mitigation.position_jump_mitigation.position_jump_mitigation import position_motion_pairs
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay


def main() -> None:
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    march = dataset.decisions.loc[dataset.decisions.decision_time.lt("2024-04-01")]
    identities = march[["approach_id", "mmsi"]].drop_duplicates()
    counts = identities.groupby("mmsi").size()
    scores, weights = [], []
    policy = PositionJumpMitigationConfig()
    for row in identities.itertuples():
        history = dataset.histories[row.approach_id]
        history = history.loc[history.time.lt("2024-04-01")]
        pairs = position_motion_pairs(history, policy)
        valid = pairs.loc[pairs.assessed, "score"].to_numpy()
        if len(valid):
            scores.extend(valid)
            weights.extend(np.full(len(valid), 1 / (counts.loc[row.mmsi] * len(valid))))
    scores, weights = np.asarray(scores), np.asarray(weights)
    order = np.argsort(scores, kind="stable")
    threshold = float(scores[order[np.searchsorted(np.cumsum(weights[order]), .995 * weights.sum())]])
    result = {"cohort": "March navigation only; no April or ETA labels", "quantile": .995,
        "weighting": "Equal vessel, equal approaches within vessel, equal valid pairs within approach",
        "approaches": len(identities), "vessels": len(counts), "pairs": len(scores),
        "policy": {**asdict(policy), "distance_threshold_squared": threshold},
        "source_hash": file_digest(config.baseline.input_csv),
        "limits": "Empirical clean-pair score threshold, not a guaranteed false-alarm probability. "
                  "The position/velocity scales are fixed experimental normalizers, not sensor specifications. "
                  "Decision-window false alerts are evaluated separately."}
    output = Path(__file__).resolve().parent / "results"
    output.mkdir(parents=True, exist_ok=True)
    (output / "calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

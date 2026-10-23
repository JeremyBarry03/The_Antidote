"""Evaluate anomaly detection, without changing or retraining ETA predictors."""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import PositionJumpAttack, PositionJumpConfig
from eta_baselines.dataset import file_digest
from experiments.position_jump_anomaly.report import write_report
from mitigation.position_jump_mitigation import PositionJumpMitigation, PositionJumpMitigationConfig
from mitigation.position_jump_mitigation.position_jump_mitigation import position_motion_pairs
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.service import DemoService

POLICY = PositionJumpMitigationConfig()
SETTINGS = [("clean", 0., 0), *[("whole_feed", fraction, seed) for fraction in (.1, .2, .25, .5, 1.)
    for seed in (4201, 4202, 4203)], *[("warm_burst", 1., seed) for seed in (4201, 4202, 4203)]]


def window_counts(times: pd.Series, values: np.ndarray, clocks: pd.Series, minutes: float) -> np.ndarray:
    """Count past/current events, including both window endpoints, at each clock."""
    times, clocks = times.to_numpy(), clocks.to_numpy()
    start = np.searchsorted(times, clocks - np.timedelta64(int(minutes * 60 * 1e9), "ns"), side="left")
    end = np.searchsorted(times, clocks, side="right")
    cumulative = np.r_[0, np.cumsum(values)]
    return cumulative[end] - cumulative[start]


def approach_detection(task: tuple) -> tuple[list[dict], list[dict]]:
    history, decisions = task
    rows, audits = [], []
    detector = PositionJumpMitigation(POLICY)
    for mode, fraction, seed in SETTINGS:
        onset = history.time.min() + pd.Timedelta(minutes=20) if mode == "warm_burst" else None
        attack = PositionJumpConfig(affected_fraction=fraction, seed=seed, start_time=onset,
            end_time=onset + pd.Timedelta(minutes=15) if onset is not None else None)
        stream = PositionJumpAttack(attack).apply(history)
        assert stream.reports.delivered_time.eq(stream.reports.time).all()
        # Only adjacent earlier/current measurements enter each pair; no fitted
        # future track exists. This cache is valid only for in-order delivery.
        pairs = position_motion_pairs(stream.reports, POLICY)
        pairs = pairs.loc[pairs.time.le(decisions.decision_time.max())].copy()
        alerts = window_counts(pairs.time, pairs.flagged.to_numpy(), decisions.decision_time,
                               POLICY.warning_window_minutes) > 0
        for index in (0, len(decisions) - 1):
            clock = decisions.decision_time.iloc[index]
            assert detector.apply(stream.available(clock), clock).anomaly_detected == alerts[index]
        # Truth enters only after observable warning decisions have been created.
        labels = stream.modification_log.set_index("record_id").fault_applied
        pairs["current_injected"] = pairs.record_id.map(labels)
        pairs["affected_pair"] = pairs.current_injected | pairs.current_injected.shift(fill_value=False)
        involved = window_counts(pairs.time, pairs.affected_pair.to_numpy(), decisions.decision_time,
                                 POLICY.warning_window_minutes) > 0
        positives = pairs.loc[pairs.assessed & pairs.affected_pair]
        detected = positives.loc[positives.flagged]
        delay = ((detected.time.iloc[0] - positives.time.iloc[0]).total_seconds() / 60
                 if len(detected) else None)
        for i, decision in enumerate(decisions.itertuples()):
            rows.append({"approach_id": decision.approach_id, "mmsi": decision.mmsi, "split": decision.split,
                "decision_id": decision.decision_id, "decision_time": decision.decision_time,
                "mode": mode, "fraction": fraction, "seed": seed, "anomaly": bool(alerts[i]),
                "affected_window": bool(involved[i]), "first_detection_delay_minutes": delay})
        pairs = pairs.assign(approach_id=decisions.approach_id.iloc[0], split=decisions.split.iloc[0],
                             mode=mode, fraction=fraction, seed=seed)
        audits.extend(pairs.to_dict(orient="records"))
        unchanged = history.columns.difference(["latitude", "longitude"])
        pd.testing.assert_frame_equal(history[unchanged], stream.reports[unchanged])
    return rows, audits


def summarize(decisions: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (split, mode, fraction), group in decisions.groupby(["split", "mode", "fraction"]):
        audit = pairs.loc[pairs.split.eq(split) & pairs["mode"].eq(mode) & pairs.fraction.eq(fraction)]
        valid = audit.loc[audit.assessed]
        affected, reference = valid.loc[valid.affected_pair], valid.loc[~valid.affected_pair]
        per = group.drop_duplicates(["approach_id", "seed"])
        rows.append({"split": split, "mode": mode, "fraction": fraction,
            "approaches": group.approach_id.nunique(), "decision_times": group.decision_id.nunique(),
            "scheduled_decision_seed_pairs": len(group), "decision_alert_rate": float(group.anomaly.mean()),
            "affected_decision_windows": int(group.affected_window.sum()),
            "affected_window_alert_rate": float(group.loc[group.affected_window, "anomaly"].mean()) if group.affected_window.any() else None,
            "assessed_pairs": len(valid), "affected_pairs": len(affected),
            "affected_pair_detection_rate": float(affected.flagged.mean()) if len(affected) else None,
            "reference_pair_alert_rate": float(reference.flagged.mean()) if len(reference) else None,
            "median_first_detection_delay_minutes": float(per.first_detection_delay_minutes.dropna().median())
                if per.first_detection_delay_minutes.notna().any() else None,
            "detected_approach_profiles": int(per.first_detection_delay_minutes.notna().sum())})
    return pd.DataFrame(rows)


def saved_model_check(config: OptimizedConfig) -> dict:
    """Replay the prior severe failure, comparing the same feed with warnings off/on."""
    service = DemoService.load(config)
    identity = "249489000_20240421T162855:2024-04-21 14:40:00"
    attack = PositionJumpConfig(affected_fraction=.5, seed=4203)
    ordinary = service.position_jump_snapshot(identity, attack, reveal=True, inspect=True)
    warned = service.position_jump_snapshot(identity, attack, reveal=True, inspect=True, mitigate_position_jump=True)
    for arm in ("original", "attacked"):
        assert ordinary[arm]["cards"] == warned[arm]["cards"]
        assert ordinary[arm]["received_history"] == warned[arm]["received_history"]
        assert ordinary[arm]["reference_arrival"] == warned[arm]["reference_arrival"]
    card = next(c for c in warned["attacked"]["cards"] if c["system"] == "C")
    alert = any(a["type"] == "position_jump" for a in warned["attacked"]["anomaly_detection"]["anomalies"])
    assert alert
    return {"decision_id": identity, "seed": 4203, "fraction": .5,
        "all_A_B_C_cards_exactly_unchanged": True, "source_and_reference_unchanged": True,
        "position_warning_triggered": alert, "C_error_minutes": card["error_minutes"],
        "C_absolute_error_minutes": abs(card["error_minutes"]), "forecast_modified": False}


def main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config_vessel_class_v2.json")
    calibration = json.loads((output / "calibration.json").read_text())
    assert asdict(POLICY) == calibration["policy"]
    protected = json.loads((output / "protected_hashes.json").read_text())
    implementation = [Path(__file__), HERE / "calibrate.py", HERE / "report.py", SCIENCE / "Optimized_Model/service.py",
        SCIENCE / "api/anamoly_detector.py", *SCIENCE.joinpath("mitigation/position_jump_mitigation").glob("*.py")]
    hashes = {str(p): file_digest(p) for p in implementation}
    (output / "protocol.json").write_text(json.dumps({"policy": asdict(POLICY), "settings": SETTINGS,
        "training": "none", "ETA_features_modified": False, "calibration": calibration,
        "implementation_hashes": hashes, "metrics": "Pooled eligible adjacent pairs and scheduled decision/seed windows; "
        "pair positive means either endpoint injected. Reference alerts are a false-alarm proxy. "
        "First delay is from first affected eligible pair to first flagged affected pair; undetected profiles excluded and counted separately."}, indent=2), encoding="utf-8")
    dataset = load_replay(config)
    rows, audits = [], []
    for split in ("validation", "evaluation"):
        tasks = [(dataset.histories[identity], group.sort_values("decision_time"))
            for identity, group in dataset.partition(split).groupby("approach_id")]
        print(f"{split}: {len(tasks)} approaches", flush=True)
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(approach_detection, task) for task in tasks]
            for count, future in enumerate(as_completed(futures), 1):
                decisions, pairs = future.result()
                rows.extend(decisions)
                audits.extend(pairs)
                if count % 24 == 0 or count == len(tasks):
                    print(f"  {count}/{len(tasks)}", flush=True)
    decisions, pairs = pd.DataFrame(rows), pd.DataFrame(audits)
    summary = summarize(decisions, pairs)
    smoke = saved_model_check(config)
    assert all(file_digest(Path(p)) == digest for p, digest in protected.items())
    assert all(file_digest(Path(p)) == digest for p, digest in hashes.items())
    decisions.to_csv(output / "decisions.csv", index=False)
    pairs.to_csv(output / "pairs.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    validation = {"protected_hashes_unchanged": True, "protected_files": len(protected),
        "implementation_unchanged_during_run": True, "forecast_modified": False, "model_retrained": False,
        "prefix_checks": 2 * len(SETTINGS) * (36 + 112), "saved_model_failure_case": smoke,
        "elapsed_seconds": time.perf_counter() - started}
    (output / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    write_report(summary, validation, output)
    print(summary.loc[summary.split.eq("evaluation")].to_string(index=False), flush=True)
    print(json.dumps(validation, indent=2), flush=True)


if __name__ == "__main__":
    main()

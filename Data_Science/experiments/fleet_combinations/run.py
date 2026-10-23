"""Exploratory paired screen of the current fleet mitigation integration.

Run from Data_Science: python experiments/fleet_combinations/run.py
No fitting or policy changes. Checkpoints are ignored local artifacts.
"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import version
from itertools import combinations
import argparse
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from eta_baselines.dataset import file_digest
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.evaluation import predict_systems
from Optimized_Model.features import OPTIMIZED_COLUMNS, QUALITY_COLUMNS, RICH_COLUMNS
from Optimized_Model.fleet import ATTACK_CONTROLS, FleetService, poisoning_settings
from Optimized_Model.fleet_mitigations import FleetPolicy
from Optimized_Model.service import DemoService, _json_value
from Optimized_Model.views import view_row

_RUNTIME = None


def scenarios() -> list[dict]:
    names = [control["id"] for control in ATTACK_CONTROLS]
    cases = [{"id": "nominal", "kind": "nominal", "attacks": [], "settings": {}}]
    for size in (1, 2):
        for selected in combinations(names, size):
            cases.append({"id": "__".join(selected), "kind": "single" if size == 1 else "pair",
                          "attacks": list(selected),
                          "settings": {name: 15 if name == "reporting_gap" else 50 for name in selected}})
    for severity, gap in ((50, 15), (100, 30)):
        cases.append({"id": f"all_eight_{severity}", "kind": "stack", "attacks": names,
                      "settings": {name: gap if name == "reporting_gap" else severity for name in names}})
    return cases


def initialize(config_path: str, seed: int) -> None:
    global _RUNTIME
    config = OptimizedConfig.load(Path(config_path))
    service = DemoService.load(config)  # Validate actual current artifacts first.
    runtime_config = replace(config, evaluation_seeds=[seed])
    _RUNTIME = FleetService(runtime_config, service.dataset, service.systems, service.extractor)


def selected_decisions(dataset, mode: str) -> pd.DataFrame:
    selected = []
    for identity, group in dataset.partition("evaluation").groupby("approach_id", sort=True):
        group = group.sort_values("decision_time")
        if mode == "all":
            selected.append(group)
            continue
        start = dataset.histories[identity].time.min()
        outage_index = min(int(group.decision_time.searchsorted(start + pd.Timedelta(minutes=20))), len(group)-1)
        selected.append(group.iloc[sorted({0, outage_index, len(group)//2, len(group)-1})])
    return pd.concat(selected, ignore_index=True)


def evaluate_approach(task: tuple[str, pd.DataFrame, list[dict], str]) -> tuple[list, list, list]:
    identity, decisions, cases, checkpoint = task
    destination = Path(checkpoint)
    if destination.exists():
        return joblib.load(destination)
    fleet = _RUNTIME
    source = fleet.dataset.histories[identity]
    before = pd.util.hash_pandas_object(source, index=True).to_numpy().tobytes()
    off_rows, on_rows, audit_rows = [], [], []
    for case in cases:
        settings = poisoning_settings(case["settings"])
        nominal, changed, _ = fleet._stream(identity, settings)
        values = case["settings"]
        policy = FleetPolicy(enabled=True,
            position_faults=bool(values.get("location_drift") or values.get("position_jump")),
            noise=bool(values.get("sensor_deterioration")),
            speed_drift=bool(values.get("sensor_drift")), trusted_fixes=False)
        for _, decision in decisions.iterrows():
            clock = decision.decision_time
            received = changed.loc[changed.time.le(clock) & changed.delivered_time.le(clock)]
            assert received.time.le(clock).all() and received.delivered_time.le(clock).all()
            row = decision.to_dict()
            row.update(view_row(received, decision, fleet.extractor))
            row.update(scenario=case["id"], condition="nominal", seed=fleet.config.evaluation_seeds[0])
            patch, metadata = fleet.mitigations.apply(received, clock, policy)
            assert not set(patch) & (set(QUALITY_COLUMNS) | {
                "observation_time", "decision_time", "arrival_time", "supported", "raw_supported"})
            assert not any(column.startswith("raw_") for column in patch)
            off_rows.append(row)
            on_rows.append({**row, **patch})
            normal = nominal.loc[nominal.time.le(clock) & nominal.delivered_time.le(clock)]
            record = dict(approach_id=identity, mmsi=str(decision.mmsi), decision_id=decision.decision_id,
                decision_time=clock, scenario=case["id"], seed=row["seed"],
                feature_change=bool(metadata["features_changed"]), received_reports=len(received),
                withheld_reports=len(normal)-len(received),
                review=bool(metadata.get("requires_review")) or bool(row["reasons"]) or not row["supported"],
                any_detection=bool(row["reasons"]) or any(item["detected"] for item in metadata["strategies"]))
            for item in metadata["strategies"]:
                for field in ("detected", "applied", "requires_review", "reconstructed_reports"):
                    record[f"{item['id']}_{field}"] = item[field]
            audit_rows.append(record)
    assert before == pd.util.hash_pandas_object(source, index=True).to_numpy().tobytes()
    result = off_rows, on_rows, audit_rows
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(result, destination)
    return result


def prepare_views(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
        if column not in frame:
            frame[column] = np.nan
    for column in ("observation_time", "raw_observation_time"):
        if column not in frame:
            frame[column] = pd.NaT
        frame[column] = pd.to_datetime(frame[column])
    return frame


def approach_metrics(frame: pd.DataFrame) -> dict:
    valid = frame.loc[frame.available & frame.error_minutes.notna()].copy()
    if valid.empty:
        return {"coverage": 0., "mae": None, "mse": None, "rmse": None, "p95": None}
    grouped = valid.assign(ae=valid.error_minutes.abs(), se=valid.error_minutes**2).groupby("approach_id")
    mse = float(grouped.se.mean().mean())
    return dict(coverage=len(valid)/len(frame), mae=float(grouped.ae.mean().mean()),
                mse=mse, rmse=float(np.sqrt(mse)), p95=float(valid.error_minutes.abs().quantile(.95)))


def paired_interval(frame: pd.DataFrame) -> tuple[float, float]:
    per = frame.groupby(["mmsi", "approach_id"]).delta.mean().reset_index()
    vessels = per.groupby("mmsi").delta.agg(["sum", "count"]).to_numpy()
    rng = np.random.default_rng(20261023)
    draws = rng.integers(len(vessels), size=(1000, len(vessels)))
    sampled = vessels[draws]
    means = sampled[:, :, 0].sum(axis=1) / sampled[:, :, 1].sum(axis=1)
    return tuple(map(float, np.quantile(means, [.025, .975])))


def summarize(predictions: pd.DataFrame, audit: pd.DataFrame, cases: list[dict]):
    rows, pairs = [], []
    for case in cases:
        frame = predictions.loc[predictions.scenario.eq(case["id"])]
        detail = audit.loc[audit.scenario.eq(case["id"])]
        row = dict(scenario=case["id"], kind=case["kind"], attacks="+".join(case["attacks"]),
                   decisions=len(detail), approaches=detail.approach_id.nunique())
        for arm in ("A", "B", "C_guard", "Antidote"):
            for metric, value in approach_metrics(frame.loc[frame.arm.eq(arm)]).items():
                row[f"{arm}_{metric}"] = value
        off = frame.loc[frame.arm.eq("C_guard")].set_index("decision_id")
        on = frame.loc[frame.arm.eq("Antidote")].set_index("decision_id")
        paired = on[["mmsi", "approach_id", "error_minutes", "available"]].rename(
            columns={"error_minutes": "on_error", "available": "on_available"}).join(
            off[["error_minutes", "available"]].rename(columns={"error_minutes": "off_error", "available": "off_available"}))
        paired["scenario"] = case["id"]
        paired["delta"] = paired.on_error.abs()-paired.off_error.abs()
        valid = paired.loc[paired.on_available & paired.off_available].copy()
        row["paired_decisions"] = len(valid)
        row["delta_mae"] = float(valid.groupby("approach_id").delta.mean().mean())
        row["delta_low"], row["delta_high"] = paired_interval(valid)
        row["improved_fraction"] = float(valid.delta.lt(-1e-6).mean())
        row["worsened_fraction"] = float(valid.delta.gt(1e-6).mean())
        row["worsened_over_1min_fraction"] = float(valid.delta.gt(1).mean())
        row["forecast_change_fraction"] = float((valid.on_error-valid.off_error).abs().gt(1e-6).mean())
        for column in ("feature_change", "review", "any_detection"):
            row[f"{column}_fraction"] = float(detail[column].mean())
        row["approach_detection_fraction"] = float(detail.groupby("approach_id").any_detection.any().mean())
        for column in detail:
            if column.endswith(("_applied", "_detected", "_requires_review")):
                row[f"{column}_fraction"] = float(detail[column].eq(True).mean())
        rows.append(row)
        pairs.append(paired.reset_index())
    return pd.DataFrame(rows), pd.concat(pairs, ignore_index=True)


def render_report(summary: pd.DataFrame, protocol: dict) -> str:
    lines = ["# Combined attacks: current Antidote integration", "",
        "## Scope", "",
        f"This is an exploratory screen of {protocol['approaches']} April approaches / "
        f"{protocol['vessels']} vessels at {protocol['decision_clocks']} original decision clocks per scenario. "
        f"It covers {len(protocol['scenarios'])} declared settings with fault seed {protocol['seed']}.",
        "", "The 28 pairs use 50% for each non-gap slider and a fixed 15-minute reporting gap. "
        "At 50%: speed drift is -0.05 knots/min capped at 1.5 knots, location drift is 10 m/min capped "
        "at 926 m, noise sigma is 1 knot / 5 degrees, and position jumps affect half the reports "
        "(2,000 m mean / 200 m SD). Missing fields use deterministic report selection at 50%. "
        "Equal-severity missing-field and position-jump attacks share the same selection hash and seed, "
        "so their selected reports overlap; these are not independent dropout masks. "
        "All-eight cases also include one severe setting (100%, 30-minute gap).",
        "", "Representative clocks are the first, first at/after 20 minutes from approach start, "
        "middle and last existing scheduled decision. Duplicates are removed. Clock selection uses no forecast errors. "
        "These are not scores across all 2,402 clocks unless the protocol says all.",
        "", "Antidote uses the current frozen vessel-class-v2 C plus the dashboard strategies. "
        "C guard is the identical frozen C and trained guard with additional strategies disabled. "
        "A and B see the same raw attacked reports. Verified fixes are absent, matching the current dashboard. "
        "Missing outputs remain in coverage denominators; accuracy uses available outputs. "
        "MAE and MSE first average within each approach and then across approaches; RMSE is the square root of "
        "that MSE. P95 and change shares pool decision clocks. Paired intervals resample vessels 1,000 times "
        "and retain repeated approaches within vessel. They are exploratory, unadjusted for 39 comparisons.",
        "", "## Results", "",
        "| Setting | C guard MAE | Antidote MAE | Change [95% paired interval] | B MAE | Repairs used | Review |",
        "|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        label = row.scenario.replace("__", " + ").replace("_", " ")
        lines.append(f"| {label} | {row.C_guard_mae:.3f} | {row.Antidote_mae:.3f} | "
                     f"{row.delta_mae:+.3f} [{row.delta_low:+.3f}, {row.delta_high:+.3f}] | "
                     f"{row.B_mae:.3f} | {row.feature_change_fraction:.1%} | {row.review_fraction:.1%} |")
    lines += ["", "Negative change means lower ETA absolute error. Review is an input-status warning, "
              "not a withheld forecast, and does not count as an accuracy improvement.",
        "", "## Limits", "",
        "- This April period has already been inspected. These are exploratory follow-up results, not a new holdout.",
        "- Models, thresholds, source records, original crossing labels and UI behavior are frozen during the run.",
        "- The fleet runner knows the selected simulation fault families to choose reference assumptions and pause incompatible repairs. "
        "It is not blind automatic fault isolation.",
        "- Location faults and navigation faults together pause position-based corrections. Noise plus speed drift pauses their overlapping repairs. "
        "Class carry-forward can still operate. These no-op cases assess the current conservative integration, not recovery capability.",
        "- Gap and jump strategies provide warnings; location drift has no coordinate correction without an independently verified reference.",
        "- This is one seed and selected settings. It does not validate all 256 on/off subsets, all slider values, coordinated attacks or deployment safety.",
        "- Scores measure the original analytical harbor crossing, not verified docking. No calibration envelope is transferred to repairs.",
        "", "## Reproduce", "", "`python experiments/fleet_combinations/run.py` from Data_Science. "
        "Use `--clocks all` for all original decision clocks, `--seed N` for another fault realization. "
        "Checkpoints are versioned by the protocol hash under ignored model artifacts. "
        "Raw predictions, repair audit and ranked failures are local CSVs; protocol/summary/validation are JSON.",
        ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=4201)
    parser.add_argument("--clocks", choices=("representative", "all"), default="representative")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("workers must be between one and four")
    started = time.perf_counter()
    config_path = SCIENCE/"Optimized_Model/config_vessel_class_v2.json"
    initialize(str(config_path), args.seed)
    fleet = _RUNTIME
    cases = scenarios()
    decisions = selected_decisions(fleet.dataset, args.clocks)
    output = HERE/"results"/f"{args.clocks}_seed_{args.seed}"
    output.mkdir(parents=True, exist_ok=True)
    model_paths = [config_path, fleet.config.frozen_baseline_model("quadratic"),
                   fleet.config.frozen_baseline_model("xgboost"), fleet.config.output_directory/"models/C.joblib"]
    protected = {str(path): file_digest(path) for path in model_paths}
    protected.update(fleet.dataset.manifest["sources"])
    modules = {str(path.relative_to(SCIENCE)): file_digest(path)
               for root in ("Optimized_Model", "attacks", "mitigation", "eta_baselines")
               for path in (SCIENCE/root).rglob("*.py")}
    modules[str(Path(__file__).relative_to(SCIENCE))] = file_digest(Path(__file__))
    protocol = dict(model_version="vessel_class_v2", seed=args.seed, clock_mode=args.clocks,
        approaches=decisions.approach_id.nunique(), vessels=decisions.mmsi.nunique(),
        decision_clocks=len(decisions), scenarios=cases, protected_hashes=protected,
        implementation_hashes=modules, trusted_fixes=False, drift_direction="under",
        bootstrap_seed=20261023, bootstrap_samples=1000,
        versions={package: version(package) for package in ("numpy","pandas","xgboost","scikit-learn","joblib")})
    run_key = sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()[:16]
    cache = fleet.config.output_directory/"fleet_combination_screen"/run_key
    protocol["run_key"] = run_key
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2))
    (output/"run_snapshot.py").write_bytes(Path(__file__).read_bytes())
    tasks = [(identity, group, cases, str(cache/f"{sha256(identity.encode()).hexdigest()[:16]}.joblib"))
             for identity, group in decisions.groupby("approach_id", sort=True)]
    off, on, audit = [], [], []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                             initargs=(str(config_path), args.seed)) as pool:
        futures = [pool.submit(evaluate_approach, task) for task in tasks]
        for count, future in enumerate(as_completed(futures), 1):
            base, repaired, metadata = future.result()
            off.extend(base); on.extend(repaired); audit.extend(metadata)
            if count % 8 == 0 or count == len(tasks):
                print(f"Prepared {count}/{len(tasks)} approaches in {time.perf_counter()-started:.1f}s", flush=True)
    before, after = prepare_views(off), prepare_views(on)
    keys = ["scenario", "decision_id", "seed"]
    assert not before.duplicated(keys).any() and len(before) == len(decisions)*len(cases)
    protected_columns = [column for column in before if column.startswith("raw_") or column in QUALITY_COLUMNS]
    pd.testing.assert_frame_equal(before[protected_columns], after[protected_columns])
    raw = predict_systems(before, fleet.systems)
    raw["arm"] = raw.system.map({"A":"A", "B":"B", "C":"C_guard"})
    repaired = predict_systems(after, [item for item in fleet.systems if item.name == "C"])
    repaired["arm"] = "Antidote"
    predictions = pd.concat([raw, repaired], ignore_index=True)
    audit_frame = pd.DataFrame(audit)
    summary, pairs = summarize(predictions, audit_frame, cases)
    predictions.to_csv(output/"predictions.csv", index=False)
    audit_frame.to_csv(output/"repair_audit.csv", index=False)
    pairs.sort_values("delta", ascending=False).to_csv(output/"ranked_failures.csv", index=False)
    summary.to_csv(output/"summary.csv", index=False)
    (output/"summary.json").write_text(json.dumps(_json_value(summary.to_dict("records")), indent=2, allow_nan=False))
    (output/"REPORT.md").write_text(render_report(summary, protocol))
    unchanged = all(file_digest(Path(path)) == digest for path,digest in protected.items())
    assert unchanged, "Protected source or model artifact changed during the experiment."
    validation = dict(protected_files_unchanged=unchanged, raw_quality_and_a_b_inputs_unchanged=True,
        causal_received_reports=True, original_labels_preserved=True, unique_case_keys=True,
        cases=len(before), forecasts=len(predictions), elapsed_seconds=time.perf_counter()-started,
        run_key=run_key, current_model_manifests_validated=True)
    (output/"validation.json").write_text(json.dumps(validation, indent=2))
    print(summary[["scenario","C_guard_mae","Antidote_mae","delta_mae","feature_change_fraction","review_fraction"]].to_string(index=False), flush=True)
    print(f"Saved {output}; {len(predictions):,} forecasts in {time.perf_counter()-started:.1f}s", flush=True)


if __name__ == "__main__":
    main()

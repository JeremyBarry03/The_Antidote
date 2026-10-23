"""First-pass existing attacks on frozen 2023 nominal A/B/C, full March test."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import logging
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

from attacks import (MissingSpeedAttack, MissingSpeedConfig, MissingCourseAttack, MissingCourseConfig,
                     MissingVesselClassAttack, MissingVesselClassConfig, ReportingGapAttack, ReportingGapConfig,
                     SensorDriftAttack, SensorDriftConfig, SensorDeteriorationAttack, SensorDeteriorationConfig,
                     PositionJumpAttack, PositionJumpConfig, LocationDriftAttack, LocationDriftConfig)
from eta_baselines.dataset import file_digest
from experiments.prior_model_comparison.run import summarize
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import load_systems, predict_systems, paired_vessel_intervals
from Optimized_Model.features import OptimizedFeatures, OPTIMIZED_COLUMNS, RICH_COLUMNS
from Optimized_Model.model import inference_implementation
from Optimized_Model.views import read_views, view_row

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "artifacts/data_eval/attack_comparison"
SEED = 4201
CASES = ("missing_speed", "missing_course", "missing_vessel_class", "reporting_gap_15",
         "speed_drift_under", "speed_drift_over", "sensor_noise_medium", "position_jump", "location_drift")
logger = logging.getLogger(__name__)


def attack_for(case, first_decision):
    if case == "missing_speed":
        return MissingSpeedAttack(MissingSpeedConfig(.25, SEED))
    if case == "missing_course":
        return MissingCourseAttack(MissingCourseConfig(.25, SEED))
    if case == "missing_vessel_class":
        return MissingVesselClassAttack(MissingVesselClassConfig(.25, SEED))
    if case == "reporting_gap_15":
        start = first_decision + pd.Timedelta(minutes=12)
        return ReportingGapAttack(ReportingGapConfig(start, start + pd.Timedelta(minutes=15)))
    if case in ("speed_drift_under", "speed_drift_over"):
        rate = -.1 if case == "speed_drift_under" else .1
        return SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=rate, seed=SEED))
    if case == "sensor_noise_medium":
        return SensorDeteriorationAttack(SensorDeteriorationConfig.from_severity("medium", seed=SEED))
    if case == "position_jump":
        return PositionJumpAttack(PositionJumpConfig(seed=SEED))
    if case == "location_drift":
        return LocationDriftAttack(LocationDriftConfig(seed=SEED))
    raise ValueError(f"Unknown attack: {case}")


def replay_task(task):
    case, history, decisions, baseline, guard = task
    original = history.copy(deep=True)
    strategy = attack_for(case, decisions["decision_time"].min())
    stream = strategy.apply(history)
    pd.testing.assert_frame_equal(history, original)
    extractor = OptimizedFeatures(baseline, guard)
    rows = []
    for _, decision in decisions.iterrows():
        row = decision.to_dict()
        row.update(view_row(stream.available(decision["decision_time"]), decision, extractor))
        row.update(scenario=case, condition=strategy.condition.value, seed=SEED)
        rows.append(row)
    audit = stream.modification_log.copy()
    audit["approach_id"] = decisions["approach_id"].iloc[0]
    return rows, audit


def score(views, systems):
    result = predict_systems(views, systems)
    result["artifact_system"] = result["system"]
    result["system"] = result["system"].replace({"C_nominal": "C"})
    if (result["available"] & ~np.isfinite(result["error_minutes"])).any():
        raise ValueError("Supported inputs produced invalid predictions")
    return result


def finish_case(predictions, original, name, output, config):
    summary = summarize(predictions, name)
    for index, row in summary.iterrows():
        group = predictions.loc[predictions["system"].eq(row["model"])]
        baseline = original.loc[original["system"].eq(row["model"])]
        if set(group["decision_id"]) != set(baseline["decision_id"]):
            raise ValueError("Attack changed the scheduled evaluation cases")
        matched = baseline.loc[baseline["decision_id"].isin(group.loc[group["available"], "decision_id"])]
        reference = matched["error_minutes"].abs().groupby(matched["approach_id"]).mean().mean()
        summary.loc[index, "paired_original_mae_minutes"] = reference
        summary.loc[index, "mae_change_matched_minutes"] = row["approach_weighted_mae_minutes"] - reference
    predictions.to_csv(output / "predictions.csv", index=False)
    summary.to_csv(output / "summary.csv", index=False)
    paired_vessel_intervals(predictions, config).to_csv(output / "paired_uncertainty.csv", index=False)
    return summary


def write_report(summary, output, protocol):
    lines = ["# Existing attacks: 2023 nominal A/B/C on full March 2024", "",
             "All attacked cases below are **Simulated disruption** of the original March reports. "
             "A/B/C remain frozen, with C explicitly using `C_nominal.joblib`. "
             "No additional mitigation or recalibration is applied. C retains its built-in input guard.", "",
             f"Each setting schedules {protocol['decisions']} decisions across {protocol['approaches']} approaches. "
             "All March 1–31 records eligible for the existing gate/cohort are retained. "
             "Arrival labels and decision clocks come from the original reports, not the attack.", "",
             "## First-pass results", "",
             "| Setting | A MAE / MdAE | B MAE / MdAE | C MAE / MdAE | A/B/C coverage |",
             "|---|---:|---:|---:|---:|"]
    for case, group in summary.groupby("cohort", sort=False):
        cells = [case]
        coverage = []
        for model in ("A", "B", "C"):
            row = group.loc[group["model"].eq(model)].iloc[0]
            cells.append(f"{row.approach_weighted_mae_minutes:.3f} / {row.forecast_mdae_minutes:.3f}")
            coverage.append(f"{row.coverage:.1%}")
        cells.append(" / ".join(coverage))
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(["", "Errors are minutes. MAE gives each approach equal weight; MdAE and P95 "
                  "describe individual available forecasts. `summary.csv` also contains P95, coverage "
                  "and MAE changes against original forecasts on the same supported decisions. "
                  "Unavailable forecasts remain in coverage denominators.", "",
                  "## Settings and limits", "", "```json", json.dumps(protocol["settings"], indent=2), "```", "",
                  "Reporting outage starts 12 minutes after each approach's first scheduled decision "
                  "and lasts 15 minutes, independently of arrival time and prediction errors. "
                  "Unexposed early/short approaches remain in the full-cohort scores. "
                  "Raw modification logs are separate from predictor features.", "",
                  "One fixed attack seed (4201) and one representative setting per attack family "
                  "are a first pass, not an exhaustive severity/seed study. Both speed-drift directions "
                  "are included. Attack settings are reused from existing configs/presets, not tuned "
                  "against March performance. No real-world fault prevalence is inferred.", "",
                  "The models were fitted/tuned only on 2023. C's nominal-only variant was selected "
                  "after inspecting original March performance, so variant selection is post hoc. "
                  "Predictions concern analytical-gate crossings, not verified docking.", "",
                  "## Reproduce", "", "From this worktree's `Data_Science` directory:", "", "```powershell",
                  "& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -u -m experiments.nominal_attack_comparison.run",
                  "```", "", "Outputs, progress and hashed per-case checkpoints: "
                  f"`{output.relative_to(ROOT)}`. Models, source hashes, settings and implementation "
                  "hashes are recorded in `protocol.json`. This command resumes matching verified cases.", ""])
    (output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    if output == DEFAULT_OUTPUT:
        Path(__file__).with_name("RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    parser.add_argument("--limit-approaches", type=int)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    args = parser.parse_args()
    output = args.output.resolve()
    if args.limit_approaches is not None and (args.limit_approaches < 1 or output == DEFAULT_OUTPUT):
        parser.error("A positive approach limit requires a separate --output smoke directory")
    output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(output / "progress.log", encoding="utf-8")])
    status = output / "status.json"
    started = time.perf_counter()
    try:
        config = OptimizedConfig.load(ROOT / "Optimized_Model/config_data_eval.json")
        dataset = load_replay(config)
        decisions = dataset.partition("evaluation")
        if args.limit_approaches:
            ids = decisions["approach_id"].drop_duplicates().iloc[:args.limit_approaches]
            decisions = decisions.loc[decisions["approach_id"].isin(ids)]
        if not decisions["decision_time"].between("2024-03-01", "2024-04-01", inclusive="left").all():
            raise ValueError("Evaluation must be entirely March 2024")
        systems = [system for system in load_systems(config) if system.name in {"A", "B", "C_nominal"}]
        nominal = read_views(config.output_directory / "views/evaluation_nominal.csv")
        nominal = nominal.loc[nominal["decision_id"].isin(decisions["decision_id"])]
        original = score(nominal, systems)
        paths = {"A": config.frozen_baseline_model("quadratic"), "B": config.frozen_baseline_model("xgboost"),
                 "C": config.output_directory / "models/C_nominal.joblib"}
        protocol = {"seed": SEED, "decisions": len(decisions), "approaches": decisions["approach_id"].nunique(),
                    "cases": args.cases, "models": {name: file_digest(path) for name, path in paths.items()},
                    "sources": dataset.manifest["sources"], "inference": inference_implementation(),
                    "implementation": {str(path.relative_to(ROOT)): file_digest(path)
                                       for path in [Path(__file__), ROOT / "Optimized_Model/views.py",
                                                    ROOT / "Optimized_Model/evaluation.py",
                                                    ROOT / "experiments/prior_model_comparison/run.py",
                                                    *(ROOT / "attacks").rglob("*.py")]},
                    "settings": {name: attack_for(name, pd.Timestamp("2024-03-01")).parameters for name in args.cases},
                    "additional_mitigations": False, "test": "March 1-31, 2024"}
        if "reporting_gap_15" in protocol["settings"]:
            protocol["settings"]["reporting_gap_15"] = {
                "start_offset_after_first_decision_minutes": 12, "duration_minutes": 15,
            }
        protocol_path = output / "protocol.json"
        if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
            raise ValueError("Protocol changed; choose a new output directory")
        protocol_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
        summaries = [summarize(original, "original")]
        original.to_csv(output / "original_predictions.csv", index=False)
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for case in args.cases:
                directory = output / case
                directory.mkdir(exist_ok=True)
                checkpoint = directory / "checkpoint.json"
                if checkpoint.exists():
                    saved = json.loads(checkpoint.read_text())
                    if all(file_digest(directory / name) == digest for name, digest in saved.items()):
                        summaries.append(pd.read_csv(directory / "summary.csv"))
                        logger.info("Reusing verified %s", case)
                        continue
                    raise ValueError(f"Completed files changed: {case}")
                logger.info("Starting %s: %s approaches", case, protocol["approaches"])
                status.write_text(json.dumps({"status": "running", "case": case, "prepared": 0,
                                               "approaches": protocol["approaches"]}), encoding="utf-8")
                tasks = [(case, dataset.histories[identity], group, config.baseline, config.guard)
                         for identity, group in decisions.groupby("approach_id", sort=False)]
                rows, audits = [], []
                for index, (batch, audit) in enumerate(pool.map(replay_task, tasks)):
                    rows.extend(batch)
                    audits.append(audit)
                    if (index + 1) % 25 == 0:
                        logger.info("%s: prepared %s/%s approaches", case, index + 1, len(tasks))
                        status.write_text(json.dumps({"status": "running", "case": case, "prepared": index + 1,
                                                       "approaches": len(tasks)}), encoding="utf-8")
                views = pd.DataFrame(rows)
                for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
                    if column not in views:
                        views[column] = np.nan
                for column in ("observation_time", "raw_observation_time"):
                    if column not in views:
                        views[column] = pd.NaT
                predictions = score(views, systems)
                summaries.append(finish_case(predictions, original, case, directory, config))
                pd.concat(audits, ignore_index=True).to_csv(directory / "modifications.csv", index=False)
                files = ("predictions.csv", "summary.csv", "paired_uncertainty.csv", "modifications.csv")
                checkpoint.write_text(json.dumps({name: file_digest(directory / name) for name in files}), encoding="utf-8")
                logger.info("Completed %s", case)
                pd.concat(summaries, ignore_index=True).to_csv(output / "summary.csv", index=False)
        summary = pd.concat(summaries, ignore_index=True)
        write_report(summary, output, protocol)
        status.write_text(json.dumps({"status": "complete", "elapsed_seconds": time.perf_counter() - started}), encoding="utf-8")
        logger.info("All attack comparisons complete")
    except BaseException as error:
        status.write_text(json.dumps({"status": "failed", "error": str(error)}), encoding="utf-8")
        logger.exception("Attack comparison stopped; completed cases retained")
        raise


if __name__ == "__main__":
    awake = None
    if sys.platform == "win32":
        import ctypes

        awake = ctypes.windll.kernel32.SetThreadExecutionState
        awake.argtypes = [ctypes.c_uint]
        awake.restype = ctypes.c_uint
        awake(0x80000001)
    try:
        main()
    finally:
        if awake is not None:
            awake(0x80000000)

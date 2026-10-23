"""Run versioned 2023 retraining and March 2024 evaluation using existing CLIs."""

import argparse
from datetime import date, timedelta
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys

import duckdb
import pandas as pd

from eta_baselines.dataset import file_digest
from eta_baselines.observations import CSV_READ_OPTIONS
from .acquire import COLUMN_MAPPING, acquire, merge_days

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT.parent / "data"
OUTPUT = ROOT / "artifacts" / "data_eval"
BASELINE_CONFIG = ROOT / "config_data_eval.json"
OPTIMIZED_CONFIG = ROOT / "Optimized_Model" / "config_data_eval.json"
SOURCE_START = date(2023, 1, 1)
SOURCE_END = date(2023, 8, 9)  # 220 days, exclusive end.
SOURCE_FILE = "hampton_roads_2023_220days.csv"


def validate_sources() -> dict[str, object]:
    source = DATA / SOURCE_FILE
    manifest = json.loads(source.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    expected = [(SOURCE_START + timedelta(days=index)).isoformat()
                for index in range((SOURCE_END - SOURCE_START).days)]
    if (manifest["start"] != SOURCE_START.isoformat() or manifest["end_exclusive"] != SOURCE_END.isoformat()
            or [item["date"] for item in manifest["days"]] != expected):
        raise ValueError("A complete, ordered 220-day 2023 source is required")
    if file_digest(source) != manifest["merged_sha256"]:
        raise ValueError("2023 source changed since acquisition")
    for day in manifest["days"]:
        path = DATA / "daily_ais_2023" / f"{day['date']}.csv"
        if file_digest(path) != day["subset_sha256"]:
            raise ValueError(f"Daily regional source changed: {path}")
    march = DATA / "hampton_roads_march_2024.csv"
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as connection:
        columns = connection.execute(
            f"DESCRIBE SELECT * FROM read_csv(?, {CSV_READ_OPTIONS})", [str(march)]
        ).fetchdf()["column_name"].tolist()
        if columns != list(COLUMN_MAPPING.values()):
            raise ValueError("2023 normalized columns do not match the March reference")
        count, bad = connection.execute(
            "SELECT COUNT(*), COUNT(*) FILTER (WHERE TRY_CAST(base_date_time AS TIMESTAMP) IS NULL "
            "OR TRY_CAST(base_date_time AS DATE) < DATE '2024-03-01' "
            "OR TRY_CAST(base_date_time AS DATE) >= DATE '2024-04-01') "
            f"FROM read_csv(?, {CSV_READ_OPTIONS})", [str(march)],
        ).fetchone()
        if not count or bad:
            raise ValueError("March evaluation CSV has missing or out-of-period records")
    return {"source_2023_sha256": manifest["merged_sha256"],
            "source_2023_days": len(expected),
            "source_2023_rows": sum(day["subset_rows"] for day in manifest["days"]),
            "parse_rejected_rows_national": sum(day.get("parse_rejected_rows_national", 0) for day in manifest["days"]),
            "march_sha256": file_digest(march), "march_rows": count,
            "baseline_config_sha256": file_digest(BASELINE_CONFIG),
            "optimized_config_sha256": file_digest(OPTIMIZED_CONFIG),
            "april_2024_data_used": False}


def assemble_inputs() -> None:
    directory = DATA / "daily_ais_2023"
    baseline = json.loads(BASELINE_CONFIG.read_text(encoding="utf-8"))
    optimized = json.loads(OPTIMIZED_CONFIG.read_text(encoding="utf-8"))
    first = date.fromisoformat(baseline["splits"]["start"])
    baseline_end = date.fromisoformat(baseline["splits"]["end_exclusive"])
    calibration_start = date.fromisoformat(optimized["calibration_start"])
    if first != SOURCE_START or baseline_end != calibration_start or not baseline_end < SOURCE_END:
        raise ValueError("Baseline and calibration windows must partition the declared source budget")
    days = [first + timedelta(days=index) for index in range((baseline_end - first).days)]
    baseline_source = (BASELINE_CONFIG.parent / baseline["input_csv"]).resolve()
    merge_days(days, directory, baseline_source)
    calibration_days = [calibration_start + timedelta(days=index)
                        for index in range((SOURCE_END - calibration_start).days)]
    destination = (OPTIMIZED_CONFIG.parent / optimized["later_csv"]).resolve()
    merge_days(calibration_days, directory, destination)
    temporary = destination.with_suffix(".csv.partial")
    with temporary.open("wb") as output:
        with destination.open("rb") as source:
            shutil.copyfileobj(source, output, length=1024**2)
        with (DATA / "hampton_roads_march_2024.csv").open("rb") as source:
            source.readline()
            shutil.copyfileobj(source, output, length=1024**2)
    temporary.replace(destination)


def evaluate_nominal(partition: str) -> None:
    """Evaluate original reports once; optional stress sweeps are separate work."""
    from Optimized_Model.calibration import apply_review, fit_calibration, load_calibration, save_review_curves
    from Optimized_Model.configuration import OptimizedConfig
    from Optimized_Model.dataset import load_replay
    from Optimized_Model.evaluation import load_systems, predict_systems, save_evaluation
    from Optimized_Model.replay import Scenario
    from Optimized_Model.views import materialize_views

    config = OptimizedConfig.load(OPTIMIZED_CONFIG)
    dataset = load_replay(config)
    decisions = dataset.partition(partition)
    minimum = (config.review.minimum_evaluation_approaches if partition == "evaluation"
               else config.review.minimum_calibration_approaches)
    if decisions["approach_id"].nunique() < minimum:
        raise ValueError(f"Insufficient approaches for {partition}; do not lower support after seeing results")
    name = f"{partition}_nominal"
    views = materialize_views(dataset, config, partition, [Scenario("nominal")],
                              2042 if partition == "calibration" else 4201, name)
    systems = [system for system in load_systems(config) if system.name in ("A", "B", "C")]
    predictions = predict_systems(views, systems)
    calibration = fit_calibration(predictions, config) if partition == "calibration" else load_calibration(config)
    reviewed = apply_review(predictions, calibration, config)
    save_evaluation(reviewed, config, name)
    save_review_curves(reviewed, config, name)


def write_report() -> Path:
    manifest = json.loads((OUTPUT / "run_manifest.json").read_text(encoding="utf-8"))
    replay = json.loads((OUTPUT / "optimized" / "manifest.json").read_text(encoding="utf-8"))
    path = OUTPUT / "optimized" / "results" / "evaluation_nominal" / "predictions.csv"
    columns = ["system", "scenario", "seed", "approach_id", "mmsi", "available", "error_minutes"]
    selected = []
    for chunk in pd.read_csv(path, usecols=columns, chunksize=100_000, dtype={"mmsi": str}):
        selected.append(chunk.loc[chunk["system"].isin(["A", "B", "C"])])
    predictions = pd.concat(selected, ignore_index=True)
    rows = []
    for (scenario, system), group in predictions.groupby(["scenario", "system"]):
        valid = group.loc[group["available"] & group["error_minutes"].notna()].copy()
        valid["absolute_error"] = valid["error_minutes"].abs()
        rows.append({"scenario": scenario, "model": system,
                     "approaches": group["approach_id"].nunique(), "vessels": group["mmsi"].nunique(),
                     "mae_minutes": float(valid.groupby("approach_id")["absolute_error"].mean().mean()),
                     "median_absolute_error_minutes": float(valid["absolute_error"].median()),
                     "p95_absolute_error_minutes": float(valid["absolute_error"].quantile(.95)),
                     "coverage": len(valid) / len(group)})
    summary = pd.DataFrame(rows)
    summary.to_csv(OUTPUT / "abc_march_summary.csv", index=False)

    def table(frame):
        lines = ["| Model | Approaches | MAE (min) | Median AE (min) | P95 AE (min) | Coverage |",
                 "|---|---:|---:|---:|---:|---:|"]
        for row in frame.itertuples():
            lines.append(f"| {row.model} | {row.approaches} | {row.mae_minutes:.3f} | "
                         f"{row.median_absolute_error_minutes:.3f} | {row.p95_absolute_error_minutes:.3f} | "
                         f"{row.coverage:.1%} |")
        return "\n".join(lines)

    text = ["# 220-day 2023 retraining; March 2024 evaluation", "",
            "A: quadratic ridge regression. B: ordinary XGBoost. C: degradation-aware XGBoost.", "",
            "All 220 declared official NOAA daily point archives (January 1–August 8, 2023) were acquired. "
            f"The regional source contains {manifest['sources']['source_2023_rows']:,} reports.", "",
            f"Malformed national CSV rows quarantined during ingestion: "
            f"{manifest['sources'].get('parse_rejected_rows_national', 0):,}. "
            "Original rejected lines and parser reasons are preserved in daily reject logs. "
            "This national count is not a count of Hampton Roads omissions.", "",
            "January 1–June 29, 2023: fit (180 days); June 30–July 19: hyperparameter selection (20 days); "
            "July 20–29: internal check (10 days); July 30–August 8: calibration (10 days). "
            "Entire March 2024: evaluation. April 2024 data were not used. "
            "Boundary-spanning approaches are purged. March was used in earlier project runs, "
            "so this is a held-out comparison for these new fits, not a previously unseen research dataset.", "",
            "## Original March reports", "", table(summary.loc[summary["scenario"] == "nominal"]), "",
            "MAE gives each approach equal weight. Median and P95 describe individual forecasts. "
            "Coverage includes unavailable scheduled forecasts; interval-based deferral is reported separately.", "",
            "## Training augmentation", "",
            "C retains its established four-condition training mixture. Added delivery delays and "
            "position offsets are simulated disruption applied only to training/development views. "
            "July 30–August 8 calibration and March evaluation use original reports without injected faults. "
            "Instant nominal delivery remains an assumption because source delivery timestamps are unavailable. "
            "No robustness gain under simulated faults is claimed by this nominal evaluation.", ""]
    text.extend(["## Cohort and artifacts", "", "```json",
                 json.dumps(replay["split_counts"], indent=2), "```", "",
                 "Arrival means an interpolated east-to-west crossing of the existing analytical gate, "
                 "not docking. Results are conditional on qualifying observed cargo/tanker crossings. "
                 "Repeated vessels may occur across periods; MMSI is not a model feature.", "",
                 "The supplied GeoPackage has 7,596,268 untimed track segments and was audited, "
                 "not converted into fabricated reports. See `compatibility_report.json`.", "",
                 "Models and detailed predictions are under `artifacts/data_eval/`. "
                 "See `optimized/results/evaluation_nominal/` for paired vessel uncertainty, "
                 "per-vessel errors, coverage and calibration/deferral diagnostics. "
                 "The three additional fitted C controls support internal attribution only.", "",
                 "Source: https://www.coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/index.html", ""])
    destination = Path(__file__).with_name("RESULTS.md")
    destination.write_text("\n".join(text), encoding="utf-8")
    return destination


def run() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sources = validate_sources()
    code = {}
    for directory in ("eta_baselines", "Optimized_Model", "Simple_baseline", "XGBoost_Model", "experiments/data_eval"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            code[str(path.relative_to(ROOT))] = file_digest(path)
    state_path = OUTPUT / "run_manifest.json"
    state = {"sources": sources, "implementation": code, "completed_stages": [], "status": "running"}
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["sources"] != sources or state["implementation"] != code:
            raise ValueError("Source/config/code changed during this versioned run; review before restarting")
    commands = [
        ("assemble", None),
        ("baselines", ["eta_baselines", "all", "--config", str(BASELINE_CONFIG)]),
        ("replay", ["Optimized_Model", "prepare", "--config", str(OPTIMIZED_CONFIG)]),
        ("optimized", ["Optimized_Model", "train", "--config", str(OPTIMIZED_CONFIG)]),
        ("calibrate", None),
        ("evaluate", None),
        ("report", None),
    ]
    try:
        for name, command in commands:
            if name in state["completed_stages"]:
                logger.info("Reusing completed stage: %s", name)
                continue
            logger.info("Starting stage: %s", name)
            state.update(status="running", current_stage=name)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            if name == "assemble":
                assemble_inputs()
            elif name == "report":
                write_report()
            elif name in ("calibrate", "evaluate"):
                evaluate_nominal("calibration" if name == "calibrate" else "evaluation")
            else:
                arguments = [sys.executable, "-u", "-m", *command]
                with subprocess.Popen(arguments, cwd=ROOT, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True) as process:
                    with (OUTPUT / "pipeline.log").open("a", encoding="utf-8") as log:
                        for line in process.stdout:
                            print(line, end="", flush=True)
                            log.write(line)
                            log.flush()
                    if process.wait():
                        raise subprocess.CalledProcessError(process.returncode, arguments)
            state["completed_stages"].append(name)
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        state.update(status="complete", current_stage=None)
        state.pop("error", None)
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquire", action="store_true", help="Acquire/resume the declared 220 days before training")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(OUTPUT / "pipeline.log", encoding="utf-8")])
    status = OUTPUT / "job_status.json"
    awake_api = None
    if sys.platform == "win32":
        import ctypes

        awake_api = ctypes.windll.kernel32.SetThreadExecutionState
        awake_api.argtypes = [ctypes.c_uint]
        awake_api.restype = ctypes.c_uint
        if not awake_api(0x80000001):  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED; display may turn off.
            logger.warning("Could not inhibit automatic system sleep during this run")
    try:
        if args.acquire:
            status.write_text(json.dumps({"status": "acquiring", "workers": args.workers}), encoding="utf-8")
            acquire(DATA / SOURCE_FILE, SOURCE_START, SOURCE_END, args.workers)
        status.write_text(json.dumps({"status": "training_pipeline"}), encoding="utf-8")
        run()
        status.write_text(json.dumps({"status": "complete", "report": str(Path(__file__).with_name("RESULTS.md"))}), encoding="utf-8")
        logger.info("A/B/C retraining and March evaluation complete")
    except BaseException as error:
        status.write_text(json.dumps({"status": "failed", "error": str(error)}), encoding="utf-8")
        logger.exception("Pipeline stopped; verified daily subsets and completed stages are retained")
        raise
    finally:
        if awake_api is not None:
            awake_api(0x80000000)  # Clear this thread's temporary sleep request.


if __name__ == "__main__":
    main()

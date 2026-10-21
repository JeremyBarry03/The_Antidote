"""Paired inference-only Gaussian-noise experiment on frozen corrected A/B/C."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
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

from attacks import SensorDeteriorationAttack, SensorDeteriorationConfig
from attacks.sensorDeteriorationAttack import SEVERITY_LEVELS
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS
from experiments.missing_speed_attack.run import metrics, paired_interval
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import PredictionSystem, load_systems, predict_systems
from Optimized_Model.features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from Optimized_Model.views import view_row

SEEDS = (4201, 4202, 4203)


def replay_case(task: tuple) -> tuple[list[dict], pd.DataFrame]:
    """Use the serving feature path, keeping injection truth out of its inputs."""
    history, decisions, config, settings, scenario = task
    extractor = OptimizedFeatures(config.baseline, config.guard)
    original = history.copy(deep=True)
    stream = SensorDeteriorationAttack(settings).apply(history)
    untouched = list(history.columns.drop(["sog", "cog"]))
    pd.testing.assert_frame_equal(stream.reports[untouched], history[untouched])
    pd.testing.assert_frame_equal(stream.reports[["sog", "cog"]].isna(), history[["sog", "cog"]].isna())
    pd.testing.assert_frame_equal(history, original)
    rows = []
    for _, decision in decisions.iterrows():
        received = stream.available(decision.decision_time)
        assert received.time.le(decision.decision_time).all()
        assert received.delivered_time.le(decision.decision_time).all()
        row = decision.to_dict()
        row.update(view_row(received, decision, extractor))
        row.update(scenario=scenario, condition="nominal" if scenario == "original" else "quality", seed=settings.seed)
        rows.append(row)
    audit = stream.modification_log.copy()
    audit["approach_id"], audit["scenario"] = decisions.approach_id.iloc[0], scenario
    return rows, audit


def summarize(frame: pd.DataFrame) -> dict:
    """Retain unavailable decisions and compare errors on identical support."""
    row = {key: frame[key].iloc[0] for key in ("system", "severity", "mode", "affected_fraction", "scenario")}
    row.update(metrics(frame))
    matched = frame.loc[frame.available & frame.original_error_minutes.notna()]
    row["paired_decisions"] = len(matched)
    baseline = metrics(matched, "original_error_minutes") if len(matched) else {}
    attacked = metrics(matched) if len(matched) else {}
    row.update(original_mae_minutes=baseline.get("mae_minutes", np.nan),
               original_mdae_minutes=baseline.get("mdae_minutes", np.nan),
               mae_change_minutes=attacked.get("mae_minutes", np.nan)-baseline.get("mae_minutes", np.nan),
               mdae_change_minutes=attacked.get("mdae_minutes", np.nan)-baseline.get("mdae_minutes", np.nan),
               realizations=int(frame.seed.nunique()))
    if len(matched):
        row["mae_change_ci_low"], row["mae_change_ci_high"] = paired_interval(matched)
    else:
        row["mae_change_ci_low"], row["mae_change_ci_high"] = np.nan, np.nan
    return row


def render_report(summary: pd.DataFrame, validation: dict, c_status: str) -> str:
    lines = ["# SensorDeteriorationAttack: frozen-model robustness", "",
        "Simulated Gaussian corruption of original reported SOG and COG. Original measurements are references, not independently verified physical truth. Sigma settings are experimental, not measured real-world failure rates.", "",
        "SOG = max(0, original + Gaussian noise); no artificial upper cap. COG = (original + independent Gaussian noise) modulo 360. Existing missing/invalid values stay unchanged. Selection precedes both independent noise draws and is stable by vessel/timestamp/seed. Every row, coordinate, class, clock and crossing target is preserved.", "",
        f"112 April approaches / 110 vessels / 2,402 decision times. {c_status} No retraining, recalibration, or new mitigation. C retains its existing guard and feature processing.", "",
        "MAE weights each approach equally, averaging scenario seeds within approaches. MdAE and P95 pool absolute errors over decision/seed pairs. Changes use paired supported decisions. Coverage includes every scheduled decision; missing predictions are not scored as zero error. Values are minutes to the analytical reference crossing, not docking.", "",
        "| Setting | Mode | Selected fraction | Model | MAE | MdAE | Δ MAE | Δ MdAE | P95 | Coverage |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        lines.append(f"| {row.severity} | {row.mode} | {row.affected_fraction:.0%} | {row.system} | {row.mae_minutes:.4f} | {row.mdae_minutes:.4f} | {row.mae_change_minutes:+.4f} | {row.mdae_change_minutes:+.4f} | {row.p95_error_minutes:.4f} | {row.coverage:.2%} |")
    lines += ["", "Low = 0.5 kn / 2°; Medium = 1 kn / 5°; High = 2 kn / 10°; Extreme = 4 kn / 20°. Sigma zero disables a measurement. Default completed matrix: all four severities, combined mode, 100% of eligible reports, seeds 4201–4203. These vary corruption, not training. Actual selected fraction can differ in partial-selection runs because selection uses independent identity hashes.", "",
        "Per-seed results, full predictions and separate report audit are locally ignored CSVs. Summary CSV includes 1,000-draw paired vessel-cluster bootstrap intervals for MAE changes. Labels/audit truth never enter predictor feature lists. Source/model hashes are checked before and after.", "",
        "April was previously inspected; this is a follow-up robustness experiment, not a pristine holdout. Noise may worsen, improve or leave individual forecasts unchanged. These results do not establish naturally occurring sensor failures in the source data.", "",
        f"Completed {validation['configurations']} attacked configurations; {validation['predictions']:,} model forecasts including originals. Protected hashes unchanged: {validation['protected_hashes_unchanged']}.", "",
        "Reproduce from Data_Science: `python experiments/sensor_deterioration_attack/run.py`.",
        "Optional expanded matrix: `--modes sog cog both --fractions 0.1 0.25 0.5 1`. Use `--output` to preserve the default report."]
    return "\n".join(lines)+"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modes", nargs="+", choices=["sog", "cog", "both"], default=["both"])
    parser.add_argument("--fractions", type=float, nargs="+", default=[1.])
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--output", type=Path, default=HERE/"results")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    for fraction in args.fractions:
        SensorDeteriorationConfig(affected_fraction=fraction)
    started = time.perf_counter()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/"Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    if len(decisions) != 2402 or decisions.approach_id.nunique() != 112:
        raise ValueError("Expected the existing 112-approach / 2,402-decision cohort.")
    try:
        systems = [s for s in load_systems(config) if s.name in ("A", "B", "C")]
        c_status = "Models A, B and C loaded through artifact/hash compatibility checks."
    except (FileNotFoundError, ValueError) as error:
        systems = [PredictionSystem(name, joblib.load(config.frozen_baseline_model(model)), "raw")
                   for name, model in (("A", "quadratic"), ("B", "xgboost"))]
        c_status = f"Model C could not be evaluated: {error}"
    if any(tuple(s.predictor.feature_columns) != FEATURE_COLUMNS for s in systems if s.name in ("A", "B")):
        raise ValueError("A/B must use corrected vessel-class features.")
    model_paths = {name: config.frozen_baseline_model(model) for name, model in (("A", "quadratic"), ("B", "xgboost"))}
    if any(s.name == "C" for s in systems):
        model_paths["C"] = config.output_directory/"models/C.joblib"
    protected = {**model_paths, "March": config.baseline.input_csv, "April": config.later_csv,
                 "baseline_training": SCIENCE/"eta_baselines/training.py",
                 "optimized_training": SCIENCE/"Optimized_Model/model.py",
                 "base_features": SCIENCE/"eta_baselines/features.py",
                 "C_features": SCIENCE/"Optimized_Model/features.py"}
    hashes = {name: file_digest(path) for name, path in protected.items()}
    protocol = dict(attack=SensorDeteriorationAttack.name, simulation=True, severities=dict(SEVERITY_LEVELS),
        modes=args.modes, fractions=args.fractions, seeds=SEEDS, trained_models=[s.name for s in systems],
        model_C_status=c_status, protected_paths={k: str(p) for k, p in protected.items()}, protected_hashes=hashes,
        cohort="Same original April 8-21 approaches, clocks and interpolated analytical crossing labels",
        original_measurements="Reference only; physical truth not independently verified",
        selection="Identity hash threshold before noise; same report set for both enabled fields",
        noise="Two independent standard normal draws per vessel/timestamp/seed, scaled by sigma",
        speed_bounds="Lower bound zero only; original invalid/SOG 102.3 sentinel preserved",
        training="None", calibration="None", mitigation="Existing model C processing only",
        MAE="Equal approach weights; realizations averaged within approach", MdAE="Pooled prediction-seed median",
        changes="Same supported decision pairs", bootstrap="1000 vessel-cluster draws; seed 20261021")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    cases = [(dataset.histories[key].sort_values("time", kind="stable").reset_index(drop=True), group)
             for key, group in decisions.groupby("approach_id", sort=False)]
    configurations = [("original", "none", 0., SensorDeteriorationConfig(0, 0, seed=42))]
    for level in SEVERITY_LEVELS:
        for mode in dict.fromkeys(args.modes):
            for fraction in dict.fromkeys(args.fractions):
                for seed in SEEDS:
                    settings = SensorDeteriorationConfig.from_severity(level, affected_fraction=fraction, seed=seed)
                    if mode == "sog":
                        settings = replace(settings, cog_sigma_degrees=0)
                    if mode == "cog":
                        settings = replace(settings, sog_sigma_knots=0)
                    configurations.append((level, mode, fraction, settings))
    predictions, exposures = [], []
    references = {}
    nominal_identity = None
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, (level, mode, fraction, settings) in enumerate(configurations):
            scenario = "original" if level == "original" else f"{level}_{mode}_{fraction:g}"
            tasks = [(history, group, config, settings, scenario) for history, group in cases]
            rows, audits = [], []
            for case_rows, audit in pool.map(replay_case, tasks):
                rows.extend(case_rows)
                audits.append(audit)
            views = pd.DataFrame(rows)
            for column in (*OPTIMIZED_COLUMNS, *(f"raw_{c}" for c in RICH_COLUMNS)):
                if column not in views:
                    views[column] = np.nan
            for column in ("observation_time", "raw_observation_time"):
                if column not in views:
                    views[column] = pd.NaT
            identities = views[["decision_id", "decision_time", "arrival_time", "mmsi", "approach_id"]]
            if nominal_identity is None:
                nominal_identity = identities.copy()
            else:
                pd.testing.assert_frame_equal(identities, nominal_identity)
            assert not {"fault_applied", "original_sog", "original_cog", "selected"} & set(views.columns)
            result = predict_systems(views, systems)
            for name, group in result.groupby("system"):
                if level == "original":
                    references[name] = group.set_index("decision_id").error_minutes
                result.loc[group.index, "original_error_minutes"] = group.decision_id.map(references[name])
            result["absolute_error_change"] = result.error_minutes.abs()-result.original_error_minutes.abs()
            result["severity"], result["mode"], result["affected_fraction"] = level, mode, fraction
            result["sog_sigma_knots"], result["cog_sigma_degrees"] = settings.sog_sigma_knots, settings.cog_sigma_degrees
            if (result.available & ~np.isfinite(result.error_minutes)).any():
                raise ValueError("Supported predictions must be finite.")
            predictions.append(result)
            audit_frame = pd.concat(audits, ignore_index=True)
            audit_frame.to_csv(output/"report_audit.csv", mode="w" if index == 0 else "a", header=index == 0, index=False)
            exposures.append(dict(severity=level, mode=mode, affected_fraction=fraction, seed=settings.seed,
                reports=len(audit_frame), selected=int(audit_frame.selected.sum()),
                changed=int(audit_frame.fault_applied.sum()), speed_clipped=int(audit_frame.sog_clipped.sum()),
                course_wrapped=int(audit_frame.cog_wrapped.sum())))
            print(f"{index+1}/{len(configurations)} {scenario} seed {settings.seed}: {len(result):,} A/B/C scheduled forecasts", flush=True)
    results = pd.concat(predictions, ignore_index=True)
    results.to_csv(output/"predictions.csv", index=False)
    pd.DataFrame(exposures).to_csv(output/"injection_audit.csv", index=False)
    keys = ["system", "severity", "mode", "affected_fraction"]
    summary = pd.DataFrame([summarize(g) for _, g in results.groupby(keys, sort=False)])
    summary.to_csv(output/"summary.csv", index=False)
    pd.DataFrame([dict(seed=g.seed.iloc[0], **summarize(g)) for _, g in results.groupby(keys+["seed"], sort=False)]).to_csv(
        output/"per_seed_summary.csv", index=False)
    for name, path in protected.items():
        if file_digest(path) != hashes[name]:
            raise ValueError(f"Protected source/model changed: {name}")
    validation = dict(approaches=112, vessels=int(decisions.mmsi.nunique()), unique_decisions=2402,
        models=[s.name for s in systems], configurations=len(configurations)-1, predictions=len(results),
        protected_hashes_unchanged=True, all_source_rows_and_unrelated_fields_preserved=True,
        missingness_preserved=True, original_clocks_and_reference_targets_preserved=True,
        causal_serving_feature_path_used=True, audit_truth_excluded_from_features=True,
        minimum_forecast_coverage=float(summary.coverage.min()), elapsed_seconds=time.perf_counter()-started)
    (output/"validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (output/"REPORT.md").write_text(render_report(summary, validation, c_status), encoding="utf-8")
    print(f"Completed in {validation['elapsed_seconds']:.1f}s. Report: {output/'REPORT.md'}", flush=True)


if __name__ == "__main__":
    main()

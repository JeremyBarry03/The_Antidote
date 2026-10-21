"""Frozen A/B/C robustness to simulated position jumps, with matched original feeds."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0,str(SCIENCE))

from attacks import PositionJumpAttack, PositionJumpConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS
from experiments.sensor_deterioration_attack.run import summarize
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.evaluation import PredictionSystem, load_systems, predict_systems
from Optimized_Model.features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from Optimized_Model.views import view_row

FRACTIONS = (.1,.2,.25,.5,1.)
SEEDS = (4201,4202,4203)


def replay_case(task: tuple) -> tuple[list[dict],pd.DataFrame]:
    history,decisions,config,settings,scenario,window_start,window_duration = task
    if window_start is not None:
        start = history.time.min()+pd.Timedelta(minutes=window_start)
        settings = replace(settings,start_time=start,end_time=start+pd.Timedelta(minutes=window_duration))
    original = history.copy(deep=True)
    stream = PositionJumpAttack(settings).apply(history)
    other = list(history.columns.drop(["latitude","longitude"]))
    pd.testing.assert_frame_equal(stream.reports[other],history[other])
    pd.testing.assert_frame_equal(stream.reports[["latitude","longitude"]].isna(),history[["latitude","longitude"]].isna())
    pd.testing.assert_frame_equal(history,original)
    extractor = OptimizedFeatures(config.baseline,config.guard)
    rows = []
    for _,decision in decisions.iterrows():
        received = stream.available(decision.decision_time)
        if not received.time.le(decision.decision_time).all() or not received.delivered_time.le(decision.decision_time).all():
            raise ValueError("Future reports cannot enter inference.")
        row = decision.to_dict()
        row.update(view_row(received,decision,extractor))
        row.update(scenario=scenario,condition="nominal" if scenario=="original" else "quality",seed=settings.seed)
        rows.append(row)
    audit = stream.modification_log.copy()
    audit["approach_id"],audit["scenario"] = decisions.approach_id.iloc[0],scenario
    return rows,audit


def render_report(summary: pd.DataFrame,validation: dict,protocol: dict) -> str:
    lines = ["# PositionJumpAttack: frozen A/B/C robustness", "",
        "Simulated corruption of copied AIS latitude/longitude. Original reported coordinates are references, not independently verified physical truth. The pattern is motivated by original jump-and-return inconsistencies; the underlying GPS/identity/timing/processing cause was not established.", "",
        "Percentages select eligible reports using the existing seed/vessel/timestamp hash threshold. Requested percentages are not exact-count quotas. A reproducible bearing per MMSI displaces selected fixes; unselected fixes retain their original positions. At 100% the whole supplied feed/window is displaced, with no intervening correct fixes inside it. The Python/API window is half-open [start,end). No reports are removed. Speed, course, classification, identity, timing, decision schedule and original crossing targets stay unchanged.", "",
        f"The cohort contains {validation['approaches']} April approaches / {validation['vessels']} vessels / {validation['unique_decisions']:,} decision times. {protocol['model_C_status']} No retraining, recalibration or new mitigation. C retains its existing guard.", "",
        f"Completed settings (mean meters, fraction): {protocol['settings']}. Each attacked setting uses seeds 4201–4203 to vary selection, bearing and report distances, not model training. Main prevalence comparison holds mean displacement at {protocol['primary_displacement_meters']:g} meters. Distance standard deviation: {protocol['displacement_std_meters']:g} meters. Additional means, if requested, are compared at 25%. All are stress settings; observed severe source jumps were much rarer than these injected percentages.", "",
        "Distances are independent normal draws per vessel/timestamp identity, clipped to [0, half Earth's circumference]. Sigma zero reproduces fixed distances. Duplicate identities share a draw; sampling order, future reports and percentage do not change it. The clipping is audited separately. The seed/identity namespace for distance is separate from report selection and vessel bearing.", "",
        f"Window: {protocol['window_policy']}", "",
        "MAE weights approaches equally, averaging scenario realizations within each approach. MdAE and P95 pool absolute errors over decision/seed pairs. Changes compare identical supported original/attacked decisions. Coverage retains every scheduled decision in the denominator. Units are minutes to the analytical crossing, not docking.", "",
        "| Mean displacement | Selected fraction | Model | MAE | MdAE | Δ MAE | Δ MdAE | P95 | Coverage |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary.itertuples():
        label = "Original" if row.displacement_meters==0 else f"{row.displacement_meters/1000:g} km"
        lines.append(f"| {label} | {row.affected_fraction:.0%} | {row.system} | {row.mae_minutes:.4f} | {row.mdae_minutes:.4f} | {row.mae_change_minutes:+.4f} | {row.mdae_change_minutes:+.4f} | {row.p95_error_minutes:.4f} | {row.coverage:.2%} |")
    lines += ["", "CSV outputs include all predictions, per-seed summaries, displacement/selection audit and 1,000-draw paired vessel-cluster MAE-change intervals. CSVs remain locally ignored. Hashes of source data, frozen models and existing inference/training code are checked before and after. Audience-only injection truth is never fed to the predictors.", "",
        "Model histories and analytical crossing labels are never rebuilt from corrupted coordinates, even if an injected fix appears across the gate. The original 112-approach cohort did not include the severe jump endpoints identified by the location audit. This experiment tests a simulated failure pattern on that cohort; it does not attribute its original ETA errors to those source anomalies. April has been inspected previously and is not a pristine holdout.", "",
        f"Completed {validation['configurations']} attacked configurations and {validation['predictions']:,} model forecasts including originals. Minimum forecast coverage: {validation['minimum_forecast_coverage']:.2%}. Protected hashes unchanged: {validation['protected_hashes_unchanged']}.", "",
        "Reproduce from Data_Science: `python experiments/position_jump_attack/run.py`.",
        "Optional timed run: `--window-start-minutes 20 --window-duration-minutes 15 --output artifacts/position_jump_window`. Other settings are listed by `--help`."]
    return "\n".join(lines)+"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fractions",type=float,nargs="+",default=FRACTIONS)
    parser.add_argument("--displacement-meters",type=float,default=2000.)
    parser.add_argument("--displacement-std-meters",type=float,default=200.)
    parser.add_argument("--severity-distances",type=float,nargs="*",default=[])
    parser.add_argument("--window-start-minutes",type=float)
    parser.add_argument("--window-duration-minutes",type=float,default=15.)
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--output",type=Path,default=HERE/"results/normal_distance")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    if (not math.isfinite(args.window_duration_minutes) or args.window_duration_minutes<=0
            or (args.window_start_minutes is not None and
                (not math.isfinite(args.window_start_minutes) or args.window_start_minutes<0))):
        parser.error("Window offset must be finite/nonnegative and duration finite/positive.")
    settings = list(dict.fromkeys([(args.displacement_meters,f) for f in args.fractions]
                                 + [(distance,.25) for distance in args.severity_distances]))
    for distance,fraction in settings:
        PositionJumpConfig(distance,fraction,displacement_std_meters=args.displacement_std_meters)
    started = time.perf_counter()
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/"Optimized_Model/config_vessel_class_v2.json")
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id","decision_time"])
    if len(decisions)!=2402 or decisions.approach_id.nunique()!=112:
        raise ValueError("Expected the existing 112-approach / 2,402-decision cohort.")
    try:
        systems = [system for system in load_systems(config) if system.name in ("A","B","C")]
        c_status = "A/B/C saved artifacts passed their compatibility/hash checks."
    except (ValueError,FileNotFoundError) as error:
        systems = [PredictionSystem(name,joblib.load(config.frozen_baseline_model(model)),"raw")
                   for name,model in (("A","quadratic"),("B","xgboost"))]
        c_status = f"Model C was not evaluated: {error}"
    if any(tuple(system.predictor.feature_columns)!=FEATURE_COLUMNS for system in systems if system.name in ("A","B")):
        raise ValueError("Corrected frozen A/B artifacts are required.")
    paths = {name:config.frozen_baseline_model(model) for name,model in (("A","quadratic"),("B","xgboost"))}
    if any(system.name=="C" for system in systems):
        paths["C"] = config.output_directory/"models/C.joblib"
    protected = {**paths,"March":config.baseline.input_csv,"April":config.later_csv,
        **{name:SCIENCE/name for name in ("eta_baselines/features.py","eta_baselines/prediction.py",
            "Optimized_Model/features.py","Optimized_Model/quality.py","Optimized_Model/replay.py",
            "eta_baselines/training.py","Optimized_Model/model.py")}}
    hashes = {name:file_digest(path) for name,path in protected.items()}
    protocol = dict(attack=PositionJumpAttack.name,simulation=True,settings=settings,seeds=SEEDS,
        primary_displacement_meters=args.displacement_meters,model_C_status=c_status,
        displacement_std_meters=args.displacement_std_meters,
        defaults=PositionJumpAttack().parameters,models=[system.name for system in systems],
        protected_paths={name:str(path) for name,path in protected.items()},protected_hashes=hashes,
        selection="Existing report-identity hash; percentage of eligible reports, not approaches",
        displacement="Spherical forward geodesic, with one identity-seeded bearing per MMSI; independent identity-seeded normal distance per report, clipped to [0, half Earth's circumference]",
        window_policy=("Whole supplied approach feed" if args.window_start_minutes is None else
            f"[{args.window_start_minutes:g}, {args.window_start_minutes+args.window_duration_minutes:g}) minutes after each approach's earliest supplied report"),
        labels="Original analytical crossing references, never derived from corrupted positions",
        training="None",new_mitigation="None; existing model C preprocessing retained",
        MAE="Equal approach weights",MdAE="Pooled absolute-error median",changes="Same supported decision pairs")
    (output/"protocol.json").write_text(json.dumps(protocol,indent=2),encoding="utf-8")
    cases = [(dataset.histories[key].sort_values("time",kind="stable").reset_index(drop=True),group)
             for key,group in decisions.groupby("approach_id",sort=False)]
    configurations = [(0.,0.,42)]+[(distance,fraction,seed) for distance,fraction in settings for seed in SEEDS]
    predictions,exposure = [],[]
    references = {}
    nominal = None
    invariant_columns = [f"raw_{column}" for column in FEATURE_COLUMNS
                         if column not in ("east_meters","north_meters","mean_east_meters")]
    invariant_columns += ["approach_id","mmsi","decision_id","decision_time","arrival_time","raw_observation_time"]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index,(distance,fraction,seed) in enumerate(configurations):
            original = index==0
            scenario = "original" if original else f"jump_{distance:g}m_sd{args.displacement_std_meters:g}m_{fraction:g}"
            attack_config = PositionJumpConfig(distance,fraction,seed,
                displacement_std_meters=0. if original else args.displacement_std_meters)
            tasks = [(history,group,config,attack_config,scenario,args.window_start_minutes,args.window_duration_minutes)
                     for history,group in cases]
            rows,audits = [],[]
            for case_rows,audit in pool.map(replay_case,tasks):
                rows.extend(case_rows)
                audits.append(audit)
            views = pd.DataFrame(rows)
            for column in (*OPTIMIZED_COLUMNS,*(f"raw_{c}" for c in RICH_COLUMNS)):
                if column not in views:
                    views[column] = np.nan
            for column in ("observation_time","raw_observation_time"):
                if column not in views:
                    views[column] = pd.NaT
            if nominal is None:
                nominal = views[invariant_columns].copy()
            else:
                pd.testing.assert_frame_equal(views[invariant_columns],nominal)
            if {"fault_applied","original_longitude","original_latitude","selected"} & set(views):
                raise ValueError("Injection truth cannot enter the feature table.")
            result = predict_systems(views,systems)
            for name,group in result.groupby("system"):
                if original:
                    references[name] = group.set_index("decision_id").error_minutes
                result.loc[group.index,"original_error_minutes"] = group.decision_id.map(references[name])
            result["absolute_error_change"] = result.error_minutes.abs()-result.original_error_minutes.abs()
            result["severity"],result["displacement_meters"] = "original" if original else f"{distance:g}m",distance
            result["displacement_std_meters"] = attack_config.displacement_std_meters
            result["mode"] = "whole_feed" if args.window_start_minutes is None else "window"
            result["affected_fraction"] = fraction
            if (result.available & ~np.isfinite(result.error_minutes)).any():
                raise ValueError("Supported predictions must be finite.")
            predictions.append(result)
            audit_frame = pd.concat(audits,ignore_index=True)
            audit_frame.to_csv(output/"report_audit.csv",mode="w" if original else "a",header=original,index=False)
            exposure.append(dict(displacement_meters=distance,affected_fraction=fraction,seed=seed,
                displacement_std_meters=attack_config.displacement_std_meters,
                reports=len(audit_frame),eligible_reports=int(audit_frame.eligible_position.sum()),
                in_window=int(audit_frame.in_window.sum()),selected_reports=int(audit_frame.selected.sum()),
                changed_reports=int(audit_frame.fault_applied.sum()),
                clipped_distances=int(audit_frame.distance_clipped.sum()),
                mean_applied_displacement_meters=float(audit_frame.loc[audit_frame.selected,"applied_displacement_meters"].mean()) if audit_frame.selected.any() else 0.,
                std_applied_displacement_meters=float(audit_frame.loc[audit_frame.selected,"applied_displacement_meters"].std()) if audit_frame.selected.sum()>1 else 0.,
                maximum_applied_displacement_meters=float(audit_frame.applied_displacement_meters.max())))
            print(f"{index+1}/{len(configurations)} {scenario} seed {seed}: {len(result):,} scheduled forecasts",flush=True)
    results = pd.concat(predictions,ignore_index=True)
    results.to_csv(output/"predictions.csv",index=False)
    pd.DataFrame(exposure).to_csv(output/"injection_audit.csv",index=False)
    keys = ["system","displacement_meters","displacement_std_meters","affected_fraction"]
    summary = pd.DataFrame([dict(displacement_meters=group.displacement_meters.iloc[0],
        displacement_std_meters=group.displacement_std_meters.iloc[0],**summarize(group))
                            for _,group in results.groupby(keys,sort=False)])
    summary.to_csv(output/"summary.csv",index=False)
    pd.DataFrame([dict(seed=group.seed.iloc[0],displacement_meters=group.displacement_meters.iloc[0],
        displacement_std_meters=group.displacement_std_meters.iloc[0],**summarize(group))
        for _,group in results.groupby(keys+["seed"],sort=False)]).to_csv(output/"per_seed_summary.csv",index=False)
    for name,path in protected.items():
        if file_digest(path)!=hashes[name]:
            raise ValueError(f"Protected source/model/code changed: {name}")
    validation = dict(approaches=112,vessels=int(decisions.mmsi.nunique()),unique_decisions=2402,
        configurations=len(configurations)-1,predictions=len(results),models=[s.name for s in systems],
        protected_hashes_unchanged=True,all_rows_and_non_position_fields_preserved=True,
        missing_coordinate_pattern_preserved=True,original_clocks_and_crossing_labels_preserved=True,
        raw_non_position_features_unchanged=True,audit_truth_excluded_from_features=True,
        minimum_forecast_coverage=float(summary.coverage.min()),elapsed_seconds=time.perf_counter()-started)
    (output/"validation.json").write_text(json.dumps(validation,indent=2),encoding="utf-8")
    (output/"REPORT.md").write_text(render_report(summary,validation,protocol),encoding="utf-8")
    print(f"Completed in {validation['elapsed_seconds']:.1f}s. Report: {output/'REPORT.md'}",flush=True)


if __name__ == "__main__":
    main()

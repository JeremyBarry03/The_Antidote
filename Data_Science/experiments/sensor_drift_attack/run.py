"""Evaluate automatic speed-sensor drift using corrected, frozen A/B models."""

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

from attacks import SensorDriftAttack, SensorDriftConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS, FeatureBuilder
from eta_baselines.prediction import EtaPredictor
from experiments.missing_speed_attack.run import metrics, paired_interval, snapshot
from Optimized_Model.configuration import OptimizedConfig

from Optimized_Model.dataset import load_replay

RATES = (-.025, -.05, -.1, .025, .05, .1)
SEEDS = (4201, 4202, 4203)


def score(predictor: EtaPredictor, inputs: pd.DataFrame, reference: pd.Series | None,
          system: str, rate: float, seed: int) -> pd.DataFrame:
    predicted = predictor.predict(inputs)
    frame = predicted[["approach_id", "mmsi", "decision_id", "decision_time", "observation_time",
        "arrival_time", "predicted_arrival_time", "predicted_remaining_minutes", "report_age_minutes",
        "error_minutes"]].copy()
    frame["system"], frame["attack"] = system, SensorDriftAttack.name
    frame["drift_rate_knots_per_minute"], frame["seed"] = rate, seed
    frame["original_error_minutes"] = (frame.error_minutes if reference is None else frame.decision_id.map(reference))
    frame["absolute_error_change"] = frame.error_minutes.abs()-frame.original_error_minutes.abs()
    if not np.isfinite(frame.error_minutes).all():
        raise ValueError("Retained reports must produce finite A/B forecasts at every original decision.")
    return frame


def summarize(frame: pd.DataFrame) -> dict:
    row = {key: frame[key].iloc[0] for key in ("system", "attack", "drift_rate_knots_per_minute")}
    row.update(metrics(frame))
    original = metrics(frame, "original_error_minutes")
    row.update(original_mae_minutes=original["mae_minutes"], original_mdae_minutes=original["mdae_minutes"],
        mae_change_minutes=row["mae_minutes"]-original["mae_minutes"],
        mdae_change_minutes=row["mdae_minutes"]-original["mdae_minutes"],
        changed_prediction_decisions=int(frame.absolute_error_change.abs().gt(1e-7).sum()),
        realizations=int(frame.seed.nunique()))
    return row


def render_report(summary: pd.DataFrame, exposure: pd.DataFrame) -> str:
    report = """# SensorDriftAttack: automatic speed bias, frozen corrected A/B

This is a simulated sensor fault on original AIS observations. Original reported
speed is a reference, not independently verified physical truth. The tested rates
are stress settings, not estimated real-world sensor drift rates. Nothing forces
ETA degradation: prediction errors may worsen, improve or remain unchanged.

Only sog changes. Every report, position, course, class, identity, measurement and
delivery timestamp, decision clock and analytical crossing label is retained.
The bias starts at zero at each approach's first supplied report and progresses
in one direction, with a gently varying rate and a smooth 3-knot limit. Negative
rates underreport speed; positive rates overreport it. Variation is 25% with a
20-minute cycle. Seeds 4201/4202/4203 change one reproducible phase per vessel;
they are not training seeds. No individual reports are randomly selected.

Corrected saved A (quadratic Ridge) and B (XGBoost) are unchanged. The evaluation
uses 112 April approaches / 110 vessels / 2,402 decision times. Both original-feed
baselines are reproduced against the preceding corrected-model study. Models are
neither retrained nor recalibrated, and no new mitigation is introduced.

## Whole-approach errors

MAE gives approaches equal weight, averaging realizations within each approach.
MdAE and P95 pool prediction/seed absolute errors. All values are minutes to the
analytical crossing, not verified docking. Lower is better.

| Drift rate (knots/minute) | A MAE / MdAE | B MAE / MdAE | A P95 | B P95 |
|---|---:|---:|---:|---:|
"""
    for rate in (0., *RATES):
        selected = summary.loc[summary.drift_rate_knots_per_minute.eq(rate)]
        a, b = (selected.loc[selected.system.eq(name)].iloc[0] for name in ("A", "B"))
        label = "0 (original)" if rate == 0 else f"{rate:+.3f}"
        report += (f"| {label} | {a.mae_minutes:.4f} / {a.mdae_minutes:.4f} | "
                   f"{b.mae_minutes:.4f} / {b.mdae_minutes:.4f} | {a.p95_error_minutes:.4f} | {b.p95_error_minutes:.4f} |\n")
    report += ("\n## Paired MAE changes\n\nChanges compare each attacked prediction with its own "
        "original-feed forecast. Intervals use 1,000 paired vessel-cluster bootstrap draws.\n\n"
        "| Drift rate | A change [95% interval] | B change [95% interval] |\n|---|---:|---:|\n")
    for rate in RATES:
        selected = summary.loc[summary.drift_rate_knots_per_minute.eq(rate)]
        cells = []
        for name in ("A", "B"):
            row = selected.loc[selected.system.eq(name)].iloc[0]
            cells.append(f"{row.mae_change_minutes:+.4f} [{row.mae_change_ci_low:+.4f}, {row.mae_change_ci_high:+.4f}]")
        report += f"| {rate:+.3f} | {cells[0]} | {cells[1]} |\n"
    report += ("\n## Bounds and interpretation\n\nReported speeds are bounded to 0–102.2 knots. "
        "Existing missing speed remains missing. Audit files separate requested bias from the "
        "actual applied change and mark faults only when a valid speed changes. The smooth "
        "3-knot bias limit is a cap, not a promise of a 3-knot error at 30 minutes. "
        "Near zero or the upper speed bound, clipping can further reduce the applied bias.\n\n"
        "| Drift rate | Reports changed | Reports clipped | Maximum absolute requested / applied bias |\n"
        "|---|---:|---:|---:|\n")
    for rate, group in exposure.groupby("drift_rate_knots_per_minute", sort=False):
        report += (f"| {rate:+.3f} | {group.drifted_reports.sum():,} | {group.clipped_reports.sum():,} | "
                   f"{group.maximum_absolute_requested_bias.max():.4f} / {group.maximum_absolute_applied_bias.max():.4f} knots |\n")
    report += (f"\nForecast coverage is {summary.coverage.min():.2%} across all configurations. "
        "Report-count exposure totals pool three scenario realizations, not distinct source measurements. "
        "April was inspected previously; this is a follow-up study, not a pristine holdout. "
        "Original reports can already contain imperfections. These results do not prove that natural "
        "sensor drift caused the baseline ETA errors.\n\n"
        "The attack never changes forecasts or recovers missing data. Audit truth is excluded "
        "from model inputs. No source CSVs, saved models, shared feature/training code, service "
        "or frontend files change. CSV outputs remain local and ignored.\n\n"
        "Reproduce from Data_Science: `python experiments/sensor_drift_attack/run.py`.\n")
    return report


def main() -> None:
    started = time.perf_counter()
    output = HERE/"results"
    output.mkdir(exist_ok=True)
    config_path = SCIENCE/"Optimized_Model/config_vessel_class_v2.json"
    config = OptimizedConfig.load(config_path)
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    if decisions.approach_id.nunique() != 112 or len(decisions) != 2402:
        raise ValueError("Expected the existing 112-approach / 2,402-decision evaluation cohort.")
    model_paths = {"A": config.frozen_baseline_model("quadratic"), "B": config.frozen_baseline_model("xgboost")}
    protected = {**model_paths, "March": config.baseline.input_csv, "April": config.later_csv,
        "service": SCIENCE/"Optimized_Model/service.py", "baseline_training": SCIENCE/"eta_baselines/training.py",
        "optimized_training": SCIENCE/"Optimized_Model/model.py", "features": SCIENCE/"eta_baselines/features.py",
        "prediction": SCIENCE/"eta_baselines/prediction.py"}
    hashes = {name: file_digest(path) for name, path in protected.items()}
    systems = {name: joblib.load(path) for name, path in model_paths.items()}
    if any(tuple(predictor.feature_columns) != FEATURE_COLUMNS for predictor in systems.values()):
        raise ValueError("Both saved models must use the corrected vessel-class feature contract.")
    protocol = dict(attack=SensorDriftAttack.name, configuration=str(config_path),
        model_paths={name: str(path) for name, path in model_paths.items()}, protected_hashes=hashes,
        signed_rates_knots_per_minute=RATES, profile_seeds=SEEDS, training="None; saved A/B remain frozen",
        defaults=SensorDriftAttack().parameters, start_policy="Each supplied approach begins at its first report",
        profile="Integrated sinusoidal variation of signed rate; smoothly bounded with maximum_bias*tanh(q/maximum_bias)",
        speed_bounds_knots=[0., 102.2], simulation="Original reported speed is a reference, not verified physical truth",
        MAE="Equal approach weight, with scenario realizations averaged within each approach",
        MdAE="Pooled absolute-error median over decision/profile-seed pairs",
        P95="Pooled 95th percentile of absolute errors", bootstrap="1,000 paired vessel-cluster draws; fixed seed 20261021",
        scope="No service, frontend, shared feature/model-training, calibration or mitigation changes",
        evaluation="Same April 8-21 cases/clocks/analytical crossing references; previously inspected")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    nominal_attack = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=0))
    cases, base_rows = [], []
    for identity, group in decisions.groupby("approach_id", sort=False):
        history = dataset.histories[identity].sort_values("time", kind="stable").reset_index(drop=True)
        if history.duplicated(["mmsi", "time"]).any():
            raise ValueError("The prepared source cohort must contain unambiguous vessel/time keys.")
        cases.append((history, group))
        stream = nominal_attack.apply(history)
        base_rows.extend(snapshot(builder, stream, decision, zero_fill=False) for _, decision in group.iterrows())
    nominal_inputs = pd.DataFrame(base_rows)
    originals = {name: score(predictor, nominal_inputs, None, name, 0., 42) for name, predictor in systems.items()}
    references = {name: frame.set_index("decision_id").error_minutes for name, frame in originals.items()}
    expected = pd.read_csv(HERE.parent/"vessel_class_attacks/results_vessel_class_v2/summary.csv")
    for name, frame in originals.items():
        previous = expected.loc[expected.system.eq(name) & expected.selection_unit.eq("report") & expected.affected_fraction.eq(0.)].iloc[0]
        np.testing.assert_allclose(metrics(frame)["mae_minutes"], previous.mae_minutes, rtol=0, atol=1e-6)
        np.testing.assert_allclose(metrics(frame)["mdae_minutes"], previous.mdae_minutes, rtol=0, atol=1e-6)
    print("Corrected original-feed A/B MAE and MdAE reproduced; no retraining.", flush=True)
    predictions, exposure = list(originals.values()), []
    unchanged_features = [column for column in FEATURE_COLUMNS if column not in
                          ("speed_knots", "mean_speed_knots", "speed_trend_knots_per_minute")]
    unchanged_features += ["decision_id", "observation_time", "decision_time", "arrival_time"]
    audit_path = output/"report_audit.csv"
    first_audit = True
    for rate in RATES:
        for seed in SEEDS:
            rows, audits = [], []
            attack = SensorDriftAttack(replace(SensorDriftConfig(), drift_rate_knots_per_minute=rate, seed=seed))
            for history, group in cases:
                stream = attack.apply(history)
                other = list(history.columns.drop("sog"))
                pd.testing.assert_frame_equal(stream.reports[other], history[other])
                pd.testing.assert_series_equal(stream.reports.sog.isna(), history.sog.isna())
                audit = stream.modification_log.copy()
                audit["approach_id"] = group.approach_id.iloc[0]
                audit["drift_rate_knots_per_minute"] = rate
                audits.append(audit)
                exposure.append(dict(drift_rate_knots_per_minute=rate, seed=seed,
                    approach_id=group.approach_id.iloc[0], mmsi=group.mmsi.iloc[0],
                    source_reports=len(history), retained_reports=len(stream.reports),
                    drifted_reports=int(audit.fault_applied.sum()), clipped_reports=int(audit.clipped.sum()),
                    source_missing_speed=int(history.sog.isna().sum()),
                    maximum_absolute_requested_bias=float(audit.requested_bias_knots.abs().max()),
                    maximum_absolute_applied_bias=float(audit.applied_bias_knots.abs().max())))
                rows.extend(snapshot(builder, stream, decision, zero_fill=False) for _, decision in group.iterrows())
            inputs = pd.DataFrame(rows)
            pd.testing.assert_frame_equal(inputs[unchanged_features], nominal_inputs[unchanged_features])
            pd.concat(audits, ignore_index=True).to_csv(audit_path, index=False,
                mode="w" if first_audit else "a", header=first_audit)
            first_audit = False
            for name, predictor in systems.items():
                predictions.append(score(predictor, inputs, references[name], name, rate, seed))
            print(f"Rate {rate:+.3f} knots/minute / seed {seed}: all {len(inputs)} A/B forecast times retained", flush=True)
    results = pd.concat(predictions, ignore_index=True)
    results.to_csv(output/"predictions.csv", index=False)
    exposure_frame = pd.DataFrame(exposure)
    exposure_frame.to_csv(output/"injection_audit.csv", index=False)
    keys = ["system", "drift_rate_knots_per_minute"]
    summaries = []
    for _, group in results.groupby(keys, sort=False):
        row = summarize(group)
        row["mae_change_ci_low"], row["mae_change_ci_high"] = paired_interval(group)
        summaries.append(row)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output/"summary.csv", index=False)
    pd.DataFrame([dict(seed=group.seed.iloc[0], **summarize(group)) for _, group in
                  results.groupby(keys+["seed"], sort=False)]).to_csv(output/"per_seed_summary.csv", index=False)
    for name, path in protected.items():
        if file_digest(path) != hashes[name]:
            raise ValueError(f"Protected source/model/code changed: {name}")
    if not summary.coverage.eq(1.).all():
        raise ValueError("Every original prediction time must remain available.")
    validation = dict(baseline_mae_and_mdae_reproduced=True, every_source_report_retained=True,
        other_report_fields_and_missing_speed_pattern_preserved=True, unaffected_model_features_equal=True,
        original_clocks_and_arrival_labels_preserved=True, standard_feature_builder_used_for_every_decision=True,
        audit_truth_excluded_from_model_features=True, all_forecasts_finite=True, coverage_100_percent=True,
        protected_hashes_unchanged=True, approaches=112, vessels=int(decisions.mmsi.nunique()),
        unique_decisions=len(decisions), predictions=len(results), summary_rows=len(summary),
        drift_configurations=len(RATES)*len(SEEDS), elapsed_seconds=time.perf_counter()-started)
    (output/"validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    (output/"REPORT.md").write_text(render_report(summary, exposure_frame), encoding="utf-8")
    print(f"Saved {len(summary)} summaries / {len(results):,} predictions in {validation['elapsed_seconds']:.2f}s.", flush=True)


if __name__ == "__main__":
    main()

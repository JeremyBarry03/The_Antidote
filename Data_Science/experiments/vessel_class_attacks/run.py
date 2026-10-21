"""Field-only class faults with explicit unknown class, plus historical replay."""

import argparse
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

from attacks import MissingVesselClassAttack, MissingVesselClassConfig
from eta_baselines.dataset import file_digest, prepare_dataset
from eta_baselines.features import (FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, LEGACY_FEATURE_COLUMNS,
                                   FeatureBuilder, vessel_class_features)
from eta_baselines.prediction import EtaPredictor
from eta_baselines.training import BaselineTrainer, load_examples
from experiments.missing_speed_attack.run import metrics, paired_interval
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay

FRACTIONS = (.1, .25, .5, 1.)
SEEDS = (4201, 4202, 4203)
UNITS = ("report", "vessel")
FIXED_MODELS = SCIENCE/"artifacts/march_2024_vessel_class_v2"


def train_corrected_models(config: OptimizedConfig) -> None:
    """Keep dates/data/selected hyperparameters fixed; train on nominal March only."""
    selected = {name: json.loads((config.baseline.output_directory/name/"metrics.json").read_text())["selected_parameters"]
                for name in ("quadratic", "xgboost")}
    training = replace(config.baseline.training, ridge_alphas=[selected["quadratic"]["alpha"]],
        xgboost_depths=[selected["xgboost"]["depth"]],
        xgboost_learning_rates=[selected["xgboost"]["learning_rate"]])
    baseline = replace(config.baseline, output_directory=FIXED_MODELS, training=training)
    prepare_dataset(baseline)
    examples = load_examples(baseline)
    if examples.vessel_class_unknown.any():
        raise ValueError("Nominal cargo/tanker preparation unexpectedly contains unknown classes.")
    BaselineTrainer(baseline).train(examples, ["quadratic", "xgboost"])


def score(predictor: EtaPredictor, inputs: pd.DataFrame, reference: pd.Series,
          latest_classes: pd.DataFrame, system: str, attack: str, unit: str,
          fraction: float, seed: int) -> pd.DataFrame:
    predicted = predictor.predict(inputs)
    frame = predicted[["approach_id", "mmsi", "decision_id", "decision_time", "observation_time", "arrival_time",
                       "predicted_arrival_time", "report_age_minutes", "error_minutes"]].copy()
    frame["system"], frame["attack"], frame["selection_unit"] = system, attack, unit
    frame["affected_fraction"], frame["seed"] = fraction, seed
    frame["original_error_minutes"] = frame.decision_id.map(reference)
    frame["absolute_error_change"] = frame.error_minutes.abs()-frame.original_error_minutes.abs()
    # Audit is joined after inference, never used to recover missing/wrong inputs.
    frame = frame.join(latest_classes, on="decision_id", validate="one_to_one")
    if not np.isfinite(frame.error_minutes).all():
        raise ValueError("Every original decision must retain a finite forecast.")
    return frame


def summarize(frame: pd.DataFrame) -> dict:
    row = {key: frame[key].iloc[0] for key in ("system", "attack", "selection_unit", "affected_fraction")}
    row.update(metrics(frame))
    original = metrics(frame, "original_error_minutes")
    row.update(original_mae_minutes=original["mae_minutes"], original_mdae_minutes=original["mdae_minutes"],
               mae_change_minutes=row["mae_minutes"]-original["mae_minutes"],
               mdae_change_minutes=row["mdae_minutes"]-original["mdae_minutes"],
               changed_class_decisions=int(frame.class_field_changed.sum()),
               changed_prediction_decisions=int((frame.error_minutes-frame.original_error_minutes).abs().gt(1e-7).sum()))
    row["mae_change_ci_low"], row["mae_change_ci_high"] = paired_interval(frame)
    return row


def table(summary: pd.DataFrame, attack: str, unit: str) -> str:
    selected = summary.loc[summary.attack.eq(attack) & summary.selection_unit.eq(unit)]
    lines = ["| Selected fraction | A MAE / MdAE | B MAE / MdAE | Coverage |", "|---|---:|---:|---:|"]
    for fraction, group in selected.groupby("affected_fraction", sort=False):
        a = group.loc[group.system.eq("A")].iloc[0]
        b = group.loc[group.system.eq("B")].iloc[0]
        lines.append(f"| {fraction:.0%} | {a.mae_minutes:.4f} / {a.mdae_minutes:.4f} | "
                     f"{b.mae_minutes:.4f} / {b.mdae_minutes:.4f} | {a.coverage:.2%} |")
    return "\n".join(lines)


def render_report(summary: pd.DataFrame, slices: pd.DataFrame, class_counts: dict,
                  *, legacy: bool) -> str:
    version = "historical binary-class models" if legacy else "explicit unknown class, retrained A/B"
    encoding = (
        "These historical frozen models use only is_tanker: cargo and unknown both produce 0. "
        "The corrected models/results are in ../results_vessel_class_v2/REPORT.md. "
        "This table preserves the old model version; it does not describe the corrected input contract."
        if legacy else
        "Both models receive is_cargo/is_tanker/vessel_class_unknown: cargo=(1,0,0), "
        "tanker=(0,1,0), unknown=(0,0,1). Unknown stays distinct after median imputation. "
        "A/B were retrained on nominal March with the original splits, seed 42 and previously "
        "selected hyperparameters. The source cohort excludes missing classes, so there are zero "
        "unknown-class training examples. This fixes representation without adding synthetic "
        "missing-class training or claiming learned robustness to an unseen class state."
    )
    report = (f"# Missing vessel class: {version}\n\n"
        "MissingVesselClassAttack sets vessel_type to NaN. "
        "All reports, motion, clocks and crossing labels are retained. "
        "The original cohort is selected before injection; no class filter is reapplied.\n\n"
        f"## What reaches the models\n\n{encoding}\n\n"
        "Evaluation uses the same 112 April approaches / 110 vessels / 2,402 decision times. "
        "Each model is compared with its own original-feed baseline within this version. "
        "Partial selections use seeds 4201/4202/4203, which vary the fault selection, not model training. "
        "100% selection is seed independent and scored once. MAE gives approaches equal weight; "
        "MdAE pools prediction/seed absolute errors. Both are minutes to the analytical crossing, "
        "not verified docking. Lower is better.\n\n")
    for unit in UNITS:
        report += (f"## {MissingVesselClassAttack.name}: selection per {unit}\n\n"
                   f"{table(summary, MissingVesselClassAttack.name, unit)}\n\n")
    report += (f"## Class balance\n\n{class_counts.get(0., 0)} original cargo approaches and "
               f"{class_counts.get(1., 0)} original tanker approaches. "
               "Class-specific scores use original classes in evaluator audit only, never as recovered model inputs.\n\n")
    for name in ("A", "B"):
        selected = slices.loc[slices.attack.eq(MissingVesselClassAttack.name)
            & slices.selection_unit.eq("report") & slices.system.eq(name)
            & slices.cohort.eq("original_tanker")]
        before = selected.loc[selected.affected_fraction.eq(0.)].iloc[0]
        after = selected.loc[selected.affected_fraction.eq(1.)].iloc[0]
        report += f"Tanker-only {name} MAE: {before.mae_minutes:.4f} to {after.mae_minutes:.4f} minutes under full removal.\n\n"
    report += ("## Interpretation and limits\n\n"
        "The encoding fix does not guarantee lower errors or a monotonic response to increasing faults. "
        "An unknown state absent from nominal training can still follow a learned cargo-like decision path. "
        "Report MdAE and tail errors alongside MAE. No class reconstruction, metadata cache, "
        "forced ETA shift, outcome-based targeting or row removal is introduced.\n\n"
        "These are simulated faults on real histories. Original missingness does not establish valid-but-wrong "
        "source classifications. Fractions are selection probabilities, not exact quotas. April was already "
        "inspected, so these are follow-up results rather than a pristine holdout. All forecasts remain available.\n\n"
        "Source CSVs, historical frozen models and frontend/service files are preserved. New models live under "
        "artifacts/march_2024_vessel_class_v2; local CSVs remain ignored. The original service config still points "
        "to the original run. For the corrected A/B/C runtime use Optimized_Model/config_vessel_class_v2.json "
        "after preparing/training that version. Historical calibration and timelines are not evidence for the new models.\n\n")
    command = "--legacy" if legacy else "--train"
    report += f"Reproduce from Data_Science: `python experiments/vessel_class_attacks/run.py {command}`.\n"
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="Prepare/retrain corrected A/B in a separate versioned directory")
    parser.add_argument("--legacy", action="store_true", help="Reproduce the original frozen binary-class benchmark")
    arguments = parser.parse_args()
    if arguments.train and arguments.legacy:
        parser.error("--train and --legacy select different model versions")
    started = time.perf_counter()
    output = HERE/("results" if arguments.legacy else "results_vessel_class_v2")
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/"Optimized_Model/config.json")
    dataset = load_replay(config)
    legacy_paths = {"A": config.frozen_baseline_model("quadratic"), "B": config.frozen_baseline_model("xgboost")}
    original_protected = {**legacy_paths, "March": config.baseline.input_csv, "April": config.later_csv}
    original_hashes = {key: file_digest(path) for key, path in original_protected.items()}
    if arguments.train:
        print("Training corrected A/B on nominal March; no synthetic missing-class augmentation.", flush=True)
        train_corrected_models(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    model_paths = legacy_paths if arguments.legacy else {
        name: FIXED_MODELS/artifact/"model.joblib" for name, artifact in (("A", "quadratic"), ("B", "xgboost"))}
    if any(not path.exists() for path in model_paths.values()):
        raise FileNotFoundError("Corrected A/B models missing. Run this command with --train first, or --legacy for historical results.")
    protected = {**model_paths, "March": config.baseline.input_csv, "April": config.later_csv}
    hashes = {key: file_digest(path) for key, path in protected.items()}
    systems = {name: joblib.load(path) for name, path in model_paths.items()}
    expected_columns = LEGACY_FEATURE_COLUMNS if arguments.legacy else FEATURE_COLUMNS
    if any(tuple(predictor.feature_columns) != expected_columns for predictor in systems.values()):
        raise ValueError("Model feature contract differs from the selected experiment version.")
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    base_rows, cases, original_class_rows = {}, [], []
    for identity, group in decisions.groupby("approach_id", sort=False):
        history = dataset.histories[identity].sort_values("time").reset_index(drop=True)
        if history.duplicated(["mmsi", "time"]).any():
            raise ValueError("Ambiguous measurements require full-stream deduplication.")
        times = history.time.to_numpy()
        latest_positions = {}
        for _, decision in group.iterrows():
            row = builder.snapshot(history, decision.decision_time).iloc[0].to_dict()
            row.update(decision.to_dict())
            base_rows[decision.decision_id] = row
            position = int(np.searchsorted(times, decision.decision_time.to_datetime64(), side="right"))-1
            if position < 0:
                raise ValueError("Original decision lacks received history.")
            latest_positions[decision.decision_id] = position
            original_type = float(history.vessel_type.iloc[position])
            original_class_rows.append(dict(decision_id=decision.decision_id, original_vessel_type=original_type,
                attacked_vessel_type=original_type, original_is_tanker=row["is_tanker"], class_field_changed=False))
        cases.append((history, group, latest_positions))
    original_inputs = pd.DataFrame(base_rows.values())
    original_class = pd.DataFrame(original_class_rows).set_index("decision_id")
    originals = {name: predictor.predict(original_inputs) for name, predictor in systems.items()}
    references = {name: frame.set_index("decision_id").error_minutes for name, frame in originals.items()}
    if arguments.legacy:
        expected = pd.read_csv(config.output_directory/"results/evaluation_primary/condition_summary.csv")
        for name in systems:
            baseline = expected.loc[expected.system.eq(name) & expected.scenario.eq("nominal")].iloc[0]
            np.testing.assert_allclose(metrics(originals[name])["mae_minutes"], baseline.approach_weighted_mae_minutes,
                                       rtol=0, atol=1e-6)
    protocol = dict(version="field_only_v2" if arguments.legacy else FEATURE_SCHEMA_VERSION,
        models={"A": "frozen quadratic ridge" if arguments.legacy else "retrained quadratic ridge",
                "B": "frozen XGBoost" if arguments.legacy else "retrained XGBoost"},
        feature_columns=list(expected_columns), model_paths={name: str(path) for name, path in model_paths.items()},
        protected_hashes=hashes, fractions=FRACTIONS, partial_seeds=SEEDS, full_selection="Seed-independent; once",
        selection_units=UNITS,
        row_policy="Keep every original report; do not reapply the source cohort filter after injection",
        removal_encoding=("Historical binary model sees is_tanker=0 for unknown" if arguments.legacy else
                          "Cargo=(1,0,0), tanker=(0,1,0), unknown=(0,0,1) in is_cargo/is_tanker/vessel_class_unknown"),
        interventions="Missing masks vessel_type. Other report values remain exact.",
        features="Only class flags can change; validate full snapshots at first/middle/last decisions per case/config",
        evaluation="Same April 8-21 follow-up: original cases, clocks and crossing references; not verified docking",
        training=("None" if arguments.legacy else "March nominal only; original splits/selected hyperparameters/seed 42; no augmentation"),
        mitigation="No class reconstruction, metadata cache, forced ETA shifts or synthetic training examples",
        unknown_training_examples=0,
        metrics=dict(MAE="Equal approach weight; selection realizations pooled within each approach",
                     MdAE="Pooled absolute-error median over decision/seed pairs"),
        limits="Simulated class removal; requested fractions do not establish natural source fault rates.",
        legacy="Prior missing_vessel_class_attack/results describes row exclusions and is superseded for this attack")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    print("Matched original-feed A/B baselines scored. Field-only attacks keep every report.", flush=True)
    outputs, audits, checks = [], [], 0
    attack_type, config_type = MissingVesselClassAttack, MissingVesselClassConfig
    for unit in UNITS:
        for name, predictor in systems.items():
            outputs.append(score(predictor, original_inputs, references[name], original_class, name,
                                 attack_type.name, unit, 0., SEEDS[0]))
        for fraction in FRACTIONS:
            for seed in (SEEDS if fraction < 1 else SEEDS[:1]):
                rows, class_rows = [], []
                for history, group, latest_positions in cases:
                    stream = attack_type(config_type(fraction, seed, selection_unit=unit)).apply(history)
                    other = list(history.columns.drop("vessel_type"))
                    pd.testing.assert_frame_equal(stream.reports[other].reset_index(drop=True), history[other])
                    values = stream.reports.vessel_type.to_numpy(dtype=float, na_value=np.nan)
                    audits.append(dict(attack=attack_type.name, selection_unit=unit, affected_fraction=fraction,
                        seed=seed, approach_id=group.approach_id.iloc[0], mmsi=group.mmsi.iloc[0],
                        source_reports=len(history), retained_reports=len(stream.reports),
                        changed_class_reports=int(stream.modification_log.fault_applied.sum())))
                    checkpoints = {0, len(group)//2, len(group)-1}
                    for index, (_, decision) in enumerate(group.iterrows()):
                        position = latest_positions[decision.decision_id]
                        value = float(values[position])
                        row = base_rows[decision.decision_id].copy()
                        row.update(vessel_class_features(value))
                        if index in checkpoints:
                            standard = builder.snapshot(stream.reports, decision.decision_time).iloc[0]
                            np.testing.assert_allclose([row[c] for c in FEATURE_COLUMNS],
                                standard[list(FEATURE_COLUMNS)].to_numpy(dtype=float), rtol=0, atol=1e-10, equal_nan=True)
                            if row["observation_time"] != standard.observation_time:
                                raise ValueError("Class corruption changed the observation clock.")
                            checks += 1
                        rows.append(row)
                        original_type = float(history.vessel_type.iloc[position])
                        class_rows.append(dict(decision_id=decision.decision_id, original_vessel_type=original_type,
                            attacked_vessel_type=value, original_is_tanker=base_rows[decision.decision_id]["is_tanker"],
                            class_field_changed=bool(pd.isna(value) or value != original_type)))
                inputs = pd.DataFrame(rows)
                class_audit = pd.DataFrame(class_rows).set_index("decision_id")
                for name, predictor in systems.items():
                    outputs.append(score(predictor, inputs, references[name], class_audit, name,
                                         attack_type.name, unit, fraction, seed))
                print(f"{attack_type.name} / {unit} / {fraction:.0%} / seed {seed}: all {len(inputs)} forecasts retained", flush=True)
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output/"predictions.csv", index=False)
    pd.DataFrame(audits).to_csv(output/"injection_audit.csv", index=False)
    keys = ["attack", "selection_unit", "affected_fraction", "system"]
    summary = pd.DataFrame([summarize(group) for _, group in predictions.groupby(keys, sort=False)])
    summary.to_csv(output/"summary.csv", index=False)
    pd.DataFrame([dict(seed=group.seed.iloc[0], **summarize(group)) for _, group in predictions.groupby(
        keys+["seed"], sort=False)]).to_csv(output/"per_seed_summary.csv", index=False)
    slices = []
    for _, group in predictions.groupby(keys, sort=False):
        for label, selected in (("original_cargo", group.original_is_tanker.eq(0)),
                                ("original_tanker", group.original_is_tanker.eq(1))):
            if selected.any():
                slices.append(dict(cohort=label, **summarize(group.loc[selected])))
    pd.DataFrame(slices).to_csv(output/"class_subsets.csv", index=False)
    for key, path in protected.items():
        if file_digest(path) != hashes[key]:
            raise ValueError(f"Protected source/model changed: {key}")
    for key, path in original_protected.items():
        if file_digest(path) != original_hashes[key]:
            raise ValueError(f"Original source/frozen baseline changed: {key}")
    assert summary.coverage.eq(1.).all()
    elapsed = time.perf_counter()-started
    validation = dict(legacy_baselines_reproduced=arguments.legacy, matched_original_feed_baselines_scored=True,
        every_report_retained=True, other_report_fields_equal=True,
        standard_feature_checks=checks, original_clocks_and_crossing_references_preserved=True,
        all_summary_coverage_100_percent=True, source_and_model_hashes_unchanged=True,
        predictions=len(predictions), elapsed_seconds=elapsed)
    if not arguments.legacy:
        known = original_inputs.iloc[:1].copy()
        known.loc[:, list(vessel_class_features(70))] = list(vessel_class_features(70).values())
        unknown = known.copy()
        unknown.loc[:, list(vessel_class_features(np.nan))] = list(vessel_class_features(np.nan).values())
        for name, predictor in systems.items():
            cargo_vector = predictor.imputer.transform(known[list(predictor.feature_columns)])
            unknown_vector = predictor.imputer.transform(unknown[list(predictor.feature_columns)])
            if np.array_equal(cargo_vector, unknown_vector):
                raise ValueError(f"{name} preprocessing still aliases unknown to cargo.")
        validation["unknown_distinct_from_cargo_after_imputation"] = True
    (output/"validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    class_counts = original_inputs.groupby("is_tanker").approach_id.nunique().to_dict()
    report = render_report(summary, pd.DataFrame(slices), class_counts, legacy=arguments.legacy)
    (output/"REPORT.md").write_text(report, encoding="utf-8")
    print(f"Saved {len(summary)} summary rows / {len(predictions):,} predictions in {elapsed:.2f}s.", flush=True)


if __name__ == "__main__":
    main()

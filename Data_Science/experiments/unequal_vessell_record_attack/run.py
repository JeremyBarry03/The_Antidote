"""Isolated A/B retraining under amplified training-vessel representation."""

from dataclasses import asdict
from importlib.metadata import version
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

from attacks import UnequalVessellRecordAttack, UnequalVessellRecordConfig
from eta_baselines.dataset import file_digest
from eta_baselines.evaluation import approach_weights
from eta_baselines.features import FEATURE_COLUMNS, TARGET_COLUMN, FeatureBuilder
from eta_baselines.fitting import FitPartition, fit_imputer, fit_regressor
from eta_baselines.prediction import EtaPredictor
from eta_baselines.training import load_examples
from experiments.missing_speed_attack.run import metrics, paired_interval
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Simple_baseline.model import build_quadratic_regressor
from XGBoost_Model.model import build_xgboost_regressor

MULTIPLIERS = (1, 3, 5, 10, 50)
VESSEL_FRACTION = .2
WEIGHTINGS = ("approach_equal", "row_equal")


def evaluation_inputs(config: OptimizedConfig) -> pd.DataFrame:
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    rows = []
    for identity, group in decisions.groupby("approach_id", sort=False):
        history = dataset.histories[identity]
        for _, decision in group.iterrows():
            row = builder.snapshot(history, decision.decision_time).iloc[0].to_dict()
            row.update(decision.to_dict())
            rows.append(row)
    result = pd.DataFrame(rows)
    if result.decision_id.duplicated().any():
        raise ValueError("Evaluation decision IDs must be unique.")
    return result


def source_audit(path: Path, output: Path) -> dict:
    """Audit original cargo/tanker volume; do not use it for attack selection."""
    raw = pd.read_csv(path, usecols=["mmsi", "vessel_type"], dtype={"mmsi": str})
    raw = raw.loc[pd.to_numeric(raw.vessel_type, errors="coerce").between(70, 89)]
    counts = raw.groupby("mmsi").size().rename("source_rows")
    counts.to_csv(output / "march_source_volume_by_vessel.csv")
    return dict(cargo_tanker_rows=len(raw), vessels=len(counts),
                median_records_per_vessel=float(counts.median()),
                maximum_records_per_vessel=int(counts.max()))


def comparison_table(summary: pd.DataFrame, weighting: str) -> str:
    selected = summary.loc[summary.weighting.eq(weighting)]
    lines = ["| Selected vessels' row multiplier | A MAE | A MdAE | B MAE | B MdAE |",
             "|---|---:|---:|---:|---:|"]
    for multiplier, group in selected.groupby("record_multiplier", sort=False):
        a = group.loc[group.system.eq("A")].iloc[0]
        b = group.loc[group.system.eq("B")].iloc[0]
        lines.append(f"| {multiplier}x | {a.mae_minutes:.4f} | {a.mdae_minutes:.4f} | "
                     f"{b.mae_minutes:.4f} | {b.mdae_minutes:.4f} |")
    return "\n".join(lines)


def main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config.json")
    prepared = load_examples(config.baseline)
    train = prepared.loc[prepared.split.eq("train")].copy()
    validation = prepared.loc[prepared.split.eq("validation")].copy()
    evaluation = evaluation_inputs(config)
    if (set(train.approach_id) & set(validation.approach_id)
            or set(train.approach_id) & set(evaluation.approach_id)):
        raise ValueError("Training, validation and evaluation approaches must be disjoint.")
    frozen_paths = {"A": config.frozen_baseline_model("quadratic"),
                    "B": config.frozen_baseline_model("xgboost")}
    protected_paths = {**frozen_paths, "prepared_examples": config.baseline.output_directory / "examples.csv",
                       "march_source": config.baseline.input_csv, "april_source": config.later_csv}
    before_hashes = {name: file_digest(path) for name, path in protected_paths.items()}
    frozen = {name: joblib.load(path) for name, path in frozen_paths.items()}
    parameters = {"A": {"alpha": float(frozen["A"].regressor.get_params()["ridge__alpha"])},
                  "B": {key: frozen["B"].regressor.get_params()[key]
                        for key in ("max_depth", "learning_rate")}}
    frozen_predictions = {name: predictor.predict(evaluation) for name, predictor in frozen.items()}
    raw_audit = source_audit(config.baseline.input_csv, output)
    protocol = dict(
        attack=UnequalVessellRecordAttack.name, stage="training, after feature extraction and temporal splitting",
        record_multipliers=MULTIPLIERS, vessel_fraction=VESSEL_FRACTION,
        selection="Top training-example count; ceil(20% of training vessels); MMSI breaks ties; no error/target selection",
        selection_scope=f"{len(train)} prepared training examples, not all raw AIS reports",
        values_and_targets="Unchanged; duplicates represent repeated training exposure, not independent measurements",
        source_audit=raw_audit, protected_hashes=before_hashes,
        baseline_parameters=parameters, training_configuration=asdict(config.baseline.training),
        weightings=dict(approach_equal="Existing pipeline: approach_weights recomputed on replicated table",
                        row_equal="Counterfactual: every training row has weight one"),
        validation="Unchanged March validation; equal approach weights; existing XGBoost early stopping; no retuning",
        preprocessing="Refit train-only median imputer and A's unweighted StandardScaler, as in existing pipeline",
        seeds="Fixed original training seed 42; no random vessel selection or training-seed sweep",
        evaluation="Same April 8-21 cases and original clocks; follow-up on previously inspected data",
        reference="Analytical crossing, not independently verified docking",
        metrics=dict(MAE="Mean of per-approach mean absolute errors", MdAE="Pooled prediction absolute-error median",
                     vessel_MAE="Mean of per-vessel means of per-approach MAEs"),
        bootstrap="1000 vessel-cluster draws; seed 20261021; paired MAE change relative to each weighting's 1x control",
        limits="One deterministic selection and training seed; replication is a stress simulation, not measured source corruption",
    )
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    validation_weights = approach_weights(validation)
    summaries, predictions, audits, slices = [], [], [], []
    reference_errors = {}
    reproduction = {}
    for multiplier in MULTIPLIERS:
        attack = UnequalVessellRecordAttack(UnequalVessellRecordConfig(multiplier, VESSEL_FRACTION))
        result = attack.apply(train)
        # Every altered row must be an exact copy of its source, including missing fields and labels.
        pd.testing.assert_frame_equal(result.examples,
            train.iloc[result.modification_log.source_row].reset_index(drop=True))
        result.vessel_summary.to_csv(output / f"vessel_volume_{multiplier}x.csv", index=False)
        result.modification_log.to_csv(output / f"replication_audit_{multiplier}x.csv", index=False)
        selected = set(result.vessel_summary.loc[result.vessel_summary.selected, "mmsi"])
        imputer = fit_imputer(result.examples, FEATURE_COLUMNS)
        features = imputer.transform(result.examples[list(FEATURE_COLUMNS)])
        validation_features = imputer.transform(validation[list(FEATURE_COLUMNS)])
        for weighting in WEIGHTINGS:
            weights = (approach_weights(result.examples) if weighting == "approach_equal"
                       else np.ones(len(result.examples)))
            weight_table = result.examples[["approach_id", "mmsi"]].assign(weight=weights)
            approach_totals = weight_table.groupby("approach_id").weight.sum()
            if weighting == "approach_equal":
                np.testing.assert_allclose(approach_totals, approach_totals.iloc[0])
            audits.append(dict(record_multiplier=multiplier, weighting=weighting,
                training_rows=len(result.examples), selected_vessels=len(selected),
                training_vessels=train.mmsi.nunique(), original_training_rows=len(train),
                selected_row_share=float(result.examples.mmsi.isin(selected).mean()),
                selected_weight_share=float(weight_table.loc[weight_table.mmsi.isin(selected), "weight"].sum()/weights.sum()),
                minimum_approach_weight_share=float(approach_totals.min()/weights.sum()),
                maximum_approach_weight_share=float(approach_totals.max()/weights.sum()),
                total_training_weight=float(weights.sum())))
            for name in ("A", "B"):
                if name == "A":
                    regressor = build_quadratic_regressor(parameters[name]["alpha"])
                else:
                    regressor = build_xgboost_regressor(config.baseline.training,
                        int(parameters[name]["max_depth"]), float(parameters[name]["learning_rate"]))
                fit_regressor(regressor,
                    FitPartition(features, result.examples[TARGET_COLUMN].to_numpy(), weights),
                    FitPartition(validation_features, validation[TARGET_COLUMN].to_numpy(), validation_weights))
                predictor = EtaPredictor("quadratic" if name == "A" else "xgboost", imputer, regressor)
                model_directory = HERE / "models" / f"{weighting}_{multiplier}x"
                model_directory.mkdir(parents=True, exist_ok=True)
                joblib.dump(predictor, model_directory / f"{name}.joblib")
                predicted = predictor.predict(evaluation)
                columns = ["approach_id", "mmsi", "decision_id", "decision_time", "observation_time",
                           "arrival_time", "predicted_arrival_time", "error_minutes"]
                frame = predicted[columns].copy()
                frame["system"], frame["weighting"], frame["record_multiplier"] = name, weighting, multiplier
                if multiplier == 1:
                    reference_errors[(name, weighting)] = frame.set_index("decision_id").error_minutes
                    if weighting == "approach_equal":
                        deviation = np.abs(predicted.error_minutes.to_numpy()-frozen_predictions[name].error_minutes.to_numpy())
                        reproduction[name] = float(deviation.max())
                        np.testing.assert_allclose(predicted.error_minutes, frozen_predictions[name].error_minutes,
                                                   rtol=0, atol=1e-4 if name == "A" else 1e-7)
                frame["original_error_minutes"] = frame.decision_id.map(reference_errors[(name, weighting)])
                frame["absolute_error_change"] = frame.error_minutes.abs()-frame.original_error_minutes.abs()
                if not np.isfinite(frame.error_minutes).all():
                    raise ValueError("All scheduled evaluation forecasts must be finite.")
                row = dict(system=name, weighting=weighting, record_multiplier=multiplier, **metrics(frame))
                original = metrics(frame, "original_error_minutes")
                row.update(original_mae_minutes=original["mae_minutes"], original_mdae_minutes=original["mdae_minutes"],
                           mae_change_minutes=row["mae_minutes"]-original["mae_minutes"],
                           mdae_change_minutes=row["mdae_minutes"]-original["mdae_minutes"])
                row["mae_change_ci_low"], row["mae_change_ci_high"] = paired_interval(frame)
                per_approach = frame.assign(ae=frame.error_minutes.abs()).groupby(["mmsi", "approach_id"]).ae.mean()
                row["vessel_mae_minutes"] = float(per_approach.groupby("mmsi").mean().mean())
                if name == "B":
                    row["best_boosting_iteration"] = int(regressor.best_iteration)
                summaries.append(row)
                predictions.append(frame)
                groups = {
                    "seen_training_vessel": frame.mmsi.isin(set(train.mmsi)),
                    "unseen_training_vessel": ~frame.mmsi.isin(set(train.mmsi)),
                    "amplified_training_vessel": frame.mmsi.isin(selected),
                    "other_vessel": ~frame.mmsi.isin(selected),
                }
                for label, mask in groups.items():
                    if mask.any():
                        slices.append(dict(system=name, weighting=weighting, record_multiplier=multiplier,
                                           cohort=label, **metrics(frame.loc[mask])))
                print(f"{multiplier}x / {weighting} / {name}: MAE {row['mae_minutes']:.4f}; MdAE {row['mdae_minutes']:.4f}", flush=True)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output / "summary.csv", index=False)
    pd.concat(predictions, ignore_index=True).to_csv(output / "predictions.csv", index=False)
    pd.DataFrame(audits).to_csv(output / "training_weight_audit.csv", index=False)
    pd.DataFrame(slices).to_csv(output / "evaluation_slices.csv", index=False)
    after_hashes = {name: file_digest(path) for name, path in protected_paths.items()}
    if before_hashes != after_hashes:
        raise ValueError("Protected source/examples/model files changed during experiment.")
    elapsed = time.perf_counter()-started
    validation_report = dict(baseline_max_forecast_difference_minutes=reproduction,
        exact_replication_values_checked=True, evaluation_rows_unchanged=True,
        equal_approach_training_totals_checked=True, protected_hashes_unchanged=True,
        elapsed_seconds=elapsed, predictions=sum(len(frame) for frame in predictions),
        versions={package: version(package) for package in ("numpy", "pandas", "scikit-learn", "xgboost", "joblib")})
    (output / "validation.json").write_text(json.dumps(validation_report, indent=2), encoding="utf-8")
    first = pd.DataFrame(audits).query("record_multiplier == 1 and weighting == 'approach_equal'").iloc[0]
    last = pd.DataFrame(audits).query("record_multiplier == 50 and weighting == 'approach_equal'").iloc[0]
    changes = summary.loc[summary.record_multiplier.eq(50)].set_index(["weighting", "system"])
    outcome = (
        f"At 50x, current-pipeline MAE changes by {changes.loc[('approach_equal', 'A'), 'mae_change_minutes']:+.4f} "
        f"minutes for A and {changes.loc[('approach_equal', 'B'), 'mae_change_minutes']:+.4f} for B. "
        "Current approach weighting therefore largely limits this stress in these runs. "
        f"With ordinary row weighting, MAE rises {changes.loc[('row_equal', 'A'), 'mae_change_minutes']:.4f} "
        f"minutes for A and {changes.loc[('row_equal', 'B'), 'mae_change_minutes']:.4f} for B, "
        "relative to each row-weighted 1x reference. The large increases describe the "
        "counterfactual pipeline, not a major failure of the deployed weighting."
    )
    report = f"""# Unequal vessel record volume: A and B

This attack amplifies representation in training. It repeats the existing examples
of the top {int(VESSEL_FRACTION*100)}% of training vessels by row count, without changing any
feature, target, timestamp or evaluation row. It is a simulation, not evidence
that the original records were poisoned or that each replica is a new measurement.

## Data and protocol

Original March cargo/tanker source: {raw_audit['cargo_tanker_rows']:,} rows / {raw_audit['vessels']} vessels;
median {raw_audit['median_records_per_vessel']:g} records per vessel, maximum {raw_audit['maximum_records_per_vessel']:,}.
These raw counts include vessels/records without usable crossing labels.
The actual training cohort has {len(train):,} examples / {train.approach_id.nunique()} approaches /
{train.mmsi.nunique()} vessels, with median {train.groupby('mmsi').size().median():g} examples per vessel
and maximum {train.groupby('mmsi').size().max()}.

The selected {int(first.selected_vessels)} vessels originally contribute {first.selected_row_share:.2%} of
training rows. At 50x they contribute {last.selected_row_share:.2%} of {int(last.training_rows):,} rows.
Their share of supervised weight under current approach weighting stays
{first.selected_weight_share:.2%}, rather than growing to match their row share.

Training settings are fixed at the original selected A/B hyperparameters and seed
42. Only training rows are replicated. The original March validation data govern
XGBoost early stopping. No April error is used to select vessels or settings.
Evaluation: {evaluation.approach_id.nunique()} April approaches / {evaluation.mmsi.nunique()} vessels /
{len(evaluation):,} unchanged prediction times. Both original current-pipeline
forecasts were reproduced before amplification. Deployed models are unchanged.

## Current pipeline: equal approach training weights

{comparison_table(summary, 'approach_equal')}

## Counterfactual: ordinary row-weighted training

This is a separately retrained pipeline with uniform training-row weights, not the
deployed A/B configuration. Its 1x scores are its own matched references.

{comparison_table(summary, 'row_equal')}

## Interpretation and limits

{outcome}

All errors are minutes to the analytical crossing, not verified docking. MAE
weights approaches equally; MdAE pools prediction errors. Coverage remains 100%.
`summary.csv` also contains equal-vessel MAE, P95, and paired vessel-cluster
bootstrap intervals for change against each weighting's own 1x reference.
`evaluation_slices.csv` separates seen/unseen and amplified/other vessel identities.

Equal approach weighting is an existing partial protection, not a newly deployed
fix. The full pipeline need not be invariant: training medians and A's scaler
are unweighted, vessels can have multiple approaches, and mean-one weight
normalization changes the total ridge loss weight as row count grows. XGBoost
early stopping also responds to changed training. The row-weighted comparison
changes both weighting and its resulting fit; it is not the current system.

Replicas are repeated exposure to existing prepared examples, not extra reports
passing raw-data deduplication. These results do not establish that natural
record-volume imbalance caused the baseline errors, nor that more imbalance
must worsen every metric. This is one fixed training seed and a deterministic
count-based vessel selection. April was already inspected in prior experiments;
results are follow-up evidence, not a new pristine holdout.

No source data, prepared examples, existing model artifacts, service endpoints,
or frontend files are changed. Reproduce from `Data_Science`:
`python experiments/unequal_vessell_record_attack/run.py`.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"Saved {len(summary)} metric rows and {validation_report['predictions']:,} predictions in {elapsed:.2f}s", flush=True)


if __name__ == "__main__":
    main()

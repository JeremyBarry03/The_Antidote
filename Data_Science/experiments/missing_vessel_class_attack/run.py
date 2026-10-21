"""Legacy row-filter helpers, plus entry point for the current field-only study."""

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
from attacks.missingVesselClassAttack import classified_cargo_tanker_reports
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS, FeatureBuilder
from eta_baselines.prediction import EtaPredictor
from experiments.missing_speed_attack.run import metrics, paired_interval
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay

FRACTIONS = (.1, .25, .5, 1.)
SEEDS = (4201, 4202, 4203)
SELECTION_UNITS = ("report", "vessel")


def audit_source(path: Path) -> dict:
    """Count missing classes without inferring unknown records' true classes."""
    total, missing = 0, 0
    missing_by_mmsi, cargo_ids = {}, set()
    for chunk in pd.read_csv(path, usecols=["mmsi", "vessel_type"], dtype={"mmsi": str}, chunksize=200_000):
        classes = pd.to_numeric(chunk.vessel_type, errors="coerce")
        absent = classes.isna()
        total += len(chunk)
        missing += int(absent.sum())
        cargo_ids.update(chunk.loc[classes.between(70, 89), "mmsi"].dropna())
        for identity, count in chunk.loc[absent].groupby("mmsi").size().items():
            missing_by_mmsi[identity] = missing_by_mmsi.get(identity, 0) + int(count)
    overlap = set(missing_by_mmsi) & cargo_ids
    return dict(total_rows=total, missing_class_rows=missing, missing_class_fraction=missing/total,
                missing_class_mmsis=len(missing_by_mmsi),
                mmsis_with_both_missing_class_and_cargo_tanker_rows=len(overlap),
                missing_class_rows_on_those_mmsis=sum(missing_by_mmsi[identity] for identity in overlap),
                overlap_limit="Same-month identity overlap only; no classification or arrival inferred for unknown rows")


def feature_row(builder: FeatureBuilder, eligible: pd.DataFrame, times: np.ndarray,
                decision: pd.Series) -> dict:
    """Use only received eligible history, matching the standard snapshot window."""
    row = decision.to_dict()
    hi = int(np.searchsorted(times, decision.decision_time.to_datetime64(), side="right"))
    row["available"] = hi > 0
    row["eligible_reports_so_far"] = hi
    if hi == 0:
        row.update({column: np.nan for column in FEATURE_COLUMNS})
        row["observation_time"] = pd.NaT
        return row
    lo = int(np.searchsorted(times, times[hi-1]-np.timedelta64(builder.config.history_minutes, "m"), side="left"))
    row.update(builder.summarize(eligible.iloc[lo:hi]))
    row["observation_time"] = eligible.time.iloc[hi-1]
    return row


def score_inputs(predictor: EtaPredictor, inputs: pd.DataFrame, original: pd.Series,
                 system: str, unit: str, fraction: float, seed: int) -> pd.DataFrame:
    """Retain every scheduled decision; predict only when eligible history exists."""
    frame = inputs[["approach_id", "mmsi", "decision_id", "decision_time", "arrival_time",
                    "observation_time", "available", "eligible_reports_so_far"]].copy()
    frame["error_minutes"] = np.nan
    frame["predicted_arrival_time"] = pd.NaT
    frame["report_age_minutes"] = np.nan
    supported = inputs.loc[inputs.available]
    if not supported.empty:
        predicted = predictor.predict(supported)
        for column in ("error_minutes", "predicted_arrival_time", "report_age_minutes"):
            frame.loc[predicted.index, column] = predicted[column]
    frame["system"], frame["selection_unit"] = system, unit
    frame["affected_fraction"], frame["seed"] = fraction, seed
    frame["original_error_minutes"] = frame.decision_id.map(original)
    frame["matched_original_error_minutes"] = frame.original_error_minutes.where(frame.available)
    frame["absolute_error_change"] = frame.error_minutes.abs()-frame.matched_original_error_minutes.abs()
    if not np.isfinite(frame.loc[frame.available, "error_minutes"]).all():
        raise ValueError("Available forecasts must be finite.")
    if frame.loc[~frame.available, "error_minutes"].notna().any():
        raise ValueError("Unavailable forecasts cannot have errors.")
    return frame


def summarize(frame: pd.DataFrame) -> dict:
    row = {key: frame[key].iloc[0] for key in ("system", "selection_unit", "affected_fraction")}
    row.update(metrics(frame))
    matched = metrics(frame, "matched_original_error_minutes")
    full_original = metrics(frame, "original_error_minutes")
    row.update(matched_original_mae_minutes=matched["mae_minutes"],
               matched_original_mdae_minutes=matched["mdae_minutes"],
               full_original_mae_minutes=full_original["mae_minutes"],
               full_original_mdae_minutes=full_original["mdae_minutes"],
               mae_change_on_supported_minutes=row["mae_minutes"]-matched["mae_minutes"],
               mdae_change_on_supported_minutes=row["mdae_minutes"]-matched["mdae_minutes"],
               supported_approaches=frame.loc[frame.available, "approach_id"].nunique(),
               missing_forecasts=int((~frame.available).sum()))
    supported = frame.loc[frame.available]
    row["mae_change_ci_low"], row["mae_change_ci_high"] = (
        paired_interval(supported) if not supported.empty else (np.nan, np.nan))
    return row


def metric_text(value: float) -> str:
    return "unavailable" if pd.isna(value) else f"{value:.4f}"


def summary_table(summary: pd.DataFrame, unit: str) -> str:
    lines = ["| Class removed | Coverage | A MAE / MdAE | B MAE / MdAE | Matched original A / B MAE |",
             "|---|---:|---:|---:|---:|"]
    for fraction, group in summary.loc[summary.selection_unit.eq(unit)].groupby("affected_fraction", sort=False):
        a = group.loc[group.system.eq("A")].iloc[0]
        b = group.loc[group.system.eq("B")].iloc[0]
        label = "Original" if fraction == 0 else f"{fraction:.0%}"
        lines.append(f"| {label} | {a.coverage:.2%} | {metric_text(a.mae_minutes)} / {metric_text(a.mdae_minutes)} | "
                     f"{metric_text(b.mae_minutes)} / {metric_text(b.mdae_minutes)} | "
                     f"{metric_text(a.matched_original_mae_minutes)} / {metric_text(b.matched_original_mae_minutes)} |")
    return "\n".join(lines)


def legacy_filter_main() -> None:
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config.json")
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    model_paths = {"A": config.frozen_baseline_model("quadratic"), "B": config.frozen_baseline_model("xgboost")}
    model_hashes = {name: file_digest(path) for name, path in model_paths.items()}
    source_paths = {"March": config.baseline.input_csv, "April": config.later_csv}
    source_hashes = {name: file_digest(path) for name, path in source_paths.items()}
    systems = {name: joblib.load(path) for name, path in model_paths.items()}
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    cases, original_rows = [], []
    for identity, group in decisions.groupby("approach_id", sort=False):
        history = dataset.histories[identity].sort_values("time").reset_index(drop=True)
        if history.duplicated(["mmsi", "time"]).any():
            raise ValueError("Ambiguous records require full-stream deduplication.")
        if not history.vessel_type.between(70, 89).all():
            raise ValueError("Reference histories must match the current cargo/tanker cohort.")
        for _, decision in group.iterrows():
            row = builder.snapshot(history, decision.decision_time).iloc[0].to_dict()
            row.update(decision.to_dict())
            row.update(available=True, eligible_reports_so_far=int(history.time.le(decision.decision_time).sum()))
            original_rows.append(row)
        cases.append((history, group))
    original_inputs = pd.DataFrame(original_rows)
    originals = {name: predictor.predict(original_inputs) for name, predictor in systems.items()}
    references = {name: frame.set_index("decision_id").error_minutes for name, frame in originals.items()}
    expected = pd.read_csv(config.output_directory / "results/evaluation_primary/condition_summary.csv")
    for name in systems:
        baseline = expected.loc[expected.system.eq(name) & expected.scenario.eq("nominal")].iloc[0]
        np.testing.assert_allclose(metrics(originals[name])["mae_minutes"], baseline.approach_weighted_mae_minutes,
                                   rtol=0, atol=1e-6)
    source_audits = {name: audit_source(path) for name, path in source_paths.items()}
    protocol = dict(attack=MissingVesselClassAttack.name, model_hashes=model_hashes, source_hashes=source_hashes,
        source_audits=source_audits, models={"A": "frozen quadratic ridge", "B": "frozen XGBoost"},
        fractions=FRACTIONS, partial_selection_seeds=SEEDS, full_removal="Seed-independent; scored once",
        selection_units=dict(report="Hash seed:MMSI:measurement-time; intermittent field missingness",
                             vessel="Hash seed:MMSI; persistent missing class throughout each selected vessel history"),
        cohort_policy="Apply the existing loader's vessel_type BETWEEN 70 AND 89 to attacked reports before features",
        denominator="All original April cases and scheduled clocks; never rebuild arrivals or silently remove excluded vessels",
        baseline="Original already-filtered source observations, not a verified complete feed",
        accuracy="MAE equal approach weight among supported predictions; MdAE pooled supported absolute-error median",
        comparison="Each attack's accuracy compared to original predictions on the exact same supported decision/seed pairs",
        no_support="Coverage zero; errors and matched change undefined, never reported as zero",
        evaluation="April 8-21 follow-up on previously inspected data; analytical crossing, not verified docking",
        retraining="None; selection seeds alter fault realizations, not trained models",
        unknown_handling="No guessed class, zero fill or future class backfill; no new unknown-category model claimed",
        bootstrap="1000 vessel-cluster draws, seed 20261021; conditional paired MAE change",
        limitations="Known cargo/tanker records are masked; actual unknown-class source rows have no demonstrated cargo membership or crossing target",
    )
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    print("Original A/B baselines reproduced; source class counts audited.", flush=True)
    outputs, audits, checks = [], [], 0
    for unit in SELECTION_UNITS:
        for name, predictor in systems.items():
            outputs.append(score_inputs(predictor, original_inputs, references[name], name, unit, 0., SEEDS[0]))
        for fraction in FRACTIONS:
            for seed in (SEEDS if fraction < 1 else SEEDS[:1]):
                rows = []
                for history, group in cases:
                    stream = MissingVesselClassAttack(MissingVesselClassConfig(
                        fraction, seed, selection_unit=unit)).apply(history)
                    other_columns = list(history.columns.drop("vessel_type"))
                    pd.testing.assert_frame_equal(stream.reports[other_columns].reset_index(drop=True), history[other_columns])
                    eligible = classified_cargo_tanker_reports(stream.reports)
                    times = eligible.time.to_numpy()
                    audits.append(dict(selection_unit=unit, affected_fraction=fraction, seed=seed,
                        mmsi=group.mmsi.iloc[0], approach_id=group.approach_id.iloc[0], original_reports=len(history),
                        injected_missing_class=int(stream.modification_log.fault_applied.sum()),
                        eligible_reports=len(eligible), excluded_reports=len(history)-len(eligible)))
                    checkpoints = {0, len(group)//2, len(group)-1}
                    for index, (_, decision) in enumerate(group.iterrows()):
                        row = feature_row(builder, eligible, times, decision)
                        if row["available"] and index in checkpoints:
                            standard = builder.snapshot(eligible, decision.decision_time).iloc[0]
                            np.testing.assert_allclose([row[column] for column in FEATURE_COLUMNS],
                                standard[list(FEATURE_COLUMNS)].to_numpy(dtype=float), rtol=0, atol=1e-10, equal_nan=True)
                            if row["observation_time"] != standard.observation_time:
                                raise ValueError("Observation clock differs from standard extraction.")
                            checks += 1
                        rows.append(row)
                inputs = pd.DataFrame(rows)
                for name, predictor in systems.items():
                    frame = score_inputs(predictor, inputs, references[name], name, unit, fraction, seed)
                    if unit == "vessel":
                        # Surviving vessels retain identical inputs. A changed mix cannot be called an ETA improvement.
                        np.testing.assert_allclose(frame.loc[frame.available, "error_minutes"],
                            frame.loc[frame.available, "matched_original_error_minutes"], rtol=0, atol=1e-7)
                    outputs.append(frame)
                print(f"{unit}: {fraction:.0%} / seed {seed}; coverage {inputs.available.mean():.2%}", flush=True)
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output / "predictions.csv", index=False)
    pd.DataFrame(audits).to_csv(output / "injection_audit.csv", index=False)
    summary = pd.DataFrame([summarize(frame) for _, frame in predictions.groupby(
        ["selection_unit", "affected_fraction", "system"], sort=False)])
    summary.to_csv(output / "summary.csv", index=False)
    per_seed = pd.DataFrame([dict(seed=frame.seed.iloc[0], **summarize(frame)) for _, frame in predictions.groupby(
        ["selection_unit", "affected_fraction", "seed", "system"], sort=False)])
    per_seed.to_csv(output / "per_seed_summary.csv", index=False)
    grouped = predictions.groupby(["selection_unit", "affected_fraction", "seed", "system", "mmsi", "approach_id"], sort=False)
    per_approach = grouped.agg(scheduled=("available", "size"), available=("available", "sum"))
    per_approach["coverage"] = per_approach.available/per_approach.scheduled
    per_approach.to_csv(output / "approach_coverage.csv")
    if any(file_digest(path) != model_hashes[name] for name, path in model_paths.items()):
        raise ValueError("Frozen model changed.")
    if any(file_digest(path) != source_hashes[name] for name, path in source_paths.items()):
        raise ValueError("Source data changed.")
    elapsed = time.perf_counter()-started
    validation = dict(original_baselines_reproduced=True, original_crossing_references_unchanged=True,
        unaffected_fields_equal=True, all_scheduled_decisions_retained=True,
        standard_feature_checks=checks, surviving_vessel_forecasts_unchanged=True,
        sources_and_models_unchanged=True, scheduled_prediction_rows=len(predictions),
        elapsed_seconds=elapsed)
    (output / "validation.json").write_text(json.dumps(validation, indent=2), encoding="utf-8")
    at_half = summary.loc[summary.affected_fraction.eq(.5)].set_index(["selection_unit", "system"])
    outcome = (
        f"At 50% intermittent removal, A's MAE rises to {at_half.loc[('report', 'A'), 'mae_minutes']:.4f} "
        f"minutes and B's to {at_half.loc[('report', 'B'), 'mae_minutes']:.4f}; paired changes are "
        f"{at_half.loc[('report', 'A'), 'mae_change_on_supported_minutes']:+.4f} and "
        f"{at_half.loc[('report', 'B'), 'mae_change_on_supported_minutes']:+.4f} minutes. "
        f"Persistent 50% vessel selection leaves {at_half.loc[('vessel', 'A'), 'coverage']:.2%} "
        "coverage for both. A is more sensitive to the intermittent loss in these runs, "
        "while whole-vessel exclusion is a shared pipeline limitation."
    )
    report = f"""# MissingVesselClassAttack: A/B accuracy and coverage

This simulated attack removes only `vessel_type`. It keeps MMSI, motion, timing
and original crossing references unchanged. The existing cargo/tanker filter then
excludes unknown-class records. Empty history yields no forecast, not a zero error.

## Plan and protocol

1. Reuse BaseAttack and shared deterministic missing-field masking.
2. Test intermittent missing class per report and persistent missing class per vessel.
3. Apply the existing type-70-through-89 filter after masking, without guessing classes.
4. Reuse frozen A/B models and all {len(decisions):,} original prediction times from
   {decisions.approach_id.nunique()} April approaches / {decisions.mmsi.nunique()} vessels.
5. Report coverage and conditional accuracy; compare to the exact same surviving
   original predictions. Keep fully excluded cases in the coverage denominator.
6. Verify causal features, unchanged labels/data/models, full-removal behavior and API parity.

## Actual source observations

March has {source_audits['March']['missing_class_rows']:,} missing-class rows out of
{source_audits['March']['total_rows']:,}; April has {source_audits['April']['missing_class_rows']:,}
out of {source_audits['April']['total_rows']:,}. These counts cover all records, not only cargo/tankers.
MMSIs with both a missing-class row and a classified cargo/tanker row in the same
month number {source_audits['March']['mmsis_with_both_missing_class_and_cargo_tanker_rows']} in March and
{source_audits['April']['mmsis_with_both_missing_class_and_cargo_tanker_rows']} in April. Identity overlap
does not establish class or a crossing target for those unknown rows.

## Intermittent missing class: selection per report

{summary_table(summary, 'report')}

## Persistent missing class: selection per vessel

{summary_table(summary, 'vessel')}

Whole-vessel masking excludes selected vessels. The surviving vessels have exactly
the original predictions: their conditional MAE can change solely because the
cohort mix changes. The matched-original columns prevent calling this an accuracy
improvement or degradation. Actual per-seed coverage varies around each requested
vessel selection rate; rates are not exact quotas or measured real-world frequencies.

## Interpretation and limits

{outcome}

Intermittent missingness discards otherwise useful motion records, so an ETA may
use older evidence. Persistent missingness principally loses coverage. Both models
share the same ingestion gate, and neither can predict without eligible history.
At 100% removal both have zero coverage and undefined MAE/MdAE. These exclusions
are pipeline behavior, not proof that either regressor fails on a known input.

Errors are minutes to an analytical crossing, not verified docking. MAE weights
supported approaches equally; MdAE pools supported absolute errors. With partial
coverage these are conditional metrics, and matched original errors use the same
decision/seed pairs. `summary.csv` includes matched changes and vessel-cluster
bootstrap intervals; `per_seed_summary.csv` preserves each realization separately.

The baseline already excludes naturally unknown classes; it is not a verified
complete feed. Synthetic 10-100% masking applies to originally classified evaluation
histories and is not an estimate of natural source impact. Unknown-class source
records do not provide demonstrated cargo membership or reference arrivals here.
April was already inspected; this is follow-up evidence, not a pristine holdout.
Seeds 4201/4202/4203 change fault selection, with no retraining. Total removal is
seed independent and evaluated once. No forced ETA shifts or default classes.

Retaining an explicit unknown class would require a declared eligibility policy
and compatible model features/training; this experiment does not claim that fix.
The replay endpoint exposes exclusions and unavailable forecasts, without changing
the default ingestion pipeline, trained artifacts or frontend. CSVs remain local
and ignored by Git; this report, protocol and validation JSON can be tracked.

Reproduce from `Data_Science`: `python experiments/missing_vessel_class_attack/run.py`.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"Saved {len(summary)} summary rows / {len(predictions):,} scheduled forecast rows in {elapsed:.2f}s.", flush=True)


def main() -> None:
    """Run the current remove/swap experiment, retaining all reports."""
    from experiments.vessel_class_attacks.run import main as field_only_main

    field_only_main()


if __name__ == "__main__":
    main()

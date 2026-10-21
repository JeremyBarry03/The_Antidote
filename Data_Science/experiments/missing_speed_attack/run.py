"""Frozen B missing-speed evaluation and MdAE comparison of active attacks."""

import json
import platform
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import MissingSpeedAttack, MissingSpeedConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FeatureBuilder
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.presentation import REPORT_VALUE_COLUMNS
from Optimized_Model.replay import ReportStream

FRACTIONS = (.1, .25, .5, 1.)
SEEDS = (4201, 4202, 4203)
BOOTSTRAP_SEED = 20261021


def snapshot(builder: FeatureBuilder, stream: ReportStream, decision: pd.Series, zero_fill: bool) -> dict:
    received = stream.available(decision.decision_time).sort_values('time')
    # Match the raw B replay path, including exact measurement deduplication.
    received = received.drop_duplicates(list(REPORT_VALUE_COLUMNS))
    if zero_fill:
        received = received.copy()
        received['sog'] = received.sog.fillna(0.)
    row = builder.snapshot(received, decision.decision_time).iloc[0].to_dict()
    row.update(decision.to_dict())
    return row


def metrics(frame: pd.DataFrame, error_column: str = 'error_minutes') -> dict:
    valid = frame.loc[frame[error_column].notna()].copy()
    valid['ae'] = valid[error_column].abs()
    per = valid.groupby('approach_id').ae.mean()
    return dict(scheduled=len(frame), available=len(valid), unique_decisions=frame.decision_id.nunique(),
                approaches=frame.approach_id.nunique(), vessels=frame.mmsi.nunique(),
                coverage=len(valid)/len(frame), mae_minutes=per.mean(),
                mdae_minutes=valid.ae.median(), p95_error_minutes=valid.ae.quantile(.95))


def paired_interval(frame: pd.DataFrame) -> tuple[float, float]:
    per = frame.groupby(['mmsi', 'approach_id']).absolute_error_change.mean().reset_index()
    clusters = [g.absolute_error_change.to_numpy() for _, g in per.groupby('mmsi')]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bootstrap = [np.concatenate([clusters[i] for i in rng.integers(len(clusters), size=len(clusters))]).mean()
                 for _ in range(1000)]
    return tuple(np.quantile(bootstrap, [.025, .975]))


def table(frame: pd.DataFrame) -> str:
    lines = ['| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |',
             '|---|---|---|---|---:|---:|---:|']
    for row in frame.itertuples():
        lines.append(f'| {row.attack} | {row.setting} | {row.scope} | {row.handling} | {row.mae_minutes:.4f} | {row.mdae_minutes:.4f} | {row.original_mdae_minutes:.4f} |')
    return '\n'.join(lines)


def main() -> None:
    started = time.perf_counter()
    output = HERE/'results'
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/'Optimized_Model/config.json')
    dataset = load_replay(config)
    decisions = dataset.partition('evaluation').sort_values(['approach_id', 'decision_time'])
    model_path = config.frozen_baseline_model('xgboost')
    model_hash = file_digest(model_path)
    predictor = joblib.load(model_path)
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    protocol = dict(model='B / frozen XGBoost', model_sha256=model_hash, missing_fractions=FRACTIONS,
                    partial_selection_seeds=SEEDS, full_selection='Seed-independent; run once',
                    MAE='Equal approach weight, with seeds averaged within approaches',
                    MdAE='Median absolute error pooled across decision/seed pairs',
                    current_handling='Preserve NaN; existing training-fitted imputer and history_missing feature',
                    zero_fill_control='Set all missing sog to zero before features, including naturally missing speed',
                    masking='Independent per original report via deterministic hash, no stop/turn/outcome selection',
                    limits='Inference-time stress, not retraining; April has been inspected previously; analytical crossing, not docking',
                    stress_rates='10-100% are substantially higher than observed missing-speed rates',
                    active_attacks=['ReportingGapAttack', 'MissingSpeedAttack'],
                    bootstrap_seed=BOOTSTRAP_SEED, bootstrap_samples=1000)
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    original_inputs = {'preserve_missing': [], 'zero_fill_control': []}
    for identity, group in decisions.groupby('approach_id', sort=False):
        history = dataset.histories[identity]
        stream = ReportStream(history.assign(delivered_time=history.time), pd.DataFrame())
        for _, decision in group.iterrows():
            for handling in original_inputs:
                original_inputs[handling].append(snapshot(builder, stream, decision, handling=='zero_fill_control'))
    originals = {handling: predictor.predict(pd.DataFrame(rows)) for handling, rows in original_inputs.items()}
    pd.concat([g.assign(handling=h) for h, g in originals.items()], ignore_index=True).to_csv(output/'original_predictions.csv', index=False)
    baseline = metrics(originals['preserve_missing'])
    previous = pd.read_csv(config.output_directory/'results/evaluation_primary/condition_summary.csv')
    expected = previous.loc[previous.system.eq('B') & previous.scenario.eq('nominal')].iloc[0]
    assert abs(baseline['mae_minutes']-expected.approach_weighted_mae_minutes) < 1e-6
    outputs, audits = [], []
    for fraction in FRACTIONS:
        seeds = SEEDS if fraction < 1 else SEEDS[:1]
        for seed in seeds:
            views = {'preserve_missing': [], 'zero_fill_control': []}
            for identity, group in decisions.groupby('approach_id', sort=False):
                source = dataset.histories[identity]
                attack = MissingSpeedAttack(MissingSpeedConfig(fraction, seed))
                stream = attack.apply(source)
                # No dropped rows, changed positions, or timestamp/arrival perturbations.
                columns = list(source.columns.drop('sog'))
                pd.testing.assert_frame_equal(source[columns].sort_values('time').reset_index(drop=True),
                                              stream.reports[columns].reset_index(drop=True))
                audits.append(dict(approach_id=identity, affected_fraction=fraction, seed=seed,
                                   source_reports=len(source), source_missing_speed=int(source.sog.isna().sum()),
                                   injected_missing_speed=int(stream.modification_log.fault_applied.sum()),
                                   resulting_missing_speed=int(stream.reports.sog.isna().sum())))
                for _, decision in group.iterrows():
                    for handling in views:
                        views[handling].append(snapshot(builder, stream, decision, handling=='zero_fill_control'))
            for handling, rows in views.items():
                predicted = predictor.predict(pd.DataFrame(rows))
                predicted = predicted[['approach_id', 'mmsi', 'decision_id', 'decision_time', 'arrival_time',
                                       'observation_time', 'predicted_arrival_time', 'report_age_minutes', 'error_minutes']].copy()
                predicted['handling'] = handling
                predicted['affected_fraction'] = fraction
                predicted['seed'] = seed
                reference = originals[handling].set_index('decision_id').error_minutes
                predicted['original_error_minutes'] = predicted.decision_id.map(reference)
                predicted['absolute_error_change'] = predicted.error_minutes.abs()-predicted.original_error_minutes.abs()
                outputs.append(predicted)
            print(f'Completed {fraction:.0%} missing speed / seed {seed}', flush=True)
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output/'predictions.csv', index=False)
    pd.DataFrame(audits).to_csv(output/'injection_audit.csv', index=False)
    summaries = []
    for (handling, fraction), group in predictions.groupby(['handling', 'affected_fraction']):
        row = dict(attack='MissingSpeedAttack', setting=f'{fraction:.0%} speed missing', scope='whole_approach',
                   handling=handling, affected_fraction=fraction, seeds=group.seed.nunique())
        row.update(metrics(group))
        ref = metrics(group, 'original_error_minutes')
        row['original_mae_minutes'] = ref['mae_minutes']
        row['original_mdae_minutes'] = ref['mdae_minutes']
        row['mae_change_minutes'] = row['mae_minutes']-ref['mae_minutes']
        row['mdae_change_minutes'] = row['mdae_minutes']-ref['mdae_minutes']
        row['mae_change_ci_low'], row['mae_change_ci_high'] = paired_interval(group)
        summaries.append(row)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output/'missing_speed_summary.csv', index=False)
    comparison = [dict(attack='Original', setting='No added fault', scope='whole_approach',
                       handling='preserve_missing', original_mae_minutes=baseline['mae_minutes'],
                       original_mdae_minutes=baseline['mdae_minutes'], **baseline)]
    gap_path = SCIENCE/'experiments/reporting_gap_attack/results/predictions.csv'
    gap_rows = []
    if gap_path.exists():
        gaps = pd.read_csv(gap_path, dtype={'mmsi': str}, usecols=[
            'approach_id','mmsi','decision_id','gap_minutes','phase','error_minutes','original_error_minutes'])
        # Verify cohort/reference before combining reports, not just matching means.
        reference = originals['preserve_missing'].set_index('decision_id').error_minutes
        matched = gaps.decision_id.map(reference)
        assert matched.notna().all() and np.allclose(matched, gaps.original_error_minutes, atol=1e-7, rtol=0)
        for duration, group in gaps.groupby('gap_minutes'):
            for scope, cases in [('whole_approach', group), ('during_gap', group.loc[group.phase.eq('during')])]:
                ref = metrics(cases, 'original_error_minutes')
                row = dict(attack='ReportingGapAttack', setting=f'{duration} minute gap', scope=scope,
                           handling='existing_B', original_mae_minutes=ref['mae_minutes'], original_mdae_minutes=ref['mdae_minutes'])
                row.update(metrics(cases)); gap_rows.append(row)
        pd.DataFrame(gap_rows).to_csv(output/'reporting_gap_median_summary.csv', index=False)
    else:
        raise FileNotFoundError('Run experiments/reporting_gap_attack/run.py before building the all-attacks comparison.')
    combined = pd.concat([pd.DataFrame(comparison), pd.DataFrame(gap_rows), summary], ignore_index=True)
    combined.to_csv(output/'all_attacks_summary.csv', index=False)
    assert file_digest(model_path)==model_hash
    assert (predictions.observation_time<=predictions.decision_time).all()
    assert not predictions.duplicated(['handling','affected_fraction','seed','decision_id']).any()
    assert predictions.groupby(['handling','affected_fraction','seed']).size().eq(len(decisions)).all()
    checks = dict(model_unchanged=True, baseline_reproduced=True, positions_and_times_preserved=True,
                  no_future_measurements=True, gap_reference_matches_current_model=True,
                  active_attacks=['ReportingGapAttack','MissingSpeedAttack'],
                  decision_times=len(decisions), prediction_rows=len(predictions), runtime_seconds=time.perf_counter()-started,
                  python_version=platform.python_version())
    (output/'validation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    lines = ['# MissingSpeedAttack and MdAE across active attacks', '',
             'Model B is unchanged. 112 April approaches / 110 vessels / 2402 original decision times.', '',
             '## Current Model B handling', '',
             table(combined.loc[combined.scope.eq('whole_approach') & ~combined.handling.eq('zero_fill_control')]), '',
             '## Reporting gap: only prediction times inside the outage', '',
             table(combined.loc[combined.scope.eq('during_gap')]), '',
             '## Separate zero-fill control', '', table(summary.loc[summary.handling.eq('zero_fill_control')]), '',
             '## Definitions and limits', '',
             'MdAE means median absolute prediction error across decision/seed pairs, not the median of approach MAEs. MAE gives each approach equal weight; the two statistics have different weighting. Intervals in CSVs apply to mean absolute-error changes, not MdAE.',
             'MissingSpeedAttack preserves positions, course, timing and report counts, and replaces selected observed speeds with NaN. The current path uses the existing trained imputer and history_missing feature. This is not a new learned mitigation.',
             'The zero-fill control changes all missing sog to zero before building features, including naturally missing values. Its matched original-feed reference uses that same control. It is separate from the actual endpoint, which never zero-fills.',
             'Missing-speed removal is spread over an approach; reporting gaps are bounded outages at three fixed offsets. These are different exposure designs. During-gap comparisons have their own matched original MdAE and must not use the whole-cohort median as their reference.',
             'Rates of 10-100% are stress assumptions, much higher than observed missing speeds. Partial selection uses three fixed seeds; full selection is seed invariant and runs once. Original missing values are retained and never counted as injected defects.',
             'April results were previously inspected, so these are follow-up analyses. Error is relative to analytical gate crossing, not docking. No retraining or frontend changes. DuplicateReportAttack remains removed and is excluded from the active-attacks table.', '',
             'Run from Data_Science: `python experiments/missing_speed_attack/run.py`.']
    (output/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print(summary[['handling','affected_fraction','mae_minutes','mdae_minutes','mae_change_minutes']].to_string(index=False), flush=True)
    print('Reporting-gap medians:',pd.DataFrame(gap_rows)[['setting','scope','mae_minutes','mdae_minutes','original_mdae_minutes']].to_string(index=False), flush=True)
    print(json.dumps(checks, indent=2), flush=True)


if __name__=='__main__':
    main()

"""Missing-course stress test of frozen B, with paired zero-fill control."""

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import MissingCourseAttack, MissingCourseConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS, LEGACY_FEATURE_COLUMNS, FeatureBuilder
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from experiments.missing_speed_attack.run import metrics, paired_interval, table

FRACTIONS = (.1, .25, .5, 1.)
SEEDS = (4201, 4202, 4203)
HANDLINGS = ('preserve_missing', 'zero_fill_control')


def course_features(base: dict, course: float, zero_fill: bool) -> dict:
    """B's only course-dependent inputs are the latest course's sine and cosine."""
    row = base.copy()
    value = 0. if zero_fill and pd.isna(course) else course
    radians = np.deg2rad(value)
    row.update(course_sin=float(np.sin(radians)), course_cos=float(np.cos(radians)))
    return row


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
    if tuple(predictor.feature_columns) != LEGACY_FEATURE_COLUMNS:
        raise ValueError('This evaluator requires the original ten-feature B contract.')
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    protocol = dict(model='frozen B / XGBoost', model_sha256=model_hash, removal_fractions=FRACTIONS,
                    partial_selection_seeds=SEEDS, full_selection='100% is seed independent, evaluated once',
                    field='cog / course over ground, not heading',
                    current_pipeline='Preserve missing course, then apply existing trained feature imputation',
                    zero_fill_control='Fill missing cog with zero degrees before sine/cosine encoding; includes naturally missing values',
                    feature_reuse='Only course_sin and course_cos depend on cog in B. Reuse other columns; verify against standard extraction per approach/seed/config.',
                    reference='Same original analytical crossing, not docking; no retraining',
                    period='April 8-21 follow-up; previously inspected data',
                    rates='10-100% are stress assumptions, much greater than observed missing-course prevalence',
                    MAE='Equal approach weights; seeds averaged within approaches',
                    MdAE='Pooled median absolute error over decision/seed pairs',
                    bootstrap_seed=20261021, bootstrap_samples=1000)
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    original_inputs = {h: [] for h in HANDLINGS}
    cached = {}
    for identity, group in decisions.groupby('approach_id', sort=False):
        history = dataset.histories[identity].sort_values('time')
        if history.duplicated(['mmsi', 'time']).any():
            raise ValueError('Ambiguous timestamps require the full deduplication extractor.')
        for _, decision in group.iterrows():
            row = builder.snapshot(history, decision.decision_time).iloc[0].to_dict()
            row.update(decision.to_dict())
            cached[decision.decision_id] = row
            latest = history.loc[history.time <= decision.decision_time].iloc[-1]
            for handling in HANDLINGS:
                original_inputs[handling].append(course_features(row, latest.cog, handling=='zero_fill_control'))
    originals = {h: predictor.predict(pd.DataFrame(rows)) for h, rows in original_inputs.items()}
    pd.concat([g.assign(handling=h) for h, g in originals.items()], ignore_index=True).to_csv(output/'original_predictions.csv', index=False)
    baseline = metrics(originals['preserve_missing'])
    saved = pd.read_csv(config.output_directory/'results/evaluation_primary/condition_summary.csv')
    expected = saved.loc[saved.system.eq('B') & saved.scenario.eq('nominal')].iloc[0]
    assert abs(baseline['mae_minutes']-expected.approach_weighted_mae_minutes)<1e-6
    outputs, audits = [], []
    extraction_checks = 0
    for fraction in FRACTIONS:
        for seed in (SEEDS if fraction < 1 else SEEDS[:1]):
            views = {h: [] for h in HANDLINGS}
            for identity, group in decisions.groupby('approach_id', sort=False):
                source = dataset.histories[identity].sort_values('time')
                stream = MissingCourseAttack(MissingCourseConfig(fraction, seed)).apply(source)
                columns = list(source.columns.drop('cog'))
                pd.testing.assert_frame_equal(source[columns].reset_index(drop=True), stream.reports[columns].reset_index(drop=True))
                audits.append(dict(approach_id=identity, affected_fraction=fraction, seed=seed,
                                   original_reports=len(source), naturally_missing=int(source.cog.isna().sum()),
                                   injected_missing=int(stream.modification_log.fault_applied.sum()),
                                   resulting_missing=int(stream.reports.cog.isna().sum())))
                # Fixed clock samples, independent of forecast errors and outcomes.
                check_indices = {0, len(group)//2, len(group)-1}
                for index, (_, decision) in enumerate(group.iterrows()):
                    received = stream.available(decision.decision_time)
                    latest = received.iloc[-1]
                    base = cached[decision.decision_id]
                    for handling in HANDLINGS:
                        zero = handling=='zero_fill_control'
                        row = course_features(base, latest.cog, zero)
                        if index in check_indices:
                            reference_reports = received.assign(cog=received.cog.fillna(0.)) if zero else received
                            expected_row = builder.snapshot(reference_reports, decision.decision_time).iloc[0]
                            np.testing.assert_allclose([row[c] for c in FEATURE_COLUMNS], expected_row[list(FEATURE_COLUMNS)].to_numpy(dtype=float), rtol=0, atol=0, equal_nan=True)
                            extraction_checks += 1
                        views[handling].append(row)
            for handling, rows in views.items():
                predicted = predictor.predict(pd.DataFrame(rows))
                predicted = predicted[['approach_id','mmsi','decision_id','decision_time','arrival_time',
                                       'observation_time','predicted_arrival_time','report_age_minutes','error_minutes']].copy()
                predicted['handling'] = handling
                predicted['affected_fraction'] = fraction
                predicted['seed'] = seed
                ref = originals[handling].set_index('decision_id').error_minutes
                predicted['original_error_minutes'] = predicted.decision_id.map(ref)
                predicted['absolute_error_change'] = predicted.error_minutes.abs()-predicted.original_error_minutes.abs()
                outputs.append(predicted)
            print(f'Completed {fraction:.0%} missing course / seed {seed}', flush=True)
    predictions = pd.concat(outputs, ignore_index=True)
    predictions.to_csv(output/'predictions.csv', index=False)
    pd.DataFrame(audits).to_csv(output/'injection_audit.csv', index=False)
    summaries = []
    for (handling, fraction), group in predictions.groupby(['handling','affected_fraction']):
        ref = metrics(group, 'original_error_minutes')
        row = dict(attack='MissingCourseAttack', setting=f'{fraction:.0%} course missing', scope='whole_approach',
                   handling=handling, affected_fraction=fraction, seeds=group.seed.nunique(),
                   original_mae_minutes=ref['mae_minutes'], original_mdae_minutes=ref['mdae_minutes'])
        row.update(metrics(group))
        row['mae_change_minutes'] = row['mae_minutes']-ref['mae_minutes']
        row['mdae_change_minutes'] = row['mdae_minutes']-ref['mdae_minutes']
        row['mae_change_ci_low'], row['mae_change_ci_high'] = paired_interval(group)
        summaries.append(row)
    summary = pd.DataFrame(summaries)
    summary.to_csv(output/'missing_course_summary.csv', index=False)
    previous = SCIENCE/'experiments/missing_speed_attack/results'
    previous_protocol = json.loads((previous/'protocol.json').read_text())
    assert previous_protocol['model_sha256']==model_hash
    previous_original = pd.read_csv(previous/'original_predictions.csv')
    previous_original = previous_original.loc[previous_original.handling.eq('preserve_missing')]
    mapped = previous_original.decision_id.map(originals['preserve_missing'].set_index('decision_id').error_minutes)
    assert mapped.notna().all() and np.allclose(mapped, previous_original.error_minutes, atol=1e-7, rtol=0)
    combined = pd.concat([pd.read_csv(previous/'all_attacks_summary.csv'), summary], ignore_index=True)
    combined.to_csv(output/'all_attacks_summary.csv', index=False)
    assert file_digest(model_path)==model_hash
    assert (predictions.observation_time<=predictions.decision_time).all()
    assert not predictions.duplicated(['handling','affected_fraction','seed','decision_id']).any()
    assert predictions.groupby(['handling','affected_fraction','seed']).size().eq(len(decisions)).all()
    checks = dict(model_unchanged=True, baseline_reproduced=True, all_other_fields_unchanged=True,
                  no_future_inputs=True, previous_reference_matches=True, exact_standard_feature_checks=extraction_checks,
                  approaches=decisions.approach_id.nunique(), decision_times=len(decisions), prediction_rows=len(predictions),
                  runtime_seconds=time.perf_counter()-started)
    (output/'validation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    report = ['# MissingCourseAttack: Model B results', '',
              '112 April approaches, 110 vessels, 2402 decision times. No retraining, no altered crossing truth.', '',
              '## Current missing-value handling', '', table(summary.loc[summary.handling.eq('preserve_missing')]), '',
              '## Separate zero-fill control', '', table(summary.loc[summary.handling.eq('zero_fill_control')]), '',
              '## All active attacks: whole approaches', '',
              table(combined.loc[combined.scope.eq('whole_approach') & ~combined.handling.eq('zero_fill_control')]), '',
              '## Limits', '',
              'Course over ground is a circular angle. A valid zero means north; missing course is not a valid zero. The current path preserves NaN before the existing sine/cosine feature imputation. The control instead replaces missing cog with zero before encoding, including any naturally missing course. Each control has a matched original-feed reference using the same preprocessing.',
              'Only course_sin and course_cos depend on cog in B. Other features and observation clocks are reused; exact equivalence with standard feature extraction is checked at first, middle, and last scheduled decisions in every approach/configuration/seed.',
              'MAE averages approach MAEs equally. MdAE pools absolute errors across decision/seed pairs, so the weighting differs. Bootstrap intervals in CSVs apply to paired MAE changes. Partial removal uses three fixed seeds; total removal is seed invariant and runs once.',
              'Rates of 10-100% are simulated stress assumptions, not measured field-failure rates. Removal is spread across an approach; reporting gaps are bounded windows. Do not rank differently exposed scenarios as equally severe real-world events.',
              'April data have already been inspected; this is follow-up evidence. Arrival is an analytical crossing, not docking. No new learned mitigation, no frontend changes, and DuplicateReportAttack remains removed.', '',
              'Reproduce from Data_Science: `python experiments/missing_course_attack/run.py`.']
    (output/'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    print(summary[['handling','affected_fraction','mae_minutes','mdae_minutes','mae_change_minutes']].to_string(index=False), flush=True)
    print(json.dumps(checks, indent=2), flush=True)


if __name__=='__main__':
    main()

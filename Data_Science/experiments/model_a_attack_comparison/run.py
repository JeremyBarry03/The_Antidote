"""Paired frozen A/B evaluation of the three implemented input attacks."""

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

from attacks import MissingCourseAttack, MissingCourseConfig, MissingSpeedAttack, MissingSpeedConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FEATURE_COLUMNS, LEGACY_FEATURE_COLUMNS, FeatureBuilder
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from experiments.missing_speed_attack.run import metrics, paired_interval

FRACTIONS = (.1, .25, .5, 1.)
SEEDS = (4201, 4202, 4203)
HANDLINGS = ('preserve_missing', 'zero_fill_control')
HANDLINGS = ('preserve_missing', 'zero_fill_control')
TIME_COLUMNS = ('decision_time', 'observation_time', 'arrival_time', 'episode_start',
                'crossing_before', 'crossing_after')


def read_saved(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={'mmsi': str}, float_precision='round_trip')
    for column in TIME_COLUMNS:
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def masked_features(base: dict, values: np.ndarray, times: np.ndarray, field: str, zero: bool) -> dict:
    """Reuse only features independent of the masked field; preserve B's formulas."""
    row = base.copy()
    observed = np.where(np.isnan(values), 0., values) if zero else values
    if field == 'cog':
        radians = np.deg2rad(observed[-1])
        row.update(course_sin=float(np.sin(radians)), course_cos=float(np.cos(radians)))
        return row
    valid = ~np.isnan(observed)
    count = int(valid.sum())
    trend = np.nan
    if count >= 2:
        seconds = (times[valid]-times[valid][0])/np.timedelta64(1, 's')
        minutes = seconds/60
        if minutes[-1] > 0:
            trend = float(np.polyfit(minutes, observed[valid], 1)[0])
    row.update(speed_knots=float(observed[-1]),
               mean_speed_knots=float(np.nansum(observed)/count) if count else np.nan,
               speed_trend_knots_per_minute=trend,
               history_missing=float(len(observed) < 2 or count < 2))
    return row


def score(predictor, inputs: pd.DataFrame, reference: pd.Series, system: str,
          attack: str, setting: str, handling: str) -> pd.DataFrame:
    predicted = predictor.predict(inputs)
    columns = ['approach_id','mmsi','decision_id','decision_time','arrival_time','observation_time',
               'predicted_arrival_time','error_minutes','report_age_minutes']
    result = predicted[columns].copy()
    for column in ('seed', 'affected_fraction', 'gap_minutes', 'start_offset_minutes', 'phase'):
        if column in inputs:
            result[column] = inputs[column].to_numpy()
    result['system'] = system
    result['attack'] = attack
    result['setting'] = setting
    result['handling'] = handling
    result['original_error_minutes'] = result.decision_id.map(reference)
    result['absolute_error_change'] = result.error_minutes.abs()-result.original_error_minutes.abs()
    return result


def summarize(group: pd.DataFrame, scope: str) -> dict:
    row = {name: group[name].iloc[0] for name in ('system','attack','setting','handling')}
    row['scope'] = scope
    row.update(metrics(group))
    original = metrics(group, 'original_error_minutes')
    row.update(original_mae_minutes=original['mae_minutes'], original_mdae_minutes=original['mdae_minutes'],
               mae_change_minutes=row['mae_minutes']-original['mae_minutes'],
               mdae_change_minutes=row['mdae_minutes']-original['mdae_minutes'])
    row['mae_change_ci_low'], row['mae_change_ci_high'] = paired_interval(group)
    return row


def table(frame: pd.DataFrame) -> str:
    lines = ['| Attack | Setting | A MAE | A MdAE | B MAE | B MdAE |', '|---|---|---:|---:|---:|---:|']
    for (attack, setting), group in frame.groupby(['attack','setting'], sort=False):
        a = group.loc[group.system.eq('A')].iloc[0]
        b = group.loc[group.system.eq('B')].iloc[0]
        lines.append(f'| {attack} | {setting} | {a.mae_minutes:.4f} | {a.mdae_minutes:.4f} | {b.mae_minutes:.4f} | {b.mdae_minutes:.4f} |')
    return '\n'.join(lines)


def main() -> None:
    started = time.perf_counter()
    output = HERE/'results'
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/'Optimized_Model/config.json')
    dataset = load_replay(config)
    paths = {'A': config.frozen_baseline_model('quadratic'), 'B': config.frozen_baseline_model('xgboost')}
    hashes = {name: file_digest(path) for name, path in paths.items()}
    systems = {name: joblib.load(path) for name, path in paths.items()}
    if any(tuple(p.feature_columns) != LEGACY_FEATURE_COLUMNS for p in systems.values()):
        raise ValueError('Both models must use the original ten-feature contract.')
    decisions = dataset.partition('evaluation').sort_values(['approach_id','decision_time'])
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    protocol = dict(models={'A': 'degree-two polynomial ridge regression', 'B': 'XGBoost'}, model_hashes=hashes,
                    missing_fractions=FRACTIONS, partial_seeds=SEEDS, full_removal='seed invariant; one run',
                    gap_durations=[5,10,15,30], gap_start_offsets_after_first_decision=[12,32,62],
                    comparison='Identical cases, causal features, clocks, labels and attack settings for both frozen models',
                    training='none', evaluation='April 8-21 follow-up; previously inspected',
                    reference='Original analytical crossing, not docking',
                    features='Reuse unaffected columns; verify affected formulas against standard extraction and reproduce all saved B forecasts',
                    MAE='Equal approach weight', MdAE='Pooled absolute-error median across decision/seed/placement pairs',
                    controls='Missing stays NaN in current handling; separate zero-fill controls include naturally missing fields')
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    base_rows, cases = {}, []
    for identity, group in decisions.groupby('approach_id', sort=False):
        history = dataset.histories[identity].sort_values('time').reset_index(drop=True)
        if history.duplicated(['mmsi','time']).any():
            raise ValueError('Ambiguous observations require full-stream deduplication.')
        times = history.time.to_numpy()
        windows = {}
        for _, decision in group.iterrows():
            row = builder.snapshot(history, decision.decision_time).iloc[0].to_dict()
            row.update(decision.to_dict())
            base_rows[decision.decision_id] = row
            hi = int(np.searchsorted(times, decision.decision_time.to_datetime64(), side='right'))
            lo = int(np.searchsorted(times, times[hi-1]-np.timedelta64(10, 'm'), side='left'))
            windows[decision.decision_id] = (lo, hi)
        cases.append((history, times, group, windows))
    original_inputs = pd.DataFrame(base_rows.values())
    originals = {name: predictor.predict(original_inputs) for name, predictor in systems.items()}
    clean_reference = {name: original.set_index('decision_id').error_minutes for name, original in originals.items()}
    all_outputs = []
    for name in systems:
        all_outputs.append(score(systems[name], original_inputs, clean_reference[name], name,
                                 'Original', 'No added fault', 'preserve_missing'))
    saved_summary = pd.read_csv(config.output_directory/'results/evaluation_primary/condition_summary.csv')
    for name in systems:
        expected = saved_summary.loc[saved_summary.system.eq(name) & saved_summary.scenario.eq('nominal')].iloc[0]
        assert abs(metrics(originals[name])['mae_minutes']-expected.approach_weighted_mae_minutes)<1e-6
    print('Both original baselines reproduced.', flush=True)
    # Reuse the actual gap attack's saved feature vectors, not a new outage design.
    gap_directory = SCIENCE/'experiments/reporting_gap_attack/results'
    gaps = read_saved(gap_directory/'predictions.csv')
    assert gaps.available.all() and set(gaps.decision_id)==set(decisions.decision_id)
    b_gap = systems['B'].predict(gaps)
    np.testing.assert_allclose(b_gap.error_minutes, gaps.error_minutes, rtol=0, atol=1e-7)
    for duration, inputs in gaps.groupby('gap_minutes', sort=False):
        for name in systems:
            all_outputs.append(score(systems[name], inputs, clean_reference[name], name,
                                     'ReportingGapAttack', f'{duration} minute gap', 'preserve_missing'))
    print('Reporting gaps scored against A and B; saved B forecasts reproduced.', flush=True)
    checks_count = 0
    golden_count = len(gaps)
    for field, attack_type, config_type, directory in (
        ('sog', MissingSpeedAttack, MissingSpeedConfig, 'missing_speed_attack'),
        ('cog', MissingCourseAttack, MissingCourseConfig, 'missing_course_attack'),
    ):
        attack_name = attack_type.name
        previous = SCIENCE/'experiments'/directory/'results'
        previous_protocol = json.loads((previous/'protocol.json').read_text())
        assert previous_protocol['model_sha256']==hashes['B']
        gold = read_saved(previous/'predictions.csv')
        # Each preprocessing control gets a matched reference for each model.
        references = {}
        for handling in HANDLINGS:
            rows = []
            for history, times, group, windows in cases:
                values = history[field].to_numpy(dtype=float)
                for _, decision in group.iterrows():
                    lo, hi = windows[decision.decision_id]
                    rows.append(masked_features(base_rows[decision.decision_id], values[lo:hi], times[lo:hi], field,
                                                handling=='zero_fill_control'))
            frame = pd.DataFrame(rows)
            for name, predictor in systems.items():
                references[(name, handling)] = predictor.predict(frame).set_index('decision_id').error_minutes
        for fraction in FRACTIONS:
            for seed in (SEEDS if fraction<1 else SEEDS[:1]):
                rows_by_handling = {handling: [] for handling in HANDLINGS}
                for history, times, group, windows in cases:
                    stream = attack_type(config_type(fraction, seed)).apply(history)
                    other = list(history.columns.drop(field))
                    pd.testing.assert_frame_equal(stream.reports[other].reset_index(drop=True), history[other])
                    values = stream.reports[field].to_numpy(dtype=float)
                    check_indices = {0, len(group)//2, len(group)-1}
                    for index, (_, decision) in enumerate(group.iterrows()):
                        lo, hi = windows[decision.decision_id]
                        for handling in HANDLINGS:
                            zero = handling=='zero_fill_control'
                            row = masked_features(base_rows[decision.decision_id], values[lo:hi], times[lo:hi], field, zero)
                            row.update(seed=seed, affected_fraction=fraction)
                            if index in check_indices:
                                recent = stream.reports.iloc[lo:hi].copy()
                                if zero:
                                    recent[field] = recent[field].fillna(0.)
                                expected = builder.summarize(recent)
                                np.testing.assert_allclose([row[c] for c in FEATURE_COLUMNS],
                                    [expected[c] for c in FEATURE_COLUMNS], rtol=0, atol=1e-10, equal_nan=True)
                                checks_count += 1
                            rows_by_handling[handling].append(row)
                for handling, rows in rows_by_handling.items():
                    inputs = pd.DataFrame(rows)
                    for name, predictor in systems.items():
                        result = score(predictor, inputs, references[(name, handling)], name,
                                       attack_name, f'{fraction:.0%} removed', handling)
                        if name=='B':
                            previous_rows = gold.loc[gold.handling.eq(handling) & gold.affected_fraction.eq(fraction) & gold.seed.eq(seed)]
                            expected = result.decision_id.map(previous_rows.set_index('decision_id').error_minutes)
                            assert expected.notna().all()
                            np.testing.assert_allclose(result.error_minutes, expected, rtol=0, atol=1e-7)
                            golden_count += len(result)
                        all_outputs.append(result)
                print(f'{attack_name}: {fraction:.0%} removal, seed {seed} completed.', flush=True)
    predictions = pd.concat(all_outputs, ignore_index=True)
    for attack, frame in predictions.groupby('attack'):
        frame.to_csv(output/f'{attack}_predictions.csv', index=False)
    summaries = []
    for _, group in predictions.groupby(['system','attack','setting','handling'], sort=False):
        summaries.append(summarize(group, 'whole_approach'))
        if group.attack.iloc[0]=='ReportingGapAttack':
            summaries.append(summarize(group.loc[group.phase.eq('during')], 'during_gap'))
    summary = pd.DataFrame(summaries)
    summary.to_csv(output/'summary.csv', index=False)
    assert (predictions.observation_time<=predictions.decision_time).all()
    assert {name: file_digest(path) for name,path in paths.items()}==hashes
    baseline_arrival = decisions.set_index('decision_id').arrival_time
    assert (predictions.arrival_time==predictions.decision_id.map(baseline_arrival)).all()
    validation = dict(models_unchanged=True, no_retraining=True, original_baselines_reproduced=True,
                      all_saved_B_forecasts_reproduced=True, matched_saved_B_predictions=golden_count,
                      standard_feature_checks=checks_count, no_future_inputs=True, crossing_labels_unchanged=True,
                      approaches=decisions.approach_id.nunique(), vessels=decisions.mmsi.nunique(),
                      original_decision_times=len(decisions), prediction_rows=len(predictions),
                      runtime_seconds=time.perf_counter()-started)
    (output/'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    current = summary.loc[summary.scope.eq('whole_approach') & summary.handling.eq('preserve_missing')]
    control = summary.loc[summary.scope.eq('whole_approach') & summary.handling.eq('zero_fill_control')]
    during = summary.loc[summary.scope.eq('during_gap')]
    lines = ['# Model A versus Model B: three input attacks', '',
             'A is degree-two polynomial ridge regression; B is XGBoost. Both are existing frozen models, not new training runs.', '',
             '112 April approaches / 110 vessels / 2402 original decision times. Identical inputs, seeds, labels and clocks for each pair.', '',
             '## Whole approach: current missing-value handling', '', table(current), '',
             '## Only prediction times inside reporting gaps', '', table(during), '',
             '## Separate zero-fill controls', '', table(control), '',
             '## Interpretation and limits', '',
             'Errors are minutes relative to analytical crossing, not verified docking. Lower is better. MAE gives each approach equal weight; MdAE pools absolute errors across decision/seed/placement pairs. Coverage and paired MAE-change intervals are in summary.csv.',
             'Reporting gaps reuse the exact saved attacked features at 5/10/15/30 minutes and three fixed onsets after the first forecast. Partial speed/course removal uses the same 4201/4202/4203 selection seeds as B; these vary missing reports, not trained models. Total removal is seed independent and scored once.',
             'Current missingness stays NaN before each model applies its own trained imputer. Zero-fill controls substitute zero before feature construction, including naturally missing fields, and use matched original-feed control references. They are not current endpoint behavior or newly proposed mitigations.',
             'Only affected feature columns are recomputed for field masking. Formula agreement with the standard builder is checked at first/middle/last decisions per approach/configuration/handling; every reproduced B forecast is compared with its previous saved result. Outage features are reused after reproducing all saved B outage forecasts.',
             'The models are not clipped or recalibrated to improve results. Outages are bounded windows; missing-field removal is distributed over approaches. These different exposure designs do not establish real-world relative failure frequencies. April data have previously been inspected; this is a follow-up study.',
             'No source data, model artifacts, attack semantics, frontend code or previous result files are changed.', '',
             'Reproduce from Data_Science: `python experiments/model_a_attack_comparison/run.py`.']
    (output/'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print(current[['system','attack','setting','mae_minutes','mdae_minutes','coverage']].to_string(index=False), flush=True)
    print('ZERO-FILL CONTROLS\n'+control[['system','attack','setting','mae_minutes','mdae_minutes']].to_string(index=False), flush=True)
    print(json.dumps(validation, indent=2), flush=True)


if __name__=='__main__':
    main()

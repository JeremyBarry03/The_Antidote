"""Evaluate the actual ReportingGapAttack against frozen Model B, without retraining."""

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

from attacks import ReportingGapAttack, ReportingGapConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FeatureBuilder
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.replay import ReportStream

GAP_MINUTES = (5, 10, 15, 30)
START_OFFSETS_MINUTES = (12, 32, 62)
BOOTSTRAP_SEED = 20261020
BOOTSTRAP_SAMPLES = 1000


def snapshot(builder: FeatureBuilder, received: pd.DataFrame, decision: pd.Series) -> dict:
    """Use exactly B's existing causal ten-minute feature contract."""
    row = builder.snapshot(received, decision.decision_time).iloc[0].to_dict()
    row.update(decision.to_dict())
    return row


def summarize(group: pd.DataFrame, duration: int, scope: str) -> dict:
    valid = group.loc[group.available].copy()
    per = valid.groupby(['mmsi', 'approach_id']).agg(
        original_mae=('original_absolute_error', 'mean'),
        attacked_mae=('absolute_error', 'mean'),
        difference=('absolute_error_change', 'mean'),
    ).reset_index()
    vessel_groups = [g.difference.to_numpy() for _, g in per.groupby('mmsi')]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bootstrap = [np.concatenate([vessel_groups[i] for i in rng.integers(len(vessel_groups), size=len(vessel_groups))]).mean()
                 for _ in range(BOOTSTRAP_SAMPLES)] if vessel_groups else [np.nan]
    original = per.original_mae.mean()
    attacked = per.attacked_mae.mean()
    return dict(gap_minutes=duration, scope=scope, scheduled=len(group), available=len(valid),
                approaches=group.approach_id.nunique(), vessels=group.mmsi.nunique(),
                output_coverage=len(valid)/len(group) if len(group) else None,
                original_mae_minutes=original, attacked_mae_minutes=attacked,
                mae_change_minutes=attacked-original,
                mae_change_percent=(attacked-original)/original*100 if original else None,
                change_ci_low=np.quantile(bootstrap, .025), change_ci_high=np.quantile(bootstrap, .975),
                decisions_worsened_share=valid.absolute_error_change.gt(0).mean(),
                decisions_improved_share=valid.absolute_error_change.lt(0).mean(),
                original_p95_error=valid.original_absolute_error.quantile(.95),
                attacked_p95_error=valid.absolute_error.quantile(.95))


def markdown_table(frame: pd.DataFrame) -> str:
    columns = ['gap_minutes', 'original_mae_minutes', 'attacked_mae_minutes', 'mae_change_minutes',
               'change_ci_low', 'change_ci_high', 'scheduled', 'output_coverage']
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join(['---']*len(columns)) + ' |']
    for _, row in frame.iterrows():
        lines.append('| ' + ' | '.join(str(int(row[c])) if c in ('gap_minutes', 'scheduled') else f'{row[c]:.4f}' for c in columns) + ' |')
    return '\n'.join(lines)


def main() -> None:
    started = time.perf_counter()
    output = HERE / 'results'
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / 'Optimized_Model/config.json')
    model_path = config.frozen_baseline_model('xgboost')
    model_hash = file_digest(model_path)
    dataset = load_replay(config)
    decisions = dataset.partition('evaluation').sort_values(['approach_id', 'decision_time'])
    predictor = joblib.load(model_path)
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    protocol = dict(model='B / frozen XGBoost', model_sha256=model_hash, gaps_minutes=GAP_MINUTES,
                    start_offsets_after_first_decision_minutes=START_OFFSETS_MINUTES,
                    start_selection='Fixed offsets, independent of arrival labels or prediction errors',
                    split='April 8-21 follow-up evaluation; already inspected in earlier work',
                    attack='ReportingGapAttack: permanent loss during [start,end), no backfill',
                    outcome='Original analytical gate crossing, not docking',
                    weighting='Each approach equal; each start offset has the same decision schedule',
                    bootstrap_seed=BOOTSTRAP_SEED, bootstrap_samples=BOOTSTRAP_SAMPLES,
                    uncertainty='Vessel-cluster bootstrap; repeated outage placements are not independent vessels')
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    original_rows, attacked_rows, audits = [], [], []
    for index, (identity, group) in enumerate(decisions.groupby('approach_id', sort=False)):
        history = dataset.histories[identity].sort_values('time')
        nominal = ReportStream(history.assign(delivered_time=history.time), pd.DataFrame())
        cached = {}
        for _, decision in group.iterrows():
            row = snapshot(builder, nominal.available(decision.decision_time), decision)
            original_rows.append(row)
            cached[decision.decision_id] = row
        first_time = group.decision_time.min()
        for offset in START_OFFSETS_MINUTES:
            start = first_time + pd.Timedelta(minutes=offset)
            for duration in GAP_MINUTES:
                end = start + pd.Timedelta(minutes=duration)
                attack = ReportingGapAttack(ReportingGapConfig(start, end, str(group.mmsi.iloc[0])))
                stream = attack.apply(history)
                removed = stream.modification_log.loc[stream.modification_log.fault_applied].copy()
                removed['approach_id'] = identity
                removed['gap_minutes'] = duration
                removed['start_offset_minutes'] = offset
                audits.append(removed)
                for _, decision in group.iterrows():
                    received = stream.available(decision.decision_time)
                    supported = not received.empty
                    original = cached[decision.decision_id]
                    outside_feature_window = original['observation_time'] - pd.Timedelta(minutes=10) >= end
                    if decision.decision_time < start or outside_feature_window:
                        row = original.copy()
                    elif supported:
                        row = snapshot(builder, received, decision)
                    else:
                        row = decision.to_dict()
                    phase = ('before' if decision.decision_time < start else
                             'during' if decision.decision_time < end else
                             'recovery' if decision.decision_time < end+pd.Timedelta(minutes=10) else 'after')
                    row.update(gap_minutes=duration, start_offset_minutes=offset, gap_start=start, gap_end=end,
                               phase=phase, available=supported,
                               withheld_reports_so_far=int(removed.time.le(decision.decision_time).sum()))
                    attacked_rows.append(row)
        if index % 20 == 0:
            print(f'Replayed {index+1}/{decisions.approach_id.nunique()} approaches', flush=True)

    original = predictor.predict(pd.DataFrame(original_rows))
    original['original_absolute_error'] = original.error_minutes.abs()
    original.to_csv(output/'original_predictions.csv', index=False)
    frames = pd.DataFrame(attacked_rows)
    result = frames.copy()
    result['predicted_arrival_time'] = pd.NaT
    result['error_minutes'] = np.nan
    result['report_age_minutes'] = np.nan
    valid = frames.available
    predictions = predictor.predict(frames.loc[valid])
    for column in ['predicted_arrival_time', 'error_minutes', 'report_age_minutes']:
        result.loc[valid, column] = predictions[column].to_numpy()
    reference = original[['decision_id', 'error_minutes', 'predicted_arrival_time', 'report_age_minutes']].rename(
        columns={c: 'original_'+c for c in ['error_minutes', 'predicted_arrival_time', 'report_age_minutes']})
    result = result.merge(reference, on='decision_id', validate='many_to_one')
    result['absolute_error'] = result.error_minutes.abs()
    result['original_absolute_error'] = result.original_error_minutes.abs()
    result['absolute_error_change'] = result.absolute_error - result.original_absolute_error
    result.to_csv(output/'predictions.csv', index=False)
    pd.concat(audits, ignore_index=True).to_csv(output/'dropped_reports.csv', index=False)
    summaries = []
    for duration, group in result.groupby('gap_minutes'):
        summaries.append(summarize(group, duration, 'whole_approach'))
        for phase in ['during', 'recovery']:
            summaries.append(summarize(group.loc[group.phase.eq(phase)], duration, phase))
    summary = pd.DataFrame(summaries)
    summary.to_csv(output/'mae_summary.csv', index=False)
    per_approach = result.groupby(['approach_id', 'mmsi', 'gap_minutes', 'start_offset_minutes']).agg(
        original_mae=('original_absolute_error', 'mean'), attacked_mae=('absolute_error', 'mean'),
        scheduled=('available', 'size'), available=('available', 'sum'),
        withheld_reports=('withheld_reports_so_far', 'max')).reset_index()
    per_approach.to_csv(output/'per_approach.csv', index=False)
    validation = dict(model_unchanged=file_digest(model_path)==model_hash,
                      original_decisions=len(original), approaches=original.approach_id.nunique(),
                      attacked_predictions=len(result), future_observations_excluded=bool(
                          (frames.loc[valid, 'observation_time'] <= frames.loc[valid, 'decision_time']).all()),
                      non_targeted_data_unchanged='covered by attack unit tests')
    saved = pd.read_csv(config.output_directory/'results/evaluation_primary/condition_summary.csv')
    expected = saved.loc[saved.system.eq('B') & saved.scenario.eq('nominal'), 'approach_weighted_mae_minutes'].iloc[0]
    measured = original.groupby('approach_id').original_absolute_error.mean().mean()
    assert abs(measured-expected) < 1e-6
    assert validation['model_unchanged'] and validation['future_observations_excluded']
    assert len(result) == len(decisions)*len(GAP_MINUTES)*len(START_OFFSETS_MINUTES)
    assert not result.duplicated(['decision_id', 'gap_minutes', 'start_offset_minutes']).any()
    assert (result.arrival_time == result.decision_id.map(original.set_index('decision_id').arrival_time)).all()
    validation['nominal_baseline_reproduced'] = True
    validation['runtime_seconds'] = time.perf_counter()-started
    validation['python_version'] = platform.python_version()
    (output/'validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    report = ['# ReportingGapAttack: Model B evaluation', '',
              f'Original-feed MAE: **{measured:.4f} minutes**. {len(original)} decisions, {original.approach_id.nunique()} approaches, {original.mmsi.nunique()} vessels.', '',
              '## Whole approach', '', markdown_table(summary.loc[summary.scope.eq('whole_approach')]), '',
              '## During the outage: same-clock matched comparisons', '', markdown_table(summary.loc[summary.scope.eq('during')]), '',
              '## First ten minutes after the outage', '', markdown_table(summary.loc[summary.scope.eq('recovery')]), '',
              '## Interpretation', '',
              'Positive MAE change means the gap worsened ETA accuracy. Whole-approach averages include unaffected decisions. During/recovery rows compare the same clocks and cases with the original feed; their reference MAE differs from the full-cohort reference because their case/time mixes differ.',
              'Three fixed onset offsets after the first scheduled forecast are used per approach. Short approaches can finish before later outages; they stay in whole-approach denominators. During-gap results are conditional on the approach still having a scheduled forecast in the configured window.',
              'A 95% change interval is a vessel-cluster bootstrap interval; repeated clocks and placements are not independent cases. There is no retraining, new mitigation, or selection of onset based on errors. Reports missing inside the window do not return afterward. Initial history is retained because outages start after the first forecast.',
              'This is a controlled missing-update simulation on real tracks, not evidence of naturally occurring poisoning or actual transmission outages. April has been inspected previously, so this is a follow-up evaluation. Arrival means analytical gate crossing, not docking.', '',
              'Reproduce from Data_Science: `python experiments/reporting_gap_attack/run.py`. Settings, hashes, validation, predictions and dropped-report logs are saved in this directory.']
    (output/'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    print(summary.to_string(index=False), flush=True)
    print(json.dumps(validation, indent=2), flush=True)


if __name__ == '__main__':
    main()

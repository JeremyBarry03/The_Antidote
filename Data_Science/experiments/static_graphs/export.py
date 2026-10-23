"""Export actual frozen-model forecasts for every combination of quarter-strength attacks.

This evaluation-only export needs the evaluation CSV and fitted models. It never
opens the training CSV, fits models, or substitutes invented chart values.
Run from Data_Science: .venv/bin/python experiments/static_graphs/export.py
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

SCIENCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCIENCE))

from eta_baselines.approaches import ApproachBuilder
from eta_baselines.configuration import ExperimentConfig, FeatureConfig, GateConfig, SplitConfig, TrainingConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import FeatureBuilder
from eta_baselines.observations import iter_observation_vessels
from Optimized_Model.configuration import GuardConfig
from Optimized_Model.dataset import METADATA_COLUMNS, ReplayDataset
from Optimized_Model.evaluation import PredictionSystem, predict_systems
from Optimized_Model.features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from Optimized_Model.fleet import ATTACK_CONTROLS, FleetService, poisoning_settings, unix_seconds
from Optimized_Model.fleet_analysis import FleetAnalysis
from Optimized_Model.fleet_mitigations import FleetPolicy
from Optimized_Model.model import inference_implementation
from Optimized_Model.views import view_row
from mitigation.missing_vessel_class_mitigation.optimized_model import vessel_class_snapshot
from mitigation.navigation_features import repaired_navigation_features


def feature_patch(fleet, reports, clock, policy):
    """Same C input repairs, without building unused UI diagnostics for offline rows."""
    original, guard = fleet.extractor.snapshot(reports, clock, guarded=True)
    effective = guard.reports.copy(deep=True).reset_index(drop=True)
    patch = {}
    if not policy.position_faults and not effective.empty:
        for strategy, column in ((fleet.mitigations.speed, 'sog'), (fleet.mitigations.course, 'cog')):
            current = effective[column].to_numpy(dtype=float)
            invalid = ~np.isfinite(current) | (current < 0) | (current > 102.2 if column == 'sog' else current >= 360)
            if invalid.any():
                warmup = reports.loc[reports.time.ge(reports.time.max() - pd.Timedelta(
                    minutes=fleet.extractor.baseline.features.history_minutes + strategy.config.history_minutes))]
                repair = strategy.repair_reports(warmup, clock)
                replacement = effective.record_id.map(repair.reports.set_index('record_id')[column]).to_numpy(dtype=float)
                selected = invalid & np.isfinite(replacement)
                effective.loc[selected, column] = replacement[selected]
        if not (policy.noise and policy.speed_drift):
            for enabled, strategy, columns in ((policy.noise, fleet.mitigations.noise, ('sog', 'cog')),
                                               (policy.speed_drift, fleet.mitigations.drift, ('sog',))):
                if not enabled or not strategy.apply(reports, clock).can_predict:
                    continue
                for index, report in effective.iterrows():
                    delivery = report.get('delivered_time', report.time)
                    history = reports.loc[reports.time.le(report.time) & reports.delivered_time.le(delivery)]
                    reading = strategy.apply(history, delivery)
                    if not reading.can_predict:
                        continue
                    for column in columns:
                        if getattr(reading, 'speed_source' if column == 'sog' else 'course_source') == 'estimated':
                            effective.at[index, column] = getattr(reading, 'speed_knots' if column == 'sog' else 'course_degrees')
        if not original.empty and not np.isclose(guard.reports[['sog', 'cog']].to_numpy(dtype=float),
                                                effective[['sog', 'cog']].to_numpy(dtype=float),
                                                equal_nan=True, rtol=0, atol=1e-10).all():
            from Optimized_Model.features import QUALITY_COLUMNS
            columns = tuple(column for column in RICH_COLUMNS if column not in QUALITY_COLUMNS)
            derived = repaired_navigation_features(original, effective, fleet.extractor, columns)
            patch.update({column: derived.iloc[0][column] for column in columns})
    class_view = vessel_class_snapshot(reports, clock, fleet.extractor, fleet.mitigations.vessel_class)
    if not class_view.original_features.equals(class_view.mitigated_features):
        patch.update({column: class_view.mitigated_features.iloc[0][column]
                      for column in ('is_cargo', 'is_tanker', 'vessel_class_unknown')})
    return patch


@dataclass(frozen=True)
class FrozenGraphConfig:
    baseline: ExperimentConfig
    guard: GuardConfig
    evaluation_start: str
    evaluation_end: str
    evaluation_seeds: list[int]
    later_csv: Path


class OfflineFeatures(OptimizedFeatures):
    """Reuse identical snapshots within a checkpoint; never reuse across clocks."""

    def __init__(self, *args):
        super().__init__(*args)
        self.snapshots = {}

    def snapshot(self, available, decision_time, *, guarded):
        key = (guarded, pd.Timestamp(decision_time).value,
               pd.util.hash_pandas_object(available, index=False).values.tobytes())
        if key not in self.snapshots:
            self.snapshots[key] = super().snapshot(available, decision_time, guarded=guarded)
        return self.snapshots[key]


def read_inputs(config_path: Path, source: Path):
    contents = json.loads(config_path.read_text())
    baseline_path = (config_path.parent / contents['baseline_config']).resolve()
    raw = json.loads(baseline_path.read_text())
    baseline = ExperimentConfig(
        input_csv=(baseline_path.parent / raw['input_csv']).resolve(),
        output_directory=(baseline_path.parent / raw['output_directory']).resolve(),
        gate=GateConfig(**raw['gate']), features=FeatureConfig(**raw['features']),
        splits=SplitConfig(**raw['splits']), training=TrainingConfig(**raw['training']))
    config = FrozenGraphConfig(baseline, GuardConfig(**contents['guard']), contents['evaluation_start'],
                               contents['evaluation_end'], contents['evaluation_seeds'], source)
    root = (config_path.parent / contents['output_directory']).resolve()
    paths = {'A': root/'frozen_baselines/quadratic/model.joblib',
             'B': root/'frozen_baselines/xgboost/model.joblib', 'C': root/'models/C_nominal.joblib'}
    for path in [source, *paths.values()]:
        if not path.is_file():
            raise FileNotFoundError(f'Required evaluation input is missing: {path}')
    return config, paths


def prepare(config, path):
    if path.exists():
        return joblib.load(path)
    builder = FeatureBuilder(config.baseline.gate, config.baseline.features)
    histories, decisions = {}, []
    for vessel, _audit in iter_observation_vessels(config.later_csv):
        approaches, _ = ApproachBuilder(config.baseline.gate).build(vessel)
        for approach in approaches:
            if approach.observations.empty:
                continue
            if (pd.Timestamp(config.evaluation_start) <= approach.observations.time.iloc[0]
                    and approach.crossing_after < pd.Timestamp(config.evaluation_end)):
                frame = builder.examples(approach)
                if frame.empty:
                    continue
                frame['split'] = 'evaluation'
                decisions.append(frame[list(METADATA_COLUMNS)])
                histories[approach.approach_id] = approach.observations
    if not decisions:
        raise ValueError('No supported evaluation approaches in the supplied source.')
    frame = pd.concat(decisions, ignore_index=True)
    frame['decision_id'] = frame.approach_id + ':' + frame.decision_time.astype(str)
    dataset = ReplayDataset(frame, histories, {})
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(dataset, path)
    return dataset


def sample_dataset(dataset, size):
    """Choose by time/duration only, never by model errors or attack outcomes."""
    if size <= 0 or size >= len(dataset.histories):
        return dataset, {'approaches': len(dataset.histories), 'total_approaches': len(dataset.histories), 'sampled': False}
    grouped = dataset.decisions.groupby('approach_id').decision_time.agg(['min', 'max'])
    duration = (grouped['max']-grouped['min']).dt.total_seconds()/60
    eligible = grouped.loc[duration.between(45, 90)].sort_values('min')
    if len(eligible) < size:
        eligible = grouped.loc[duration.ge(30)].sort_values('min')
    selected = []
    for target in pd.date_range(grouped['min'].min(), grouped['min'].max(), periods=size):
        candidates = eligible.drop(index=selected, errors='ignore')
        identity = (candidates['min']-target).abs().idxmin()
        selected.append(identity)
    scope = {'approaches': len(selected), 'total_approaches': len(dataset.histories), 'sampled': True,
             'selection': 'Fixed approaches spread across March; prefer 45–90 minute approaches. Selected by time and duration, never prediction error.',
             'approach_ids': selected}
    return ReplayDataset(dataset.decisions.loc[dataset.decisions.approach_id.isin(selected)].copy(),
                         {identity: dataset.histories[identity] for identity in selected}, scope), scope


class BatchedAnalysis(FleetAnalysis):
    """Use the existing features, mitigations and aggregations; batch only inference."""

    def __init__(self, fleet, clean=None):
        super().__init__(fleet)
        self.clean = clean or {}

    def _forecast_rows(self, settings, *, decisions=None, delivery_delay_minutes=0,
                       include_clean=True, progress=lambda *_: None):
        values = poisoning_settings(settings)
        named = dict(zip((item['id'] for item in ATTACK_CONTROLS), values))
        policy = FleetPolicy(enabled=True, position_faults=bool(named['location_drift'] or named['position_jump']),
                             noise=bool(named['sensor_deterioration']), speed_drift=bool(named['sensor_drift']))
        selected = self.decisions if decisions is None else decisions
        rows, views = [], []
        for decision in selected.sort_values(['approach_id', 'decision_time']).itertuples(index=False):
            self.fleet.extractor.snapshots.clear()
            original = decision._asdict()
            clock, arrival = original['decision_time'], original['arrival_time']
            active = any(values) and clock >= self.cutover
            row = {key: original[key] for key in ('decision_id', 'approach_id', 'mmsi')}
            row.update(decision_time=clock, arrival_time=arrival,
                       remaining_minutes=(arrival-clock).total_seconds()/60, poisoned=bool(active))
            normal = self.clean.get(str(original['decision_id']))
            row['clean'] = normal or {}
            if normal and not active and not delivery_delay_minutes:
                row['selected'] = normal
                rows.append(row)
                continue
            naive_clock = clock.tz_convert(None)
            applied = values if active else (0.,)*len(values)
            _, changed, _ = self.fleet._stream(str(original['approach_id']), applied,
                                             attack_start=self.cutover.tz_convert(None) if active else None)
            received = changed.loc[changed.time.le(naive_clock) &
                                   (changed.delivered_time + pd.Timedelta(minutes=delivery_delay_minutes)).le(naive_clock)]
            if delivery_delay_minutes:
                received = received.copy()
                received['delivered_time'] += pd.Timedelta(minutes=delivery_delay_minutes)
            original.update(decision_time=naive_clock, arrival_time=arrival.tz_convert(None))
            decision_row = pd.Series(original)
            original.update(view_row(received, decision_row, self.fleet.extractor))
            patch = feature_patch(self.fleet, received, naive_clock, policy)
            original.update(patch)
            original.update(scenario='fleet', condition='nominal', seed=self.fleet.config.evaluation_seeds[0])
            views.append(original)
            rows.append(row)
        if views:
            frame = pd.DataFrame(views)
            for column in (*OPTIMIZED_COLUMNS, *(f'raw_{column}' for column in RICH_COLUMNS)):
                if column not in frame:
                    frame[column] = np.nan
            for column in ('observation_time', 'raw_observation_time'):
                if column not in frame:
                    frame[column] = pd.NaT
            predictions = {}
            for result in predict_systems(frame, self.fleet.systems).itertuples():
                eta = unix_seconds(result.predicted_arrival_time) if result.available else None
                available = eta is not None and np.isfinite(eta)
                predictions.setdefault(str(result.decision_id), {})[result.system] = {
                    'available': bool(available), 'eta': eta if available else None,
                    'error': float(result.error_minutes) if available else None}
            for row in rows:
                if 'selected' not in row:
                    row['selected'] = predictions[str(row['decision_id'])]
                    if not row['clean'] and not any(values) and not delivery_delay_minutes:
                        row['clean'] = row['selected']
                        self.clean[str(row['decision_id'])] = row['selected']
        return rows


_analysis = None


def initialize(config, paths, dataset_path, clean_path):
    global _analysis
    threadpool_limits(1)
    systems = [PredictionSystem(name, joblib.load(path), 'guarded' if name == 'C' else 'raw')
               for name, path in paths.items()]
    for system in systems:
        if hasattr(system.predictor.regressor, 'set_params') and system.name != 'A':
            system.predictor.regressor.set_params(n_jobs=1)
    fleet = FleetService(config, joblib.load(dataset_path), systems, OfflineFeatures(config.baseline, config.guard),
                         evaluation_only=True)
    _analysis = BatchedAnalysis(fleet, joblib.load(clean_path) if clean_path.exists() else None)


def scenario(mask):
    return {control['id']: control['maximum']*.25 for bit, control in enumerate(ATTACK_CONTROLS) if mask & (1 << bit)}


def export_one(task):
    mask, directory = task
    path = directory/f'{mask:03d}.json'
    if not path.exists():
        data = _analysis.monthly(scenario(mask))
        data['scope'] = _analysis.fleet.dataset.manifest
        if data['scope'].get('sampled'):
            data['source'] += f" · fixed sample of {data['scope']['approaches']}/{data['scope']['total_approaches']} March approaches"
            data['caveat'] = 'Small demo sample; not a full-month accuracy benchmark. ' + data['caveat']
        temporary = path.with_suffix('.partial')
        temporary.write_text(json.dumps(data, allow_nan=False, separators=(',', ':')))
        temporary.replace(path)
    return mask


def verify_scalar():
    """Check actual joint forecasts against the existing per-checkpoint product path."""
    after = _analysis.decisions.loc[_analysis.decisions.decision_time.ge(_analysis.cutover)]
    subset = after.iloc[[0, len(after)//2, len(after)-1]].copy()
    checks = 0
    for mask in (0, 2, 4, 8, 16, 32, 64, 128, 6, 24, 80, 255):
        settings = scenario(mask)
        rows = _analysis._forecast_rows(settings, decisions=subset)
        policy = FleetPolicy(enabled=True, position_faults=bool(settings.get('location_drift') or settings.get('position_jump')),
                             noise=bool(settings.get('sensor_deterioration')), speed_drift=bool(settings.get('sensor_drift')))
        for row in rows:
            decision = subset.loc[subset.decision_id.eq(row['decision_id'])].iloc[0].copy()
            clock = decision.decision_time.tz_convert(None)
            _, changed, _ = _analysis.fleet._stream(str(decision.approach_id), poisoning_settings(settings),
                                                   attack_start=_analysis.cutover.tz_convert(None) if mask else None)
            received = changed.loc[changed.time.le(clock) & changed.delivered_time.le(clock)]
            decision['decision_time'], decision['arrival_time'] = clock, decision.arrival_time.tz_convert(None)
            _analysis.fleet.extractor.snapshots.clear()
            expected = _analysis.fleet._predict(received, decision, policy)[0]
            for model, prediction in expected.items():
                actual = row['selected'][model]
                if prediction['available'] != actual['available']:
                    raise AssertionError(f'Support mismatch: {mask}, {row["decision_id"]}, {model}')
                if prediction['available']:
                    np.testing.assert_allclose([actual['eta'], actual['error']],
                                               [prediction['eta'], prediction['error']], rtol=0, atol=1e-6)
                checks += 1
    print(f'Verified {checks} model forecasts against scalar product inference.', flush=True)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SCIENCE/'Optimized_Model/config_data_eval.json')
    parser.add_argument('--source', type=Path, default=SCIENCE.parent/'data/hampton_roads_march_2024.csv')
    parser.add_argument('--output', type=Path, default=SCIENCE.parent/'Frontend/tracking/data/scenarios.json')
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--approaches', type=int, default=6, help='Fixed temporal sample; use 0 for the complete month.')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    config, paths = read_inputs(args.config.resolve(), args.source.resolve())
    provenance = {'source_sha256': file_digest(config.later_csv), 'models': {k: file_digest(p) for k,p in paths.items()},
                  'inference': inference_implementation(), 'exporter_sha256': file_digest(Path(__file__)),
                  'repairs': {str(path.relative_to(SCIENCE)): file_digest(path) for directory in ('mitigation', 'attacks')
                              for path in sorted((SCIENCE/directory).rglob('*.py'))},
                  'aggregation_sha256': file_digest(SCIENCE/'Optimized_Model/fleet_analysis.py'),
                  'evaluation_config_sha256': file_digest(args.config),
                  'fleet_sha256': file_digest(SCIENCE/'Optimized_Model/fleet.py'),
                  'fleet_mitigations_sha256': file_digest(SCIENCE/'Optimized_Model/fleet_mitigations.py'),
                  'views_sha256': file_digest(SCIENCE/'Optimized_Model/views.py'),
                  'baseline_config_sha256': file_digest((args.config.parent/json.loads(args.config.read_text())['baseline_config']).resolve()),
                  'attacks': list(ATTACK_CONTROLS), 'start': config.evaluation_start, 'end': config.evaluation_end,
                  'seed': config.evaluation_seeds[0], 'sample_size': args.approaches}
    signature = sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()
    cache = SCIENCE/'artifacts/static_graphs'/signature[:16]
    dataset_path, clean_path = cache/'dataset.joblib', cache/'clean.joblib'
    source_key = sha256(json.dumps({key: provenance[key] for key in ('source_sha256', 'baseline_config_sha256', 'start', 'end')}, sort_keys=True).encode()).hexdigest()[:16]
    source_path = SCIENCE/'artifacts/static_graphs'/f'source-{source_key}.joblib'
    dataset, scope = sample_dataset(prepare(config, source_path), args.approaches)
    cache.mkdir(parents=True, exist_ok=True)
    joblib.dump(dataset, dataset_path)
    print(f'{len(dataset.histories)}/{scope["total_approaches"]} approaches; {len(dataset.decisions)} decisions; cache {cache}', flush=True)
    if args.prepare_only:
        return
    initialize(config, paths, dataset_path, clean_path)
    print(f'{len(_analysis.decisions)} chart checkpoints', flush=True)
    checks = verify_scalar()
    if args.verify_only:
        return
    if not clean_path.exists():
        _analysis._forecast_rows({})
        joblib.dump(_analysis.clean, clean_path)
    export_one((0, cache))
    executor = ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                                   initargs=(config, paths, dataset_path, clean_path))
    futures = []
    try:
        futures = [executor.submit(export_one, (mask, cache)) for mask in range(1, 256)]
        for count, future in enumerate(as_completed(futures), 1):
            print(f'{count}/255: scenario {future.result():03d}', flush=True)
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown()
    stress_path = cache/'stress.json'
    if not stress_path.exists():
        stress = _analysis.stress()
        stress['scope'] = scope
        if scope.get('sampled'):
            stress['methodology'] += f" Fixed demo sample of {scope['approaches']}/{scope['total_approaches']} approaches; not a full-month benchmark."
        stress_path.write_text(json.dumps(stress, allow_nan=False, separators=(',', ':')))
    bundle = {'version': 1, 'strength_fraction': .25, 'controls': list(ATTACK_CONTROLS),
              'generated_at': datetime.now(timezone.utc).isoformat(), 'provenance': provenance,
              'scope': scope,
              'verification': {'scalar_forecasts_checked': checks, 'absolute_tolerance': 1e-6},
              'scenarios': {str(mask): json.loads((cache/f'{mask:03d}.json').read_text()) for mask in range(256)},
              'stress': json.loads(stress_path.read_text())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.partial')
    temporary.write_text(json.dumps(bundle, allow_nan=False, separators=(',', ':')))
    temporary.replace(args.output)
    print(f'Wrote {args.output} ({args.output.stat().st_size:,} bytes)', flush=True)


if __name__ == '__main__':
    main()

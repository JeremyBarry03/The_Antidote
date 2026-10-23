"""Cache full-cohort chart results from actual frozen forecasts, one scenario at a time."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import export as backend
from Optimized_Model.fleet_analysis import FleetAnalysis


def initialize(config, paths, dataset, clean):
    backend.initialize(config, paths, dataset, clean)
    analysis = backend._analysis
    # Use every archived five-minute checkpoint for daily/weekly accuracy too.
    analysis.monthly_decisions = analysis.evaluation_decisions.copy()
    analysis.monthly_ids = set(analysis.monthly_decisions.decision_id.astype(str))
    analysis.decisions = analysis.evaluation_decisions.copy()


def forecast(task):
    mask, decisions = task
    return backend._analysis._forecast_rows(backend.scenario(mask), decisions=decisions)


def aggregate(analysis, rows, settings):
    # Reuse the production aggregation contract on already computed forecasts.
    original = analysis._forecast_rows
    analysis._forecast_rows = lambda *_args, **_kwargs: rows
    try:
        return FleetAnalysis.monthly(analysis, settings)
    finally:
        analysis._forecast_rows = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--masks', default='0,1,2,4,8,16,32,64,128,255')
    parser.add_argument('--output', type=Path, default=backend.SCIENCE.parent/'Frontend/tracking/data/full-month.json')
    args = parser.parse_args()
    masks = [0, *[int(value) for value in args.masks.split(',') if int(value) != 0]]
    if args.workers < 1 or any(mask < 0 or mask > 255 for mask in masks):
        raise ValueError('Use positive workers and scenario masks from 0 to 255.')
    config_path = backend.SCIENCE/'Optimized_Model/config_data_eval.json'
    config, paths = backend.read_inputs(config_path, backend.SCIENCE.parent/'data/hampton_roads_march_2024.csv')
    source_bundle = paths['C'].parents[1]/'serving_replay.joblib'
    provenance = {'source_sha256': backend.file_digest(config.later_csv),
                  'dataset_sha256': backend.file_digest(source_bundle),
                  'models': {name: backend.file_digest(path) for name, path in paths.items()},
                  'config_sha256': backend.file_digest(config_path),
                  'inference': backend.inference_implementation(),
                  'code': {str(path.relative_to(backend.SCIENCE)): backend.file_digest(path)
                           for path in [Path(__file__), Path(backend.__file__),
                                        backend.SCIENCE/'Optimized_Model/fleet_analysis.py',
                                        backend.SCIENCE/'Optimized_Model/fleet.py',
                                        backend.SCIENCE/'Optimized_Model/fleet_mitigations.py',
                                        *sorted((backend.SCIENCE/'mitigation').rglob('*.py')),
                                        *sorted((backend.SCIENCE/'attacks').rglob('*.py'))]}}
    signature = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:16]
    cache = backend.SCIENCE/'artifacts/full_graphs'/signature
    cache.mkdir(parents=True, exist_ok=True)
    dataset_path, clean_path = cache/'dataset.joblib', cache/'clean.joblib'
    dataset = joblib.load(source_bundle)
    joblib.dump(dataset, dataset_path)
    initialize(config, paths, dataset_path, clean_path)
    analysis = backend._analysis
    scope = {'approaches': len(dataset.histories), 'total_approaches': len(dataset.histories), 'sampled': False}
    bundle = {'version': 1, 'strength_fraction': .25, 'controls': list(backend.ATTACK_CONTROLS),
              'scope': scope, 'provenance': provenance, 'scenarios': {},
              'scheduled_checkpoints': len(analysis.evaluation_decisions)}
    checks = backend.verify_scalar()
    bundle['verification'] = {'scalar_forecasts_checked': checks, 'absolute_tolerance': 1e-6}
    print(f'Full cohort: {scope["approaches"]} approaches, {len(analysis.decisions)} checkpoints.', flush=True)
    for mask in dict.fromkeys(masks):
        started = time.perf_counter()
        row_path = cache/f'{mask:03d}-rows.joblib'
        if row_path.exists():
            rows = joblib.load(row_path)
        else:
            groups = list(analysis.decisions.groupby('approach_id', sort=False))
            rows = []
            with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                                     initargs=(config, paths, dataset_path, clean_path)) as pool:
                futures = [pool.submit(forecast, (mask, group)) for _, group in groups]
                for done, future in enumerate(as_completed(futures), 1):
                    rows.extend(future.result())
                    if done % 25 == 0 or done == len(groups):
                        print(f'Scenario {mask:03d}: {done}/{len(groups)} approaches', flush=True)
            joblib.dump(rows, row_path)
        if mask == 0:
            clean = {row['decision_id']: row['selected'] for row in rows}
            analysis.clean = clean
            joblib.dump(clean, clean_path)
        data = aggregate(analysis, rows, backend.scenario(mask))
        data['scope'] = scope
        data['methodology'] = ('Daily summaries use all original five-minute checkpoints, with equal approach weight. '
                               'Convergence uses disjoint five-minute bins; stability uses seven matched offsets.')
        data['evaluation_checkpoints'] = len(rows)
        data['unique_convergence_checkpoints'] = len(analysis.convergence_decisions)
        bundle['scenarios'][str(mask)] = data
        bundle['generated_at'] = datetime.now(timezone.utc).isoformat()
        bundle['completed_masks'] = [int(key) for key in bundle['scenarios']]
        bundle['requested_masks'] = list(dict.fromkeys(masks))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix('.partial')
        temporary.write_text(json.dumps(bundle, allow_nan=False, separators=(',', ':')), encoding='utf-8')
        temporary.replace(args.output)
        print(f'Saved {mask:03d}: {len(rows)} checkpoints, {len(data["days"])} days, '
              f'{data["insights"]["stability"]["instances"]} stability approaches; '
              f'{time.perf_counter()-started:.1f}s.', flush=True)


if __name__ == '__main__':
    main()

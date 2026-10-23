"""Cache every joint fault combination on a fixed, date-stratified March sample."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import pandas as pd
import export as backend
from full_month import aggregate, initialize


def select_dataset(dataset):
    """One distinct approach per observed March day, chosen without model outcomes.

    Prefer 60-90 minute approaches to retain both the first 30 minutes and final
    hour. Within a day prefer a previously unselected vessel, then duration near
    60 minutes, then stable ID. Fall back to the longest approach if necessary.
    """
    frame = dataset.decisions.copy()
    frame['decision_time'] = pd.to_datetime(frame.decision_time, utc=True)
    grouped = frame.groupby('approach_id').agg(first=('decision_time', 'min'),
        last=('decision_time', 'max'), mmsi=('mmsi', 'first'))
    grouped['duration'] = (grouped['last']-grouped['first']).dt.total_seconds()/60
    grouped['day'] = grouped['first'].dt.normalize()
    selected, vessels = [], set()
    for _, day in grouped.groupby('day', sort=True):
        preferred = day.loc[day.duration.between(60, 90)].copy()
        if preferred.empty:
            preferred = day.loc[day.duration.ge(30)].copy()
        if preferred.empty:
            preferred = day.copy()
        preferred['repeat'] = preferred.mmsi.astype(str).isin(vessels)
        preferred['distance'] = (preferred.duration-60).abs()
        preferred['identity'] = preferred.index.astype(str)
        identity = preferred.sort_values(['repeat', 'distance', 'identity']).index[0]
        selected.append(identity)
        vessels.add(str(grouped.loc[identity, 'mmsi']))
    scope = {'sampled': True, 'approaches': len(selected), 'total_approaches': len(dataset.histories),
        'selection': 'One approach per observed start date, preferring distinct vessels and 60-90 minute duration; no prediction outcomes used.',
        'approach_ids': selected}
    return backend.ReplayDataset(dataset.decisions.loc[dataset.decisions.approach_id.isin(selected)].copy(),
        {identity: dataset.histories[identity] for identity in selected}, scope), scope


def export_case(task):
    mask, cache, scope = task
    output = cache/f'{mask:03d}.json'
    if output.exists():
        return mask, 0.
    started = time.perf_counter()
    analysis = backend._analysis
    rows = analysis._forecast_rows(backend.scenario(mask))
    data = aggregate(analysis, rows, backend.scenario(mask))
    data.update(scope=scope, evaluation_checkpoints=len(rows),
        methodology='Daily means use original five-minute checkpoints with equal approach weight. Fixed date-stratified sample, not a full-cohort benchmark.',
        source='Historical AIS replay · date-stratified March sample')
    data['caveat'] = 'Sampled approaches; not a full-month accuracy benchmark. '+data['caveat']
    output.with_suffix('.partial').write_text(json.dumps(data, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    output.with_suffix('.partial').replace(output)
    return mask, time.perf_counter()-started


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--benchmark', action='store_true')
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError('workers must be positive')
    output = backend.SCIENCE.parent/'Frontend/tracking/data/scenarios.json'
    full = json.loads((output.parent/'full-month.json').read_text())
    # Reuse only raw forecasts whose exact inputs and inference code still match.
    for relative, digest in full['provenance']['code'].items():
        raw = (backend.SCIENCE/relative).read_bytes()
        if digest not in {hashlib.sha256(raw).hexdigest(), hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()}:
            raise ValueError(f'Full cache code changed: {relative}')
    config, paths = backend.read_inputs(backend.SCIENCE/'Optimized_Model/config_data_eval.json',
        backend.SCIENCE.parent/'data/hampton_roads_march_2024.csv')
    if backend.file_digest(config.later_csv) != full['provenance']['source_sha256']:
        raise ValueError('Source differs from full cache')
    for name, path in paths.items():
        if backend.file_digest(path) != full['provenance']['models'][name]:
            raise ValueError(f'Model differs from full cache: {name}')
    source = paths['C'].parents[1]/'serving_replay.joblib'
    if backend.file_digest(source) != full['provenance']['dataset_sha256']:
        raise ValueError('Checkpoint dataset differs from full cache')
    dataset, scope = select_dataset(joblib.load(source))
    provenance = {**full['provenance'], 'sample': scope, 'representative_exporter_sha256': backend.file_digest(Path(__file__))}
    signature = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:16]
    cache = backend.SCIENCE/'artifacts/representative_graphs'/signature
    cache.mkdir(parents=True, exist_ok=True)
    dataset_path, clean_path = cache/'dataset.joblib', cache/'clean.joblib'
    joblib.dump(dataset, dataset_path)
    full_signature = hashlib.sha256(json.dumps(full['provenance'], sort_keys=True).encode()).hexdigest()[:16]
    full_cache = backend.SCIENCE/'artifacts/full_graphs'/full_signature
    ids = set(dataset.decisions.decision_id.astype(str))
    clean_rows = [row for row in joblib.load(full_cache/'000-rows.joblib') if row['decision_id'] in ids]
    joblib.dump({row['decision_id']: row['selected'] for row in clean_rows}, clean_path)
    initialize(config, paths, dataset_path, clean_path)
    checks = backend.verify_scalar()
    print(f'Sample: {scope["approaches"]} approaches, {len(ids)} checkpoints, {backend._analysis.evaluation_decisions.mmsi.nunique()} vessels; {cache}', flush=True)
    for mask in full['completed_masks']:
        path = cache/f'{mask:03d}.json'
        if path.exists():
            continue
        rows = [row for row in joblib.load(full_cache/f'{mask:03d}-rows.joblib') if row['decision_id'] in ids]
        data = aggregate(backend._analysis, rows, backend.scenario(mask))
        data.update(scope=scope, evaluation_checkpoints=len(rows),
            source='Historical AIS replay · date-stratified March sample',
            methodology='Daily summaries use original five-minute checkpoints, with equal approach weight. Fixed date-stratified sample, not a full-cohort benchmark.')
        data['caveat'] = 'Sampled approaches; not a full-month accuracy benchmark. '+data['caveat']
        path.write_text(json.dumps(data, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    masks = [mask for mask in range(256) if not (cache/f'{mask:03d}.json').exists()]
    if args.benchmark:
        masks = masks[:8]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
        initargs=(config, paths, dataset_path, clean_path)) as pool:
        futures = [pool.submit(export_case, (mask, cache, scope)) for mask in masks]
        for done, future in enumerate(as_completed(futures), 1):
            mask, elapsed = future.result()
            print(f'{done}/{len(masks)}: mask {mask:03d}, {elapsed:.1f}s; wall {time.perf_counter()-started:.1f}s', flush=True)
    if args.benchmark:
        print('Benchmark complete; published bundle unchanged.', flush=True)
        return
    bundle = {'version': 1, 'strength_fraction': .25, 'controls': list(backend.ATTACK_CONTROLS),
        'generated_at': datetime.now(timezone.utc).isoformat(), 'scope': scope, 'provenance': provenance,
        'verification': {'scalar_forecasts_checked': checks, 'absolute_tolerance': 1e-6},
        'scenarios': {str(mask): json.loads((cache/f'{mask:03d}.json').read_text()) for mask in range(256)}}
    temporary = output.with_suffix('.partial')
    temporary.write_text(json.dumps(bundle, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(output)
    print(f'Published all 256 scenarios: {output}', flush=True)


if __name__ == '__main__':
    main()

"""Recalculate only stability in the saved bundle using frozen 60-minute forecasts."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import joblib
import pandas as pd
import export as backend


def calculate(mask):
    analysis = backend._analysis
    rows = analysis._forecast_rows(backend.scenario(mask), decisions=analysis.sequence_decisions)
    sequence, stability = analysis._sequences(rows)
    return mask, sequence, stability


def main():
    output = backend.SCIENCE.parent/'Frontend/tracking/data/scenarios.json'
    bundle = json.loads(output.read_text(encoding='utf-8'))
    config, paths = backend.read_inputs(backend.SCIENCE/'Optimized_Model/config_data_eval.json',
                                      backend.SCIENCE.parent/'data/hampton_roads_march_2024.csv')
    assert backend.file_digest(config.later_csv) == bundle['provenance']['source_sha256']
    for model, path in paths.items():
        assert backend.file_digest(path) == bundle['provenance']['models'][model]
    source = joblib.load(paths['C'].parents[1]/'serving_replay.joblib')
    identities = set(bundle['scope']['approach_ids'])
    dataset = backend.ReplayDataset(source.decisions.loc[source.decisions.approach_id.isin(identities)].copy(),
                                   {identity: source.histories[identity] for identity in identities}, bundle['scope'])
    assert set(dataset.histories) == identities
    signature = sha256((json.dumps(bundle['provenance'], sort_keys=True)
                        + backend.file_digest(backend.SCIENCE/'Optimized_Model/fleet_analysis.py')).encode()).hexdigest()[:16]
    cache = backend.SCIENCE/'artifacts/stability_extension'/signature
    cache.mkdir(parents=True, exist_ok=True)
    dataset_path, clean_path = cache/'dataset.joblib', cache/'clean.joblib'
    joblib.dump(dataset, dataset_path)
    backend.initialize(config, paths, dataset_path, clean_path)
    backend._analysis._forecast_rows({})
    joblib.dump(backend._analysis.clean, clean_path)
    # Validate batched frozen inference against the production per-checkpoint path.
    checks = backend.verify_scalar()
    with ProcessPoolExecutor(max_workers=8, initializer=backend.initialize,
                             initargs=(config, paths, dataset_path, clean_path)) as pool:
        futures = [pool.submit(calculate, mask) for mask in range(256)]
        for count, future in enumerate(as_completed(futures), 1):
            mask, sequence, stability = future.result()
            scenario = bundle['scenarios'][str(mask)]
            scenario['insights']['stability'] = stability
            scenario['sequence'] = sequence
            if count % 16 == 0:
                print(f'{count}/256 scenarios recalculated', flush=True)
    bundle['stability_extension'] = {
        'minutes': 60, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'aggregation_sha256': backend.file_digest(backend.SCIENCE/'Optimized_Model/fleet_analysis.py'),
        'exporter_sha256': backend.file_digest(Path(__file__)), 'scalar_forecasts_checked': checks,
        'coverage': 'Same complete matched approaches at all thirteen offsets; shorter sequences excluded.'}
    temporary = output.with_suffix('.partial')
    temporary.write_text(json.dumps(bundle, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(output)
    print(f'Updated {output}', flush=True)


if __name__ == '__main__':
    main()

"""Temporal sampling must be fixed before examining forecast outcomes."""
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/static_graphs'))
from representative import select_dataset
from Optimized_Model.dataset import ReplayDataset


def test_sample_covers_dates_prefers_distinct_vessels_and_ignores_errors():
    rows, histories = [], {}
    for identity, date, vessel, duration in [
        ('a', '2024-03-01', '1', 60), ('b', '2024-03-01', '2', 90),
        ('c', '2024-03-02', '1', 60), ('d', '2024-03-02', '3', 75),
        ('e', '2024-03-03', '4', 20),
    ]:
        histories[identity] = pd.DataFrame()
        for offset in range(0, duration+1, 5):
            rows.append(dict(approach_id=identity,mmsi=vessel,
                decision_time=pd.Timestamp(date)+pd.Timedelta(minutes=offset),
                decision_id=f'{identity}:{offset}',error=1000 if identity in ('a','d') else 0))
    dataset = ReplayDataset(pd.DataFrame(rows), histories, {})
    sample, scope = select_dataset(dataset)
    assert scope['approach_ids'] == ['a', 'd', 'e']
    assert scope['total_approaches'] == 5
    assert scope['sampled'] is True
    assert set(sample.histories) == {'a', 'd', 'e'}
    changed = dataset.decisions.sample(frac=1, random_state=42).copy()
    changed['error'] = -changed['error']
    assert select_dataset(ReplayDataset(changed, histories, {}))[1] == scope

"""Chart counts and MAE must reflect distinct real prediction checkpoints."""
from Optimized_Model.fleet_analysis import FleetAnalysis
import pandas as pd


def test_stability_uses_one_complete_hour_cohort_and_five_minute_revisions():
    analysis = object.__new__(FleetAnalysis)
    rows = []
    for identity, duration in [('complete', 60), ('short', 30), ('unsupported', 60)]:
        for minute in range(0, duration + 1, 5):
            prediction = {model: {'available': identity != 'unsupported' or minute != 55,
                                  'eta': 1_000_000 + minute * 60}
                          for model in ('A', 'B', 'C')}
            rows.append({'approach_id': identity, 'mmsi': identity,
                         'decision_time': pd.Timestamp('2024-03-01') + pd.Timedelta(minutes=minute),
                         'selected': prediction, 'clean': prediction})
    _, stability = analysis._sequences(rows)
    assert [sample['minute'] for sample in stability['samples']] == list(range(0, 61, 5))
    assert stability['instances'] == 1
    assert stability['short_or_incomplete'] == 1
    assert stability['unsupported'] == 1
    assert all(sample['instances'] == 1 for sample in stability['samples'])
    assert stability['samples'][-1]['models']['C']['movement']['mean'] == 60
    assert stability['samples'][-1]['models']['C']['updates']['mean'] == 5


def test_convergence_never_cancels_opposite_errors_or_counts_a_checkpoint_twice():
    analysis = object.__new__(FleetAnalysis)
    rows = []
    for minute, error in [(0, 3.), (1, 10.), (2, -10.), (57, 4.)]:
        prediction = {name: {'available': True, 'error': error} for name in ('A', 'B', 'C')}
        rows.append({'approach_id': 'same-approach', 'remaining_minutes': minute,
                     'selected': prediction, 'clean': prediction})
    result = analysis._convergence(rows)
    assert result['scheduled_decisions'] == 4
    assert result['matched_decisions'] == 4
    last_bin = next(sample for sample in result['samples'] if sample['minute'] == 5)
    assert last_bin['models']['C']['mae'] == 10.
    assert last_bin['models']['C']['unavailable_decisions'] == 0
    arrival = next(sample for sample in result['samples'] if sample['minute'] == 0)
    assert arrival['scheduled_decisions'] == 1
    assert arrival['models']['C']['mae'] == 3.

"""Chart counts and MAE must reflect distinct real prediction checkpoints."""
from Optimized_Model.fleet_analysis import FleetAnalysis


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

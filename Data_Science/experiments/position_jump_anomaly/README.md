# Position anomaly-only evaluation

This replaces the deleted position-correction experiment. No model is retrained,
no input features change and no report is filtered or repaired. It evaluates
warnings on simulated disruption, not ETA improvement.

```text
python experiments/position_jump_anomaly/calibrate.py
python experiments/position_jump_anomaly/run.py
python -m pytest -q
```

Calibration fixes the empirical 99.5th-percentile innovation-score threshold
using March navigation only, equally weighting vessels and approaches within
vessel. Config and calibration JSON must match exactly before evaluation.
The normalizing position/velocity scales are fixed experimental settings.
April is a previously inspected follow-up cohort, not a pristine holdout.

Evaluation uses the existing 36 March development approaches / 757 decisions
and 112 April approaches / 2,402 decisions. It compares original copied feeds
and simulated 2 km mean / 0.2 km SD jumps at 10%, 20%, 25%, 50% and 100%, with
seeds 4201-4203. A separate 100% burst begins after 20 minutes and lasts 15.
These percentages are stress settings, not observed real-world failure rates.

Pair detection considers a pair affected if EITHER endpoint was injected.
A return from a corrupted fix to an unaltered fix can correctly produce an
inconsistency warning. Unassessed pairs are excluded from pair detection rates.
Reference-pair alerts are a false-alarm proxy, not independent proof of correct
GPS. Decision windows last five minutes; their alert rates are reported separately.
First detection delay starts at the first affected eligible pair and is measured
only among profiles with a detection. Detection counts accompany latency.

The fast pair cache is allowed only when delivery equals observation time and
pairs use adjacent previous/current measurements. Public detector first/last
prefixes are checked independently per scenario/approach. Unit tests also cover
late arrivals, future independence, missing fields and duplicate/conflicting fixes.
Attack labels join only AFTER observable detection computations.

A saved-artifact API regression replays the prior severe 50% failure with the
warning off/on. All three model cards, received histories and references must
match exactly, and a position warning must trigger. That check measures unchanged
ETA behavior; it does not rerun model accuracy for every warning setting because
this detector supplies no model input. Further service tests capture complete
inference frames and confirm equality before/after enabling warnings.

Protocol, calibration, validation and Markdown results stay reviewable. CSV
pair/decision/summary outputs are local and ignored. Protected data, saved models,
other mitigations, attacks, inference modules and frontend files must retain
their hashes. The old correction estimator and all its results are deleted.

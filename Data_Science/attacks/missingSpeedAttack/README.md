# MissingSpeedAttack

Simulates unavailable speed-over-ground measurements by setting selected `sog`
values to missing (`NaN`). It retains every report, position, course, measurement
timestamp, delivery timestamp, and reference crossing. It does not replace missing
speed with zero or force any particular ETA error.

```python
from attacks import MissingSpeedAttack, MissingSpeedConfig

attack = MissingSpeedAttack(MissingSpeedConfig(
    affected_fraction=0.25,
    seed=42,
    target_mmsi=None,  # Optional nine-digit string; None targets the supplied feed.
))
stream = attack.apply(reports)
received = stream.available(decision_time)
```

The source DataFrame is not mutated. Speed must already be numeric. Selection is
a deterministic hash of seed, MMSI, and measurement timestamp, so appending future
records cannot change past selections. Fraction zero is a no-op. Fraction one
removes every available speed. Naturally missing speeds stay missing and do not
count as injected faults. Realized rates vary in short histories. Selection is per
original report, not conditioned on stops, turns, or arrival errors.

The result reuses `ReportStream`. Its separate modification log contains
`original_sog`, `fault_applied`, `action`, attack name, seed, report identity and
timestamps. Only a newly removed speed has `fault_applied=True` and
`action="speed_removed"`. Audit fields must never enter model features. There is
no training, file access, model loading or scoring in the attack class.

## Existing handling

Model B already excludes missing values from recent speed summaries, marks
insufficient speed history with `history_missing`, and uses its trained imputer
for missing features. Missing speed does not mean stopped. The experiment keeps
this existing behavior and separately tests zero-filling as a bad-cleaning control.
No model is retrained and no new mitigation is claimed.

## Backend integration

```text
GET /api/attacks/missing-speed?decision=DECISION_ID&affected_fraction=0.25&seed=42&reveal=true&inspect=true
```

Optional `target_mmsi` scopes masking. The response contains paired `original` and
`attacked` snapshots with A/B/C cards at the same decision time. Crossing outcomes
and errors are hidden unless `reveal=true`. Missing received speeds serialize to
JSON `null`. Inspection is audience-only and excludes future reports.

`attacked.attack.injected_missing_speed_reports_so_far` counts newly masked speeds
measured by the replay clock. `withheld_reports_so_far` remains zero: reports still
arrive. Invalid settings return HTTP 400. The old calibration policy does not accept
this unevaluated custom condition. Visible controls and all frontend changes are
left to the frontend owner.

## Test and evaluate

From `Data_Science`, using the existing project environment:

```powershell
python -m pytest tests/test_missing_speed_attack.py tests/test_reporting_gap_attack.py tests/test_optimized_model.py -q
python experiments/missing_speed_attack/run.py
```

The evaluator tests 10%, 25%, 50% and 100% removal. These are synthetic stress rates,
substantially higher than the observed source missing-speed rate. Partial selection
uses three fixed seeds; complete masking runs once. All April evaluation approaches
and scheduled decisions are included. It saves paired predictions, an injection
audit, MAE/MdAE, uncertainty, settings and checks under
`experiments/missing_speed_attack/results/`.

`all_attacks_summary.csv` and `REPORT.md` also calculate ReportingGapAttack MdAE from
its saved predictions, validating that their original forecasts match current B.
The original gap predictions are not altered. DuplicateReportAttack remains
removed and is excluded. The evaluator requires the existing reporting-gap
experiment results.

MAE gives each approach equal weight; MdAE is the median absolute error across
decision/seed pairs. Reporting gaps occur in bounded windows, whereas speed masking
is distributed over an approach; compare matched reference errors and exposure
before ranking attacks. All results concern analytical gate crossing, not docking.

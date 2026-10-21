# MissingCourseAttack

Simulates unavailable course-over-ground values by masking selected `cog` entries
with `NaN`. It preserves positions, speeds, all reports and their timing, and the
reference crossing. Course over ground is not the separate AIS heading field.

```python
from attacks import MissingCourseAttack, MissingCourseConfig

attack = MissingCourseAttack(MissingCourseConfig(
    affected_fraction=0.25,
    seed=42,
    target_mmsi=None,  # Optional nine-digit MMSI string.
))
stream = attack.apply(reports)
received = stream.available(decision_time)
```

Missing course is different from a real course of zero degrees (north). The attack
never zero-fills. The current B path encodes valid course as sine/cosine, preserves
missingness, and applies its existing trained feature imputer. No model is changed
or retrained. A separate evaluation control deliberately fills missing course with
zero before encoding to measure that processing error.

Selection hashes seed, MMSI and measurement time. Earlier selections remain stable
when future records are appended. Naturally missing courses remain missing and do
not count as injected faults. Prevalence zero is a no-op, and one masks every
available course for the targeted records. Short histories can have a realized
rate different from the requested fraction.

The implementation composes shared numeric-field masking with the existing
`BaseAttack`/`ReportStream` contract. Speed and course remain separate concrete
attacks with their own names and configuration types. Inputs are copied, and the
separate audit contains `original_cog`, `fault_applied`, `action="course_removed"`
for changed entries, identity, timing, name and seed. Audit truth never enters
model features. Numeric course and parsed, compatible timestamps are required.

## Backend API

```text
GET /api/attacks/missing-course?decision=DECISION_ID&affected_fraction=0.25&seed=42&reveal=true&inspect=true
```

Optional `target_mmsi` scopes masking. The response contains paired `original` and
`attacked` A/B/C snapshots at the same clock and crossing reference. Outcomes and
errors remain hidden unless `reveal=true`. `received_history` now includes `cog`;
missing values serialize as JSON null. Inspection excludes future records and is
audience-only. `attack.injected_missing_course_reports_so_far` counts newly masked
courses; withheld and missing-speed injection counts remain zero. Invalid settings
return HTTP 400. The saved review policy does not accept this custom condition.

No frontend code or controls are changed. Use successive decision IDs with the same
parameters for playback. Existing aggregate scenario evidence must not be relabeled
as a result of a custom course attack.

## Tests and Model B evaluation

From `Data_Science`:

```powershell
python -m pytest tests -q
python experiments/missing_course_attack/run.py
```

The evaluation uses all 112 April approaches and 2402 decision times. It tests
10%, 25%, 50% and 100% removal, with three fixed seeds for partial removal and one
seed-independent complete-removal run. These are stress rates, not observed field
failure rates. It saves results under `experiments/missing_course_attack/results/`.

Only two original B features depend on course: the latest course's sine and cosine.
The evaluator reuses other columns, checks exact equivalence with the standard
extractor at fixed first/middle/last decisions in every case, and performs actual
inference with the frozen B model. MAE weights approaches equally; MdAE pools
decision/seed absolute errors. Arrival means the analytical crossing, not docking.

`all_attacks_summary.csv` combines current course results with the saved missing-speed
and reporting-gap results after verifying their model hash and original forecasts.
Original result files remain unchanged. DuplicateReportAttack remains removed.

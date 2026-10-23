# Missing-course mitigation for frozen Antidote

`MissingCourseMitigation(BaseMitigation)` mirrors Missing Speed's causal
`apply`, `repair_reports`, typed configuration/result and opt-in adapter structure.
Both use the same position fit in `mitigation/trusted_motion.py` and explicit
feature reconstruction in `mitigation/navigation_features.py`. No speed
mitigation settings or equations change. The speed regression script recomputes
every saved March/April case and verifies its predictions and repair counts.

## Math

Fit local east/north coordinates against actual seconds using least squares:
`E(t)=aE+vE*t`, `N(t)=aN+vN*t`. Speed is `hypot(vE,vN)/(1852/3600)` knots.
Nautical course is `degrees(atan2(vE,vN)) % 360`: north 0, east 90, south 180,
west 270. Circular differences use `abs((a-b+180)%360-180)`; 359 and 1 differ
by two degrees. No arithmetic averaging of course angles is introduced.

The shared checks are unchanged from Missing Speed: five-minute trailing
window; three distinct fixes spanning at least 60 seconds; no internal gap over
120 seconds; maximum 60 knots; RMS fit residual at most 50 m; maximum segment
velocity-vector disagreement with the fit at most two knots. Course adds:

- Fitted and every segment speed at least one knot.
- At least 30 m net position displacement.
- No segment direction more than 20 degrees from the fitted direction.

These are initial research settings fixed before evaluation, not calibrated
production thresholds or measured failure rates. A trailing fit estimates recent
average course over ground, not verified instantaneous COG or the vessel's bow
heading. Coherent GPS errors, turns,
and changes between reports remain limitations.

## Data and inference boundaries

Valid COG in [0,360) stays untouched, including zero (valid north). NaN, negative,
nonfinite or AIS-unavailable 360 values are eligible. Unsupported estimates stay
missing. The adapter normalizes invalid COG to NaN on its private input before
circular aggregation, preventing unavailable 360 from becoming apparently valid
north. Original source reports and received-history output are never changed.

Each historical report is repaired using only earlier/equal measurement times
available at its own delivery clock. Later positions do not backfill earlier
course. Exact duplicates do not create evidence; conflicting times, gaps, jumps,
slow/stationary motion and inconsistent direction fail reconstruction. SOG is
not required for the pure geometric estimator, and it is never repaired here.

The frozen-C adapter guards positions once, then recomputes only course sine,
course cosine, course dispersion, recent turn and velocity disagreement.
Original missing-course fraction, `history_missing`, all speed/position features,
timestamps and guard diagnostics remain intact. Audit and labels are separate
from the model's 34 features. The saved trees/imputer are not retrained. Their
numeric missing indicators still follow the effective features, so preserving
provenance alone does not provide calibrated uncertainty.

## Optional API

```
GET /api/attacks/missing-course?decision=<id>&affected_fraction=0.5&seed=4201&mitigate_missing_course=true
```

Default is false. Both original and attacked arms use the requested setting.
Only C's guarded features change; Poly and ordinary XGBoost keep their raw inputs.
Responses add `missing_course_mitigation` with repair/unsupported counts and audit.
Unreconstructed course follows the existing imputation path; no forecasts are
dropped. When repairs are used, C's old calibration is not claimed to cover this
new inference path. Frontend files are unchanged.

Initially this supports unattended nominal/MissingCourseAttack cases, with one
navigation mitigation enabled at a time. Combined speed/course mitigation,
human verification and other attack combinations need separate evaluation.

## Reproduce

From Data_Science:

```
python experiments/missing_course_mitigation/check_speed_regression.py
python experiments/missing_course_mitigation/run.py
python -m pytest -q
```

The experiment uses the same fixed cohort, decision schedules, original crossing
targets, masking fractions (0/10/25/50/100%) and seeds (4201–4203) as Missing
Speed. Full masking is seed-independent and runs once. Scoring and paired
vessel-cluster bootstrap helpers are reused. No outcome-based policy tuning.
Report MAE, MdAE, P95, coverage, reconstruction rate and per-approach regressions.
Sources, models and prior speed results are hash-protected. April has been
inspected previously and is a follow-up cohort, not a pristine holdout. All
corruption is simulated; labels mean analytical crossing, not verified docking.
CSV outputs are locally ignored. See the report/protocol/validation in
`experiments/missing_course_mitigation/results/`.

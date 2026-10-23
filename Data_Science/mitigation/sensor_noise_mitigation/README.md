# Sensor-noise mitigation

`SensorNoiseMitigation(BaseMitigation)` implements detection **and** checked
reconstruction for `SensorDeteriorationAttack`, the experiment that adds random
Gaussian noise to SOG (speed over ground) and COG (course over ground).
The serving adapter permits this strategy only with that attack. It is not
connected to the gap, drift, missing-field, or position-jump experiments.

The selected strategy is **guarded replacement**. Like `GapMitigation`, it is a
frozen, stateless `BaseMitigation` subclass with configuration, a typed result,
causal report preparation, status and provenance. The gap strategy checks report
silence; this strategy checks navigation readings against position history and
can return a derived correction. Both leave received reports intact.

## Decision

1. Use only the vessel's already measured and delivered reports.
2. Check a short position history for usable motion: distinct observations,
   sufficient span, freshness, valid coordinates, acceptable gaps, plausible
   segment speeds, fit residual, and limited turning/acceleration.
3. Estimate east/north velocity with the existing `history_velocity` helper.
   Compare reported speed and circular course against this track reference.
4. Flag inconsistent readings. Replace only flagged sensor fields in a derived
   copy with position-based estimates when the position checks pass.
5. Return `requires_review` when the reference or required readings are
   unsupported. Do not invent a correction or make an old reading fresh.

This is a consistency check, not proof of a failed sensor or an attack. The
position reference is not independent ground truth and cannot establish safety
when positions are coherently wrong. Genuine maneuvers can make the reference
unusable; those cases request review instead of forcing a straight-line fit.
At very low speed, course cannot be reconstructed reliably and is left alone.
Existing missing values and AIS unavailable sentinels are not noise-repaired.

## Initial policy

These are configurable **provisional research settings**, not calibrated limits:

| Check | Default |
|---|---:|
| Position window | 5 minutes |
| Independent observations / minimum span | 3 / 60 seconds |
| Maximum gap / observation age | 180 seconds / 5 minutes |
| Maximum positional speed | 60 knots |
| Maximum fit residual | 50 metres |
| Maximum segment-speed difference from fitted speed | 2 knots |
| Maximum segment direction difference from fitted course | 30° |
| Sensor speed / course disagreement | greater than 2 knots / 15° |
| Minimum speed for a course comparison | 1 knot |

Threshold equality is not a flag. Course differences use the shortest arc:
359° and 1° differ by 2°. Exact duplicates add no independent observations;
conflicting same-time readings block reconstruction. No attack severity,
sigma, original hidden measurement, modification log, or crossing label is read.

## Python contract

```python
from mitigation import SensorNoiseMitigation

strategy = SensorNoiseMitigation(gate)
result = strategy.apply(received_reports, decision_time)
derived_reports, result = strategy.reconstruct_reports(received_reports, decision_time)
```

`apply` returns frozen, JSON-safe provenance, current status, per-field flags,
estimated/effective speed and course, their `reported`/`estimated`/`unavailable`
sources, and reference diagnostics. `can_predict` means this input state is
supported; it does not mean the resulting ETA is calibrated or accepted.

`reconstruct_reports` returns a private received-feed copy. Each reading's repair
uses only observations available by its delivery time and measured no later
than that reading. Appending future reports cannot backfill old reconstructions.
All non-sensor fields and the real measurement/delivery times stay intact.
The current result always describes the unmodified received readings. It can
report a healthy latest reading while older inputs in the model window were
reconstructed; the adapter separately reports the count actually used.

## Noise-experiment integration

The existing `sensor_deterioration_*` replay presets automatically use this
strategy for C. Their past-only ETA timelines use the same reconstruction path.
Other scenarios and attacks keep their existing behavior. There is one selected
strategy, with no new UI controls or runtime blending menu.

```text
GET /api/attacks/sensor-deterioration?decision=<id>&severity=high&mitigate=true
```

The opt-in request adds a `mitigated` snapshot alongside the existing `original`
and `attacked` snapshots at the same clock, seed, reports and crossing reference.
`mitigated.sensor_noise_mitigation` contains diagnostics, policy, `applied`, and
`reconstructed_report_count`. The received feed and audience inspector continue
to show actual noisy reports, not silently substituted readings.

Only C's derived motion features are recomputed. A/B inputs, C's original
quality evidence, guard diagnostics, support and observation timestamps remain
unchanged. A failed position check leaves the existing forecast unchanged and
marks the input for review. No model is trained, edited or recalibrated.
All attack forecasts retain the existing uncalibrated review policy. The normal
two-snapshot endpoint response remains unchanged without `mitigate=true`.

The adapter bounds reconstruction to the model window plus causal warmup.
The strategy itself has no model loading, file I/O, scoring or mutable state.

## Evidence and next evaluation

Deterministic checks cover field-specific repairs, original-feed preservation,
future/delivery exclusion, duplicate independence, angle wrap, stationary and
maneuvering tracks, missing readings, position failures, A/B parity, preserved
quality diagnostics, scope rejection and HTTP behavior. A small speed-sensitive
predictor fixture confirms that derived values reach C's prediction path; it is
not an accuracy result for the saved models.

Before selecting final thresholds, tune on development data, including healthy
turns and deceleration. Compare unchanged C versus this serving ablation under
clean, speed-only, course-only and combined noise across severities/fractions.
Report MAE, P95, coverage, false alerts, reconstruction rate and review burden.
Use the same decisions/seeds and retain source/model hashes. Previously inspected
April data can support a follow-up comparison, not a new pristine holdout.
The completed [replacement-versus-blending study](../../experiments/sensor_noise_mitigation/results/REPORT.md)
supports this selection: frozen v1 C had about 29% lower ETA MAE under high noise
and 65% under extreme noise, while 50/50 averaging recovered less. The fixed
development blend had no clear advantage over replacement. Low-noise results
show overcorrection remains a limitation, especially for course. These are
exploratory v1 findings; current v2 accuracy has not been established. Alternatives
remain in the experiment rather than the production mitigation module.

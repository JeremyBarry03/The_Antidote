# Speed-drift mitigation

`SensorDriftMitigation(BaseMitigation)` follows the same frozen configuration,
typed result, causal preparation and stateless execution pattern as
`GapMitigation`. It targets speed-only drift, with positions as a conditional
reference. It does not classify whether a disagreement is malicious or natural.

For each received observation, fit velocity to recent positions using the shared
`history_velocity` helper. Check distinct times, history span, gaps, coordinates,
physical speed, line-fit residual and turning/acceleration consistency first.
Then calculate signed disagreement: `reported_sog - estimated_sog`.

A time-based EWMA monitors this disagreement. The update fraction is
`1 - exp(-elapsed_minutes / time_constant_minutes)`, so duplicate reports and a
higher message rate do not accelerate the clock. Detection also requires
consecutive discrepancies in the same direction over a minimum elapsed span.
A single spike or alternating jitter does not satisfy persistence.

Default provisional policy: five-minute position window, 15-minute detection
window, at least three position times spanning 60 seconds, maximum three-minute
gaps and five-minute measurement age. Reference motion is limited to 60 knots,
50-metre RMS fit error, 2-knot segment-speed disagreement, 0.2 knots/minute of
position-derived acceleration and 30-degree turning.
EWMA time constant is two minutes; the deadband is 0.2 knots and the detection
threshold is strictly greater than 0.5 knots. At least three persistent reports
over two minutes are required. These thresholds are not calibrated guarantees.

After detection, **guarded replacement** uses the current position-derived speed.
The EWMA is a detection signal, not a fitted blend of prediction inputs.
Unsupported positions, maneuvers, missing speed or unavailable sentinels request
review. Fresh nominal agreement clears the current speed-bias flag once the
criteria are no longer met.

```python
from mitigation import SensorDriftMitigation

strategy = SensorDriftMitigation(gate)
result = strategy.apply(received_reports, decision_time)
derived_reports, result = strategy.reconstruct_reports(received_reports, decision_time)
```

`reconstruct_reports` changes only SOG in a private derived copy. Each repair
uses only observations measured no later than that reading and available by its
delivery time. Later arrivals cannot backfill earlier repairs. Source data,
coordinates, course, identities, classification and timestamps remain intact.
`apply` continues to describe the raw received readings, including anomaly
evidence. `can_predict` means input support, not accepted or calibrated ETA.

No attack settings, hidden original speed, audit truth or arrival label is read.
Position quality is conditional; coherent position errors can defeat this check.
Genuine acceleration or turns may force review. The local position approximation
matches the Hampton Roads feature pipeline. Model loading, ETA feature adapters,
calibration and UI belong to callers; this module does not alter them.

The EWMA mechanism follows [NIST's monitoring guidance](https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc324.htm).
Real AIS errors and timing require development calibration; the handbook's
independence assumptions do not establish alarm probabilities for this data.
Fixture checks establish behavior and causality, not saved-model ETA gains.

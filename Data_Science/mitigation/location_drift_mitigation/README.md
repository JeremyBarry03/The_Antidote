# Location-drift mitigation

`LocationDriftMitigation(BaseMitigation)` detects persistent disagreement between
positions and SOG/COG motion. It can return corrected coordinates by projecting a
separately verified position using independently trusted speed/course. Otherwise
it requests position verification. The module does not load models or edit ETAs.

## Detection

For each pair of received observations:

```text
observed_displacement = position_now - position_previous
expected_displacement = average(previous_velocity, current_velocity) * elapsed_time
disagreement_rate = (observed_displacement - expected_displacement) / elapsed_minutes
```

An EWMA of east/north disagreement rates tracks gradual bias. Significant residuals
must persist in a consistent direction and accumulate enough displacement. Defaults
remain provisional: two-minute EWMA time constant, 4 metres/minute deadband,
filtered disagreement above 8 metres/minute, three segments over at least two
minutes, and more than 30 metres accumulated disagreement. Direction changes above
45 degrees restart persistence. Gaps over three minutes, measurements older than
five minutes, invalid navigation, implausible motion and sharp speed/course changes
request review.

Supply the complete received monitoring session. A detected anomaly remains
flagged for the session, including when an estimate is available or the coordinate
bias stops growing. Starting a new session after independent verification is a
caller action. Trimming history can lose an old alarm because the class is stateless.

## Bounded correction

Correction requires both:

- A `PositionAnchor` for this vessel: verified coordinates, measurement time,
  received time and a named verification source. This must come from an independent
  source or verification workflow; an accepted suspect AIS report is insufficient.
- `navigation_trusted=True`: the caller has independently established that the
  reported SOG/COG over the projection interval is trustworthy. Neither the selected
  attack scenario nor agreement between two suspect sensors establishes this.

Correction starts only after the existing drift detector raises an alarm. The
anchor does not introduce a separate position-discrepancy classifier.

For each segment after the anchor:

```text
velocity = SOG_in_meters_per_second * [sin(COG), cos(COG)]
estimated_position = verified_anchor + sum(average(segment_velocities) * segment_time)
```

This uses the shared Hampton Roads local coordinate approximation. If the anchor
falls between observations, velocity is interpolated at the interval boundary.
Positions from the drifting feed and accumulated detector residuals do not enter
the correction. Coordinates are estimated at the original observation time; the
output does not pretend a new AIS measurement arrived at the decision clock.

The anchor expires **five minutes after its measurement** by default, configurable
through `maximum_projection_minutes`. This is a research limit, not a calibrated
accuracy bound. Navigation must cover the whole projection interval. Excessive gaps,
unavailable speed/course or sharp maneuvers anywhere in that interval block repair.
Future/unreceived anchors, stale observations and expired anchors cannot repair
coordinates. A fresh verified anchor can support an older latched anomaly.

```python
from mitigation import LocationDriftMitigation, PositionAnchor

strategy = LocationDriftMitigation(gate)
anchor = PositionAnchor(
    mmsi=verified_position.mmsi,
    time=verified_position.measurement_time,
    received_time=verified_position.received_time,
    longitude=verified_position.longitude,
    latitude=verified_position.latitude,
    source=verified_position.source,
)
derived_reports, result = strategy.reconstruct_reports(
    complete_received_session, decision_time,
    anchor=anchor,
    navigation_trusted=navigation_is_independently_trusted,
)
```

`apply(...)` accepts the same anchor/trust arguments and returns the current derived
position. On repair, `status="reconstructed"`, `position_source="estimated"` and
`correction_applied=True`. Reported coordinates, anchor provenance and projection
age remain in the result. The raw-feed `drift_detected` flag remains true.
`can_predict=True` recommends input support; it is not calibrated ETA acceptance.

`reconstruct_reports(...)` changes only latitude/longitude in a private derived
copy. It evaluates each reading using only measurements and anchors available by
that reading's delivery time. Later arrivals cannot backfill previous repairs.
Identity, speed, course, class, timestamps and source reports remain unchanged.
An expired current estimate does not erase previously valid derived estimates.

With no anchor or no independent navigation trust, correction stays disabled and
a detected anomaly recommends `verify_position`. Combined speed/location corruption
can defeat the detector or corrupt a projection if the caller wrongly declares
navigation trusted. A constant offset present before monitoring can also evade
detection. Detector output alone cannot establish a true absolute location.

No attack parameters, source coordinates hidden by an attack, modification logs or
arrival labels enter this strategy. Caller integrations own ETA features and UI.
The [initial evaluation](../../experiments/drift_mitigation/results/REPORT.md)
covered detection without anchors; its speed-error results do not measure this
correction extension. Development calibration and current-v2 evaluation with
genuinely independent reference data remain necessary.

The [conditional anchored evaluation](../../experiments/location_drift_correction/results/REPORT.md)
now measures position agreement and legacy-v1 ETA effects with simulated trusted
fixes. It separates the no-reference case and deliberately incorrect navigation
trust controls. The simulated extra feed is unavailable in the current product;
its gains must not be presented as autonomous correction or current-v2 accuracy.

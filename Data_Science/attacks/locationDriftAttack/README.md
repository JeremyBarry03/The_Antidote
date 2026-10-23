# LocationDriftAttack

`LocationDriftAttack(BaseAttack)` adds a gradually growing coordinate offset to
copies of reports. It is separate from speed-only `SensorDriftAttack`, abrupt
`PositionJumpAttack`, and the existing `reserved_drift` replay preset.

Defaults: 20 metres/minute initial rate, a smooth 1,852-metre limit, 25% smooth
rate variation with a 20-minute period, and one seeded bearing per vessel.
An explicit bearing selects the direction. Zero rate or maximum is a no-op.
The magnitude approaches its limit smoothly; it is not exactly rate × elapsed
time. The profile reuses the speed attack's bounded sinusoidal/tanh calculation,
while coordinate displacement uses the existing spherical geodesic helpers.

```python
from attacks import LocationDriftAttack, LocationDriftConfig

attack = LocationDriftAttack(LocationDriftConfig(bearing_degrees=90.))
stream = attack.apply(reports)
received = stream.available(decision_time)
```

Each vessel starts at zero offset at its earliest supplied measurement, unless
`start_time` is specified. Reuse an explicit start when injecting rolling windows.
`target_mmsi` optionally limits the attack to one vessel. Identity-based phases
and bearings preserve ordering, duplicate, sampling and future independence when
the origin is retained. The new attack does not replace the reserved preset.

Only longitude and latitude change. Speed, course, identity, class, every report,
measurement/delivery time and reference arrival label remain unchanged. Invalid
or missing source coordinates remain unchanged and never count as new faults.
The modification log separately records original/reported positions, requested
and applied displacement, bearing and actual changes (`location_drifted`). These
truth fields never enter report data or mitigation inputs.

This is a simulated input fault, not evidence of actual NOAA poisoning. The
original position is an evaluator reference, not independently verified truth.
No model loading, training, scoring, service route or frontend controls belong
to this attack module.

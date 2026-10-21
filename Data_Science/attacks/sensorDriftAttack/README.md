# SensorDriftAttack

Automatically add a smooth, one-way bias to speed over ground (`sog`). This is a
controlled simulation on copies of original reports, not evidence of measured
sensor drift in the source. Original reported speed is a reference, not verified
physical truth. Positions, course, class, MMSI, measurement/delivery timestamps,
report count and arrival references remain unchanged. No forecasts are edited.

```python
from attacks import SensorDriftAttack, SensorDriftConfig

stream = SensorDriftAttack().apply(reports)
received = stream.available(decision_time)

# Optional configuration; the curve still runs automatically.
overreport = SensorDriftAttack(SensorDriftConfig(
    drift_rate_knots_per_minute=.1,
    seed=42,
    target_mmsi=None,
    start_time=None,
))
```

Defaults: -0.1 knots/minute, 25% smooth rate variation, 20-minute cycle,
3-knot maximum bias magnitude, seed 42, and all supplied MMSIs. Each vessel starts
at zero bias at its earliest supplied measurement unless an explicit start_time
is provided. Reports before that time remain unchanged. For rolling windows,
reuse an explicit start_time to retain the original drift origin.

For elapsed minutes t, signed rate r, rate variation a, angular frequency
w=2*pi/period, vessel-specific phase phi, and maximum bias M:

```text
q(t) = r * (t + a/w * (cos(phi) - cos(w*t + phi)))
b(t) = M * tanh(q(t)/M)
reported_sog = clip(original_sog + b(t), 0, 102.2)
```

The implementation uses an equivalent sinc identity for numerical accuracy near
the start. One seeded phase per MMSI controls the rate variation. There is no
independent per-report noise or random report selection. With 0 <= a < 1, the
requested bias never reverses direction. Zero rate or zero maximum bias is a
no-op. The tanh limit is smooth: M is a cap, not the exact bias after 30 minutes.

Missing speed stays missing. Inputs require parsed real speeds in 0–102.2 knots
or missing values; invalid numeric values are rejected instead of silently
repaired. Existing missing speeds never count as new faults. Speed encoding bounds
can reduce the actual applied bias, especially near zero, so audit records expose
original_sog, reported_sog, requested_bias_knots, applied_bias_knots and clipped.
Only an actual change sets fault_applied=True/action=speed_drifted. All audit
truth remains in modification_log, separate from model-visible reports.

The strategy reuses BaseAttack, report preparation, ReportStream and the existing
identity-based seeded generator. It does not reuse positional drift or missing-
field selection, load models, perform I/O, score errors, train models or apply
mitigations. There is no service endpoint or frontend change in this addition.

Run from Data_Science:

```powershell
python -m pytest tests -q
python experiments/sensor_drift_attack/run.py
```

The isolated experiment uses corrected frozen A/B models, the same 112 April
approaches / 2,402 prediction times, signed rates +/-0.025, +/-0.05, +/-0.1 knots
per minute and seeds 4201–4203. It reports approach-weighted MAE, pooled MdAE,
P95, coverage and paired MAE changes under experiments/sensor_drift_attack/results.
CSV outputs remain locally ignored. Source/model/code hashes are checked before
and after inference. No improvement or degradation is guaranteed or forced.

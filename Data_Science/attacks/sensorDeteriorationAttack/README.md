# SensorDeteriorationAttack

Simulated random Gaussian fluctuations around original reported speed and course.
This is separate from SensorDriftAttack's smooth directional speed bias. Original
reported measurements are references, not independently verified physical truth.
The four severity settings are experiments, not measured real-world failure rates.

```python
from attacks import SensorDeteriorationAttack, SensorDeteriorationConfig

settings = SensorDeteriorationConfig.from_severity(
    "high", affected_fraction=.25, seed=4201, target_mmsi="255803201",
)
stream = SensorDeteriorationAttack(settings).apply(reports)
available = stream.available(decision_time)  # Feed this to the existing features.

# Independent field configuration; sigma zero disables a field.
speed_only = SensorDeteriorationAttack(SensorDeteriorationConfig(1., 0.))
course_only = SensorDeteriorationAttack(SensorDeteriorationConfig(0., 5.))
```

| Severity | SOG sigma (knots) | COG sigma (degrees) |
|---|---:|---:|
| Low | 0.5 | 2 |
| Medium (default) | 1 | 5 |
| High | 2 | 10 |
| Extreme | 4 | 20 |

The frozen config also accepts `affected_fraction` in [0,1], integer `seed`,
and an optional nine-digit `target_mmsi`. Default fraction is 1, seed is 42.
The existing identity-hash selection supports 10%, 25%, 50%, 100%, or a custom
fraction. Fractions are Bernoulli thresholds, not exact-count quotas. Validity
does not change the identity draw. Both enabled fields use the same selected
report set; a missing/invalid field is skipped individually.

For each selected vessel/timestamp identity, the existing seeded generator draws
two independent standard normals. The same field draw survives input reordering,
appending future reports, duplicated rows, changing sigma, and switching modes.
Duplicate copies of one measurement share noise rather than acquiring artificial
independent evidence. There is no temporal smoothing or accumulated bias here.

Only SOG and COG change, on a deep copy. Rows, input order, coordinates, classes,
IDs, measurement/delivery times and crossing labels are retained. SOG is bounded
below by zero **without an upper cap**, following the requested formula. Source
SOG outside [0,102.2], source COG outside [0,360), infinities, and NaNs remain as
supplied and are ineligible. This includes AIS unavailable sentinels 102.3 and
360. Unparsed strings/bools/complex measurement columns fail clearly. Nullable
numeric columns are supported. The standard upstream loader already converts
invalid measurements to NaN; the attack does not perform another cleanup step.

COG wraps modulo 360. Audit truth separately records original/reported values,
requested noise, actual applied speed change, signed shortest-angle course
change, clipping/wrapping, field eligibility, report selection and actual change
flags. `fault_applied` requires a valid measurement to actually change. Audit
columns never enter `stream.reports` or predictor feature lists.

## Replay and frontend

The shared `BaseAttack` / `ReportStream` boundary injects noise before feature
generation. `DemoService.sensor_deterioration_snapshot` pairs original and attacked
predictions for Models A/B/C at one clock and one unchanged reference crossing.
Model C uses its existing guard; no mitigation, training or calibration is added.
Attack forecasts are explicitly uncalibrated and not accepted by review policy.

`GET /api/attacks/sensor-deterioration?decision=<decision_id>&severity=medium&affected_fraction=0.25&seed=4201`

Optional query parameters `sog_sigma_knots`, `cog_sigma_degrees`, `target_mmsi`,
`reveal=true`, `inspect=true` follow the other paired attack endpoints. Sigma
overrides support single-field experiments. Unknown severity/invalid config
returns HTTP 400. Reference outcomes remain hidden until reveal.

The existing frontend additional-experiment selector exposes four combined,
100%-selection presets. Both `/api/replay` and `/api/timeline` accept
`sensor_deterioration_low`, `_medium`, `_high`, `_extreme`. Timelines recompute
only past/current decision times through the serving feature path; they do not
reuse clean or unrelated saved forecasts. Inspecting shows original/noisy speed
and course without claiming GPS movement. Verification is disabled for these
standalone presets. Custom fractions/modes are available through the Python/API
interfaces, not additional UI controls.

Start the replay with the corrected saved models, from Data_Science:

```text
python -m Optimized_Model serve --config Optimized_Model/config_vessel_class_v2.json --port 8765
```

Open `http://127.0.0.1:8765`, expand the additional-experiment section, and
choose a sensor deterioration severity. The local browser walkthrough was checked
with actual A/B/C artifacts, including the delivered-only inspector and timeline.

## Evaluation

From Data_Science:

```text
python experiments/sensor_deterioration_attack/run.py
python -m pytest -q
```

The default experiment uses the corrected frozen A/B/C artifacts, existing
112 April approaches / 2,402 decision times, four combined severities at 100%,
and noise seeds 4201–4203. Models are never retrained. The report distinguishes
unavailable C artifacts from completed C evaluations, records coverage and
source/model hashes, and compares paired MAE/MdAE against original feeds.
CSV outputs stay local and ignored; Markdown and JSON preserve the protocol.

Expand modes/fractions explicitly, preferably into another output folder:

```text
python experiments/sensor_deterioration_attack/run.py --modes sog cog both --fractions 0.1 0.25 0.5 1 --output artifacts/sensor_deterioration_expanded
```

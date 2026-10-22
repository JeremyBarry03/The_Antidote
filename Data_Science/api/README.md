# Anomaly notification API

`anamoly_detector.py` retains the requested module spelling. `AnomalyDetector`
adapts mitigation results to JSON; reporting-gap rules live in
`mitigation/gap_mitigation`. No model loading or training is needed for detection.

The existing local replay server exposes:

```
GET /api/anomalies?decision=<decision_id>
GET /api/anomalies?decision=<decision_id>&at=2024-04-09T12:15:00
```

`at` is the current replay clock, not the machine clock. Poll periodically with
advancing clocks even when no report arrives. Use the same scenario on every
poll. Optional `start_time` and `end_time` simulate a ReportingGapAttack;
`target_mmsi` limits that simulation. Both time boundaries are required together.
No attack metadata is passed into detection. Optional `minimum_silence_minutes`
and `cadence_multiplier` configure the timeout (defaults 5 and 3).
`stream_ended=true` explicitly ends monitoring at the recording/session boundary.
Use the same timezones as the reports. Invalid requests return HTTP 400.

The response contains `anomaly_detected`, `anomalies`, `vessel_statuses`, policy
settings, and `forecast_modified: false`. A flagged item includes type
`reporting_gap`, MMSI, `eta_reliable: false`, silence duration, report age, timeout,
and trigger boundary. These are current flags, not a durable event queue: clear
the frontend warning when the next response no longer contains that MMSI/type.

Existing `/api/replay` and attack snapshot responses also contain
`anomaly_detection`, including original/attacked ReportingGapAttack snapshots.
The polling endpoint runs independently of model inference and supports clocks
between scheduled ETA decisions. Detection does not automatically run a timer
or push messages to a disconnected frontend. No frontend files were changed.

Replay approach histories contain pre-crossing reports; they do not include the
hidden reference crossing fix. The detector never substitutes reference labels
for observed arrival. The replay controller must end monitoring at session end,
or supply subsequent observed arrival reports in a continuous feed integration.

Python use (complete parsed history, multiple MMSIs allowed):

```python
from api.anamoly_detector import AnomalyDetector
from mitigation.gap_mitigation import GapMitigation

payload = AnomalyDetector(GapMitigation(gate)).evaluate(reports, replay_clock)
```

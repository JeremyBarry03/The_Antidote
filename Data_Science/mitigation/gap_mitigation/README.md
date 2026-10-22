# Reporting-gap anomaly detection

`GapMitigation(BaseMitigation)` monitors one MMSI using only received reports.
An approach starts at an observed position within the configured east-side
approach rectangle. At least three distinct measurement times are needed.
The timeout is `max(5 minutes, 3 * median recent reporting interval)` by default;
the cadence uses the last ten active reports. These are configurable research
settings, not measured failure probabilities or validated production thresholds.

Silence strictly greater than the timeout triggers `reporting_gap`. Equality is
still normal. Fresh reports clear the current flag. An observed fix at/west of
the gate within its latitude range ends monitoring as `arrived`; this is an
observed arrival-area rule, not the interpolated evaluation crossing label or
proof of docking. Leaving the approach rectangle ends monitoring as `left_area`.
Re-entering starts another approach. Invalid positions do not enroll/complete
an approach. Existing missing course/speed values do not affect this detector.

The silence clock uses delivery time when available, otherwise measurement time.
Report age remains the age of the measurement. Re-delivery of the same timestamp
does not restart the clock. Without actual delivery times, receiver silence and
source timestamp age cannot be independently established. A gap does not prove
an attack or a stopped vessel.

Call on every monitoring tick, including ticks with no new reports. Supply the
complete received history for the current monitoring session. The implementation
is stateless, so replay seeks and scenario changes do not retain stale flags.
Explicitly pass `stream_ended=True` at end of recording; do not run a recording's
clock indefinitely past its end. End-of-stream cannot be inferred from the last
row without confusing an ongoing outage with recording completion.

The output recommends unreliable ETA when a gap is flagged. Forecasts, model
parameters, feature generation and source reports are unchanged. No synthetic
AIS fixes, projections, automatic corrections or automatic forecast suppression.

The frontend response adapter is `api/anamoly_detector.py` (requested spelling).
It groups by MMSI and emits current anomaly/status snapshots. See its API docs.

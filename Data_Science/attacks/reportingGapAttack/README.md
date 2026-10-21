# ReportingGapAttack

A deterministic, offline simulation of missing AIS reports. It represents an
accidental reporting outage; the name does not imply an adversary or a confirmed
problem in the NOAA source. It may worsen, improve, or leave an individual ETA
unchanged. It never changes forecasts or labels to force a negative result.

## Behavior

- Drop reports with measurement time in `[start_time, end_time)`.
- Resume reports at `end_time`, without later backfilling dropped observations.
- Optionally target one nine-digit MMSI; otherwise apply to every supplied MMSI.
- Copy inputs, preserve retained values and existing delivery times, and keep the
  crossing reference untouched. Generate delivery times equal to measurement times
  only when no delivery column was provided, matching nominal replay assumptions.
- Return the existing `ReportStream`, whose `available(decision_time)` excludes
  future measurements and deliveries. Modification truth stays in its separate log.
- Reject missing/unparsed times, invalid windows, and incompatible timezone awareness.
  Use the dataset's UTC clock. The current cache uses timezone-naive UTC timestamps;
  do not pass browser-local times or add a timezone suffix to those cached timestamps.
- If there is no available history, existing prediction support rules return no
  forecast. With older history, each model handles the older evidence normally.

Unlike continuous delivery delay, this is a bounded, permanent loss of reports
measured during the configured window. It does not simulate a queue flushing at
the end of an outage. Existing pre-gap delayed deliveries retain their timing.

## Python interface

Run from `Data_Science`, using the existing project dependencies:

```python
import pandas as pd
from attacks import BaseAttack, ReportingGapAttack, ReportingGapConfig

attack: BaseAttack = ReportingGapAttack(ReportingGapConfig(
    start_time=pd.Timestamp("2024-04-10T12:10:00"),
    end_time=pd.Timestamp("2024-04-10T12:20:00"),
    target_mmsi="123456789",  # Omit to target all supplied vessels.
))
stream = attack.apply(reports)  # Parsed report DataFrame with mmsi/time columns.
received = stream.available(pd.Timestamp("2024-04-10T12:15:00"))
# Pass received to the existing feature extractor. Never pass modification_log.
```

`BaseAttack` exposes `name`, `condition`, `parameters`, and `apply(reports)`.
Future attacks implement this same strategy contract. There is no factory/registry
until multiple concrete implementations need one. No model loading, I/O, training,
or scoring belongs in the attack itself.

## Frontend integration

The existing server exposes an additive GET endpoint:

```text
/api/attacks/reporting-gap?decision=DECISION_ID&start_time=2024-04-10T12:10:00&end_time=2024-04-10T12:20:00&reveal=true&inspect=true
```

`decision` comes from `/api/catalog`. An optional `target_mmsi` scopes the outage.
Invalid settings or unknown decisions return HTTP 400. Requests have no side effects.

Frontend integration is owned separately. A caller can use the existing endpoint
with standard query encoding and cancellation:

```javascript
const query = new URLSearchParams({
  decision: selectedDecisionId,
  start_time: gapStartUtc,
  end_time: gapEndUtc,
  reveal: 'false',
  inspect: 'true',
});
const response = await fetch(`/api/attacks/reporting-gap?${query}`, {
  signal: abortController.signal,
});
const pair = await response.json();
if (!response.ok) throw new Error(pair.error);

cards.render(pair.attacked, pair.original);
```

Response contains `original` and `attacked` snapshots at the identical decision
time, each with A/B/C cards, received history, feed counts, and observable signals.
The existing card renderer can show ETA shifts using the original snapshot as its
reference. Errors and crossing truth appear only with `reveal=true`.

`attacked.attack` contains the name, parameters, and count of dropped reports
measured so far. With `inspect=true`, its `inspection` includes audience-only dropped
record identities/timestamps, capped to the latest 150 with a `truncated` flag.
Future dropped records are never exposed. `attacked.inspection` is null: position
offset inspectors are not appropriate for missing-report failures.

The new condition is not calibrated by the saved review-policy artifact, so its
cards are marked `attack_not_calibrated_requires_review` and never accepted by that
policy. Existing nominal/delay/position replay behavior is unchanged. Combining
standalone attacks with old scenarios or verified updates is explicitly rejected
until those experiment contracts are defined.

This change supplies only backend code and its API contract; frontend code and
controls are owned separately.
The saved `/api/timeline` and `/api/metrics` describe the old evaluated scenarios;
they must not be shown as evidence for this custom outage. Build outage playback
by requesting paired snapshots for successive decision IDs with the same window.
Aggregate gap results require a separately labeled evaluation run.

## Verification

```powershell
python -m pytest tests/test_reporting_gap_attack.py tests/test_optimized_model.py -q
```

Tests cover boundaries, resumption, targeting, input preservation, existing delivery
times, no future influence, empty/full outages, validation, and paired replay output.

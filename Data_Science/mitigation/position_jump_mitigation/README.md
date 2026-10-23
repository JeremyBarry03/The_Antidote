# Position navigation anomaly detector

`PositionJumpMitigation` retains the existing BaseMitigation contract and public
API name, but its only action is a per-vessel warning. The former position
estimator, hypothesis selection, quarantine, feature adapter, expiry-based
forecast suppression, experiments and results have been removed.

## Observable check

For two consecutive received fixes separated by dt seconds, convert displacement
to local east/north meters. Compute velocity vectors from SOG (knots converted
to m/s) and COG (circular angles converted with sine/cosine):

```text
u = speed_mps * [sin(course), cos(course)]
e = observed_displacement - 0.5 * (u_previous + u_current) * dt
S = (2 * position_sigma_meters^2 + 0.5 * velocity_sigma_mps^2 * dt^2) * I
score = transpose(e) * inverse(S) * e
```

The endpoint variance formula follows independent position/velocity errors and
a local trapezoidal motion approximation. Effective normalizers are 25 m per
position endpoint and 0.5 m/s per velocity endpoint. They are experimental
scales, not independently measured sensor accuracy. The empirical score
threshold is 1.948477151551384: the vessel-balanced March 99.5th percentile,
using no April data or ETA outcomes. It is not a chi-square probability or a
guaranteed false-alert rate. Actual decision-window alerts are measured separately.

Pairs more than 120 seconds apart, missing/invalid SOG or unavailable COG are
unassessed; the detector does not assume straight movement across long gaps.
True zero SOG implies zero velocity even if COG is unavailable. No missing field
in the source is filled. Invalid/missing coordinates and conflicting same-time
positions also produce warnings. Exact timestamp duplicates are not extra
independent support. Longitude and course wrap correctly.

Warn if a discrepancy ends within the last five minutes. The window uses the
actual decision clock, so old warnings expire even without new reports; the gap
detector handles reporting silence separately. New reports never see a fitted
trusted trajectory, so there is no anchor lockout or permanent rejection state.
Missing support is reported as unassessed, not confirmed good navigation.
Only already measured and delivered reports can affect an assessment.

## API

`AnomalyDetector(gap_mitigation, position_mitigation=PositionJumpMitigation())`
evaluates each MMSI independently. Its existing anomaly response includes:

- `type: position_jump`, MMSI, current detection time and observation evidence.
- `message: Navigation measurements disagree; ETA may be unreliable.`
- `eta_reliable: false`, residual magnitude, score and reason.
- `forecast_modified: false`.

The warning cannot determine whether GPS, SOG, COG or the motion approximation
is responsible. It does not establish intentional poisoning.

The existing query flag is retained for compatibility:

```text
GET /api/attacks/position-jump?decision=<id>&affected_fraction=0.25&mitigate_position_jump=true
```

Despite its historical name, the flag enables warnings only. The same flag
works on position-jump replay/timeline presets. Each timeline decision contains
its own causal anomaly response. Snapshot metadata identifies `mode: anomaly_only`,
`features_changed: false`, `forecast_modified: false` and `model_retrained: false`.
All A/B/C inputs, cards, availability, point estimates, intervals, source reports
and reference arrivals match calls without this flag. Model loading and feature
construction have no dependency on this detector. No frontend changes are made.

## Limits

A coherent fixed offset present from the beginning is not identifiable internally.
No warning means only that this check found no inconsistency; it is not proof
of accurate position or ETA. Turns, correlated measurement errors and maneuvers
can generate warnings. Another field can be responsible for disagreement.
This detects possible unreliable navigation and requests review; it does not
repair corrupted data, improve model MAE, or guarantee every bad fix is detected.

See [the detector experiment](../../experiments/position_jump_anomaly/README.md).

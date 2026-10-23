# Missing-speed mitigation for frozen Antidote

`MissingSpeedMitigation(BaseMitigation)` estimates unavailable SOG at the original
measurement time using a least-squares fit of recent east/north positions versus
time. Speed in knots is `hypot(east_mps, north_mps) / (1852/3600)`. This estimates
recent average motion, not independently verified instantaneous physical speed.

Fixed initial settings: trailing five minutes, at least three distinct fixes
spanning 60 seconds, no internal gap over 120 seconds, maximum 60 knots, maximum
50 m RMS fit residual, and maximum two-knot disagreement of any consecutive
position-derived velocity vector with the fitted velocity. These are research
settings fixed before the experiment, not production-calibrated thresholds.
Positions must be finite and geographically valid. Same-time coordinate conflicts
fail reconstruction. Exact repeated fixes do not add independent evidence.

Valid reported SOG in [0,102.2] is untouched, including zero. NaN, nonfinite,
negative or unavailable AIS 102.3 values are eligible for reconstruction. When
unsupported, they remain missing in the private effective feed. Original inputs
are never changed. Missing or invalid coordinates do not become estimates.

`apply` assesses the latest observation. `repair_reports` repairs missing speeds
at each observation causally: only preceding positions available by that report's
own delivery clock are used. Appending later positions cannot backfill previous
speeds. No estimated speed feeds another speed fit. No missing field is zero-filled.

## Frozen-model adapter

`optimized_model.missing_speed_snapshot` runs the existing C input guard once,
then repairs accepted position history. The same original/mitigated snapshot
pair supports experiments and serving. Model loading/scoring/file I/O remain
outside the mitigation. The existing feature extractor, saved trees, fitted
imputer, target clock and feature schema are unchanged.

Only supported speed-related features are recomputed: latest/mean/trend speed,
speed quantiles/variation/low-speed fraction, speed-conditioned course summaries,
and reported-versus-position velocity disagreement. Original missing-speed
fraction, `history_missing`, position/motion-fit features, guard diagnostics and
timestamps remain unchanged. Audit results never enter model features. Existing
imputer-generated missing indicators still follow the effective numeric values;
retaining provenance features does not guarantee calibrated confidence.

Unsupported SOG follows C's existing fitted imputation path. Forecasts are not
withheld, so an apparent gain cannot come from dropping difficult decisions.
Clean data with no missing SOG is an exact identity. Naturally missing SOG may
also be reconstructed, so the experiment includes original+mitigation control.

## Optional API integration

On the existing replay server:

```
GET /api/attacks/missing-speed?decision=<id>&affected_fraction=0.5&seed=4201&mitigate_missing_speed=true
```

The default remains false. Both original and attacked arms use the requested
setting. Only C's guarded features change; A/B's raw inputs and predictions remain
unchanged. The response includes separate `missing_speed_mitigation` diagnostics
and per-missing-report audit, without replacing the observed received history.
When reconstruction is used, C's pre-existing calibration is not claimed to cover
the new path. Initially only unattended nominal/MissingSpeedAttack combinations
are supported; no human-verification or mixed-attack activation. Frontend files
are unchanged. Internal Python callers may pass the same flag to `snapshot`.

## Evaluation

Run `python experiments/missing_speed_mitigation/run.py` from Data_Science.
This tests fixed March development and April follow-up cohorts at 0/10/25/50/100%
masking with seeds 4201–4203 for partial masks. Full masking runs once because
the selection is seed-invariant. No threshold search or retraining. The report
includes paired MAE changes, pooled MdAE/P95, coverage and reconstruction rate.
CSV outputs are locally ignored; protocol/report/validation JSON are retained.
Stress fractions are proposed simulated disruption settings, not observed failure
rates. Original AIS speed and the analytical crossing label are not independent
ground truth for physical speed or docking arrival.

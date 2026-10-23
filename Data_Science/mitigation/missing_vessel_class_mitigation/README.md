# Missing vessel class: simple carry-forward

`MissingVesselClassMitigation(BaseMitigation)` reuses a supported broad cargo or
tanker classification from the same MMSI's received history when the latest
report lacks type. It changes no AIS rows and guesses no exact AIS subtype.

The fixed initial policy requires at least three distinct earlier timestamps,
all agreeing on cargo/tanker, inside the last 60 minutes of the decision clock.
Repeated copies do not create evidence. Codes 70–79 agree on cargo; 80–89 agree
on tanker. Defaults are provisional settings, not calibrated probabilities.

Known current class is preserved. Missing/zero/invalid type is never assumed to
mean cargo. No recent evidence, insufficient reports, conflicting history or a
known unsupported type stays unknown. Contradictory current cargo/tanker messages
at the same timestamp also force unknown, preventing arbitrary row-order choices.
The pure rule needs only MMSI, parsed time and numeric vessel_type; no GPS,
speed, course, model loading, file writing or external registry is needed.

Each call rebuilds its evidence from scenario-local reports available by the
decision time, including delivery-time checks. There is no mutable cache shared
between vessels, scenarios or replay seeks. Hidden clean labels, future reports,
attack settings and crossing labels never enter the mitigation.

## Frozen Antidote integration

The adapter `vessel_class_snapshot` changes only existing `is_cargo`, `is_tanker`,
and `vessel_class_unknown` features. The resulting flags remain coherent:
cargo=(1,0,0), tanker=(0,1,0), unknown=(0,0,1). Original missing type, evidence
count/time, class age and reasons stay in a separate audit. Source reports,
timestamps, all motion/quality features, and saved model parameters stay intact.
Unknown class follows C's existing path; forecasts are not withheld.

API example on the existing local replay server:

```
GET /api/attacks/missing-vessel-class?decision=<id>&affected_fraction=0.5&mitigate_missing_vessel_class=true
```

The default is false. Both original/attacked arms use the requested setting.
Poly and ordinary XGBoost retain their raw inputs and predictions. The response
adds `missing_vessel_class_mitigation` with `features_changed` and an audit.
When class flags change, existing C calibration is not claimed for this new
path. Initially only unattended nominal/MissingVesselClassAttack combinations
are supported; combinations with other mitigations need separate evaluation.
Frontend files are unchanged.

## Evaluation and limits

Run `python experiments/missing_vessel_class_mitigation/run.py` from Data_Science.
The experiment uses the same March/April cohorts, decisions, original crossing
targets, and scoring helpers as the other mitigations. It compares clean,
report-masked and whole-vessel-masked feeds at 10/25/50/100% using seeds 4201–4203
for partial masks. Full masking runs once. A separate declared warm-up/dropout
scenario keeps genuine reports before first-observation+10 minutes, then removes
later types, so the cache has legitimate earlier information and can expire.

If a vessel's type has never been received, or all supplied class reports are
masked, the mitigation cannot recover it. It is not initialized from the clean
comparison feed. These prepared cargo/tanker cohorts do not test recovery of
vessels excluded by upstream source-cohort selection. Consistent metadata can
still be wrong; this is not an MMSI spoofing detector or verified registry.
Stress settings are simulated corruption, not measured failure rates. Arrival
means analytical crossing, not docking. April has been inspected previously.
Results report MAE/MdAE/P95, coverage, effective recovery rate and per-approach
variation, with protected source/model and old speed/course result hashes.
CSV outputs are locally ignored.

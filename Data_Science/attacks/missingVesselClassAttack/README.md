# MissingVesselClassAttack

This attack masks only `vessel_type` as missing (`NaN`), preserving every report,
identity, speed, course, position and timestamp **through ETA calculation**. Existing missing values are not
counted as newly injected faults. The shared masking helper and BaseAttack contract
keep deterministic selection and audit truth separate from model inputs.

```python
from attacks import MissingVesselClassAttack, MissingVesselClassConfig

attack = MissingVesselClassAttack(MissingVesselClassConfig(
    affected_fraction=.25,
    seed=4201,
    selection_unit="report",  # or "vessel" for persistent class loss
    target_mmsi=None,
))
stream = attack.apply(reports)
received = stream.available(decision_time)
# Pass all received reports to the existing feature builder and predictor.
# Do not reapply classification filtering after this field-only attack.
```

Report selection hashes seed, MMSI and measurement time. Vessel selection hashes
seed and MMSI, masking the entire supplied history of each selected vessel. Both
are independent of model errors, arrival labels, report ordering or future rows.
`affected_fraction` is a selection probability, not a guaranteed exact quota.
`target_mmsi` optionally restricts either selection to one nine-digit identity.

The source cargo/tanker cohort is selected before injection. Active replay and the
current experiment do not filter out reports after classification removal. All
position and speed evidence remains available. The corrected feature contract
uses `is_cargo/is_tanker/vessel_class_unknown`: cargo `(1,0,0)`, tanker `(0,1,0)`,
unknown `(0,0,1)`. The raw report keeps NaN and missing class stays distinct after
imputation. Historical frozen binary models still see only `is_tanker` and
cannot acquire the extra distinction by loading them; use the retrained v2 run.

`classified_cargo_tanker_reports` remains solely to reproduce the historical
row-filter experiment. It is not called by active class-attack replay or the
current experiment. That older experiment's coverage-loss results do not describe
the current retained-report behavior.

This is an inference/ingestion stress test on known cargo/tanker histories, not
retraining and not proof of malicious poisoning. Actual unknown-class source
records cannot automatically be labeled cargo/tanker or given known arrival truth.
Even complete classification loss retains every motion report and can produce
ETAs through the existing encoder. Report accuracy together with coverage and
class-specific subsets. Removing cargo class now changes its cargo/unknown
flags too. The source training cohort contains no unknown classes, so this
encoding fix does not imply the model has learned unknown-class behavior. No
metadata history/cache, class recovery or missing-class training augmentation
has been added.

## Backend integration

```text
/api/attacks/missing-vessel-class?decision=DECISION_ID&affected_fraction=0.25&seed=4201&selection_unit=report&reveal=true&inspect=true
```

Returns paired `original`/`attacked` A/B/C snapshots at the same decision and
reference. The attack snapshot retains all received reports before model features;
there is no `classification_filter` exclusion stage. Its audit records are audience-only.
The endpoint's `received_history` contains all model-visible received reports;
`vessel_type` is also exposed alongside speed/course. The separate audit retains
the removed classes for inspection, never for inference. Existing custom-attack
calibration restrictions still apply. The old saved timeline/metrics are not
evidence for this custom attack. No frontend changes are included.
Use `Optimized_Model/config_vessel_class_v2.json` when serving the corrected
models; the original configuration/artifacts remain the historical benchmark.

## Plan and testing

The isolated experiment tests 10/25/50/100% masking at report and vessel levels,
with three fixed partial-selection seeds and one seed-independent full-removal
run. It preserves all original April decision times and crossing labels, scores
retrained A/B models with all received reports, and reports MAE/MdAE plus coverage.
Current
protocol, audits, per-seed results and Markdown report are under
`experiments/vessel_class_attacks/results_vessel_class_v2`. CSVs remain ignored.
The binary-class study is preserved under `results` and reproducible with `--legacy`. The older
`experiments/missing_vessel_class_attack/results` is labeled historical.

Run from `Data_Science`:

```powershell
python -m pytest tests -q
python experiments/vessel_class_attacks/run.py --train
python experiments/vessel_class_attacks/verify_runtime.py
```

Tests cover field isolation, natural missingness, targeting, persistent versus
intermittent selection, no future influence, nullable classes, retained forecasts
under full class removal, optional outcome reveal and audit-only inspection.

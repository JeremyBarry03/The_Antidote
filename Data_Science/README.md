# ETA baselines A and B

Shared preparation and evaluation for **A: quadratic ridge regression** and
**B: standard XGBoost**. These are nominal-data baselines, not model C and not
the anomaly detector. All commands below run from `Data_Science`.

## Run

Python 3.11 is the verified runtime. CPU only; no GPU or external service needed.

```powershell
cd C:\Users\jerem\Downloads\the_antidote\2026_WM_Hackathon\Data_Science
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m eta_baselines all
```

Or run preparation once and reuse exactly the same examples:

```powershell
python -m eta_baselines prepare
python -m eta_baselines train --model quadratic
python -m eta_baselines train --model xgboost
```

Use `--config path/to/config.json` to change inputs, geometry, dates or tuning.
Paths in a config resolve relative to that config's location, not the shell.
Rerun preparation after changing the source, feature or label configuration.
Existing artifacts for a run are overwritten; choose a different output directory
to preserve an earlier run. The source CSV is never modified.

## Arrival and cohort assumptions — review before making claims

The default analytical reference is longitude **-76.30**, latitude **36.95–37.05**,
crossed east-to-west. It comes from the execution plan; it is **not an official
port boundary**, a terminal arrival, or a confirmed port call. The starting
approach area lies east of the gate within the configured latitude band.
Review `approaches.csv` on a map before treating these inferred events as valid.
This implementation deliberately does not infer arrival from speed reaching zero.

Only cargo/tanker records with reported type 70–89 enter the cohort. Missing
vessel type is excluded; record this selection limitation. Identifiers group
trajectories but are never model features. An approach enrolls on an observed
east-side position and resets after a crossing, approach-area exit or six-hour
reporting gap. A qualifying crossing has a bracketing gap <=120 seconds. The
crossing is linearly interpolated and its before/after timestamps are retained.
No port-call truth or receiver latency is available in this CSV.

Unresolved/turnaway episodes are counted but have no regression target. Results
are **conditional on qualifying observed arrivals and assumed inbound intent**.
They do not establish destination recognition or reliable behavior on non-arrivals.
No speed filter removes valid slowdowns or stops inside an enrolled approach.
Short approaches with no scheduled prediction are counted separately.

## Shared training contract

- Decision clock every five minutes, starting at least ten minutes after enrollment.
- Both models summarize at most ten minutes of reports ending at the latest
  observation available by each decision; no future motion enters features.
- Position is expressed in approximate local meters using a small-area
  equirectangular conversion; this is not precision navigation geometry.
- Features: east/north offset, SOG, sine/cosine COG, recent mean speed and east
  offset, speed trend, cargo/tanker indicator and missing-history flag.
- Invalid SOG/COG become missing. Identical rows are removed. All rows sharing a
  conflicting vessel/timestamp key are excluded rather than guessed correct.
- Median imputation and missing indicators are fitted on training only and shared.
- Target: **crossing timestamp minus latest observation timestamp**, in minutes.
  At inference, absolute ETA = observation timestamp + predicted duration;
  remaining ETA = absolute ETA minus current decision timestamp. This corrects
  aging estimates without giving the baseline model C's freshness features.
- Each approach contributes equal total training weight. Long histories do not
  automatically receive greater total influence.
- A uses scaling, degree-two polynomial features and ridge regression. B uses
  CPU histogram XGBoost, weighted validation early stopping and a bounded grid.
- No synthetic corruptions, learned repair or deferral are included in A/B.

Default March splits: 1–19 training, 20–24 validation, 25–31 test. Entire approaches
including reference brackets must lie within one partition; boundary-spanning
episodes are purged. Configuration differs intentionally from the execution
plan's April–June calendar because the supplied data cover March. Do not mix
their results. Same vessels may occur across periods; report this dependence.

Candidates are selected only on approach-weighted validation MAE. The selected
training fit is saved without refitting on validation or test. Test results are
preliminary once inspected; redesigning based on them requires a new held-out
period for protected claims. Counts below 30 approaches trigger a warning and
counts below two in any partition stop training rather than silently shuffle.

## Artifacts and reuse

`artifacts/march_2024/` contains:

- `examples.csv`: shared causal features, outcome metadata and split IDs.
- `approaches.csv`: reviewable arrival events and uncertainty brackets.
- `data_manifest.json`: source SHA256, parsing exclusions and cohort/split counts.
- `config_snapshot.json`: reproducible preparation configuration.
- `quadratic/` and `xgboost/`: `model.joblib`, `tuning.csv`, `metrics.json` and
  per-partition prediction CSVs. Predictions remain raw; negative/expired ETAs
  are counted, not clipped away.

Primary metric: mean of each approach's mean absolute ETA error, in minutes.
Reports also include bias, tail errors, output coverage on scored arrival cases
and the number of test vessels previously seen in training. These are point
estimates, not confidence intervals. Reference uncertainty and unresolved cases
must accompany any headline comparison. No published-paper accuracy is claimed.

`EtaPredictor.predict()` is the shared saved-model inference interface. Build
snapshots with `FeatureBuilder.snapshot(reports, decision_time)` using columns
`time, longitude, latitude, sog, cog, vessel_type`. Then:

```python
import joblib

predictor = joblib.load("artifacts/march_2024/xgboost/model.joblib")
predictions = predictor.predict(snapshots)
```

Keep `Data_Science` on the Python import path when loading. Only load trusted
joblib artifacts; deserialization executes Python code. The folder structure
keeps model-specific constructors separate while sharing all data/features,
weights, splitting, prediction and scoring logic.

## Verification

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests cover crossing direction/bracket uncertainty, stationary non-arrivals,
future-data exclusion, boundary purging, equal approach weights and correct
timestamp anchoring. They do not validate the geographic suitability of the gate.

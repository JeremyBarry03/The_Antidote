## Run the shared dashboard after pulling

From the repository root:

```powershell
git pull origin main
python -m pip install -r Data_Science/requirements.txt
cd Frontend
npm ci
cd ../Data_Science
python -m Optimized_Model serve --port 8765
```

Open http://127.0.0.1:8765/tracking/ . Stop any older server on that port first.
The committed serving bundle contains original March 2024 replay histories
(243 approaches, 5,382 scheduled decisions), terminal crossing positions,
model hashes and original provenance. It serves the 2023-trained A/B/nominal C
without the multi-gigabyte training CSVs or auxiliary experiment models.
It verifies model/data hashes, inference code (ignoring line endings), and
scientific configuration. Nominal C does not use augmented-C calibration.
Research training/evaluation still requires original source data and artifacts.

`MAPBOX_PUBLIC_TOKEN` in the repository `.env` is optional for the geographic
basemap; without a public token the coordinate fallback remains available.
The frontend documents monthly/stress analysis routes that this backend does
not yet implement; this bundle enables replay/inference, not those graph jobs.

# Degradation-aware ETA model C

This package builds on the existing `eta_baselines`, `Simple_baseline` and
`XGBoost_Model` code. It retains their analytical east-to-west crossing at
longitude -76.30, latitude 36.95-37.05. It does not predict docking at VIG.

The interactive demo is available with `python -m Optimized_Model serve` at
`http://127.0.0.1:8765`. Serving defaults to `config_data_eval.json`: the new
2023-trained A/B artifacts and nominal-only C (`C_nominal.joblib`), exposed under
the stable A/B/C names. The UI covers only March 1â€“31, 2024, and all existing
fleet mitigation hooks remain connected to C. The augmented C is retained for
experiments; its calibration is not reused for the nominal-only model. See
`../experiments/nominal_model_comparison/RESULTS.md` and `serving_verification.json`
in that experiment folder for the model comparison and live integration checks.
Other training/evaluation commands retain their explicit experiment behavior. The server
opens the fleet dashboard at `/tracking/`; the older replay is at
`/eta_replay.html`. Run `npm ci` in `Frontend` once to install the pinned Mapbox
SDK. See `../../Frontend/README.md` for startup, API shapes, attack behavior,
optional Mapbox token and checks.

## Historical vessel-class experiment

The vessel-class v2 run keeps cargo, tanker and unknown distinct in both raw and
guarded features. Its frozen A/B models and C/control models are separately
retrained under `artifacts/optimized/march_gate_vessel_class_v2`, preserving the
original benchmark. The old config/model manifests do not match the new shared
feature implementation and must not be presented as current compatible models.
Run the following from `Data_Science` to reproduce the corrected version:

```powershell
python experiments/vessel_class_attacks/run.py --train
python -m Optimized_Model prepare --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model train --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model serve --config Optimized_Model/config_vessel_class_v2.json --model-c C
```

The new run must be independently calibrated/evaluated before using accuracy
tables, timelines or review envelopes from it. No previous calibration or saved
evaluation evidence is copied across model versions. Explicit unknown encoding
does not add unknown-class training examples, recover classes or guarantee better
accuracy. There are no service or frontend code changes in this fix.

## Run the experiment

Use Python 3.11 and the existing pinned `Data_Science/requirements.txt`. No new
Python dependencies or GPU are required. Run from `Data_Science`:

```powershell
python -m Optimized_Model acquire --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model prepare --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model train --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model calibrate --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model evaluate --config Optimized_Model/config_vessel_class_v2.json
python -m Optimized_Model evaluate --config Optimized_Model/config_vessel_class_v2.json --suite stress
python -m Optimized_Model evaluate --config Optimized_Model/config_vessel_class_v2.json --suite volume
python -m pytest tests -q
```

The corrected A/B artifacts must already be present in `artifacts/march_2024_vessel_class_v2`.
Preparation copies A/B into this run's `frozen_baselines/`; later commands load
those checked snapshots without overwriting or refitting the upstream models. The `pilot`
command uses the previously inspected March 25-31 period and labels it exploratory.
Use `--config path/to/config.json` for a separate versioned experiment. Paths
resolve relative to that file. Training overwrites C/control artifacts in the
configured output directory; calibration rejects changed models/configuration.

`acquire` downloads the official NOAA 2024 daily GeoParquet product, retains
Hampton Roads records within longitude [-76.6,-75.8], latitude [36.7,37.2],
and merges April 1-21 into `data/hampton_roads_april_2024.csv`. Daily subset
hashes allow interrupted acquisitions to resume. Temporary national archives
are deleted after each daily extraction. DuckDB's spatial extension requires
network access on first acquisition. CSV header names are normalized by the
existing observation loader. The source CSVs are never modified.

## What is fitted

| Artifact | Inputs | Training views | Target clock |
|---|---|---|---|
| A / B | Twelve features, including explicit class flags | Nominal March fit, frozen per version | Observation |
| A_guard / B_guard | Original features after guard | Same frozen models | Observation |
| B_rich_nominal | Original plus causal motion features | Nominal | Observation |
| C_nominal | Full C features and guard | Nominal | Decision |
| augmented_motion | Guarded motion features, no added quality fields | Four conditions | Decision |
| C | Guarded motion and observable quality | Four conditions | Decision |

C uses speed quantiles/variability, circular course dispersion, derived motion,
real report age, support/gaps, missingness and physical disagreement. The guard
deduplicates, bounds minute-bin influence and screens implausible jumps. It can
fail when plausible biased reports dominate; it cannot recover an unseen vessel
during a complete outage. Low speed and valid turns are retained as behavior.

Each original training decision receives nominal, stale, quality and combined
views. Delay/offset/share settings are sampled deterministically per approach
from the declared grid. Each approach has equal total weight, then decisions,
condition groups and replicas divide that weight. Unsupported views do not
become fabricated features. Their counts remain in evaluation denominators.

All four fitted XGBoost variants use B's six depth/rate candidates, weighted
development early stopping and the same squared-error objective. C is selected
using equally weighted condition-level approach MAE on March 20-24. Its nominal
control is selected on nominal development data. Arrival labels and crossing
brackets always come from the original reference, never from injected reports.

## Periods and interpretation

| UTC period | Purpose |
|---|---|
| March 1-19 | Training, 153 approaches |
| March 20-24 | Development, 36 approaches |
| March 25-31 | Previously inspected exploratory comparison, 53 approaches |
| April 1-7 | Separate calibration, 50 approaches |
| April 8-21 | Protected evaluation, 112 approaches |

Only complete episodes within a partition qualify. Repeated vessels are allowed
across calendar periods, reported as seen/unseen and clustered during paired
resampling. MMSI is never a predictor. The cohort remains conditional on observed
cargo/tanker arrivals with supported crossing brackets; unresolved episodes
are audited but cannot receive an invented arrival label.

The archive has event times, not measured delivery times. Instant nominal
delivery and all fault rates are simulation assumptions. Reserved gradual
along-route drift is absent from training and calibration. Evaluation uses five
paired seeds. Seed-invariant nominal/delay views are computed once and reused
without changing their values. Drift follows current/past observed displacement;
when no movement direction is available, it uses a seeded direction. Drift views
are therefore computed for each seed, including at stationary observations.

Calibration uses maximum absolute residual per approach, with age-band support
of at least 30 approaches or a pooled fallback. Its empirical envelopes are not
universal confidence guarantees. The predeclared five-minute half-width policy
can defer many or all estimates. That is reported alongside an age-only policy,
matched-coverage comparisons and raw errors; deferral is not a numerical gain.

## Saved evidence

`artifacts/optimized/march_gate_v1/` contains:

- `manifest.json`, `decisions.csv`, `reference_approaches.csv`: source/configuration
  provenance, cohort, reference brackets and split counts.
- `baseline_compatibility.json`: initial/current hash and forecast comparisons.
- `frozen_baselines/` and `baseline_integrity.json`: stable comparator copies and
  the audited numerical-equivalence recovery after upstream artifacts were
  rewritten during this run. B was recovered byte-for-byte; A was verified on
  every distinct stored primary/volume input. Original binding metadata is in `lineage/`.
- `long_training_approaches.json`: retained long approaches, gaps and low-speed
  fractions. These observations support further geographic review; they do not
  prove every long episode represents a genuine destination-bound voyage.
- `views/`: feature caches, implementation signatures and separate modification
  logs. `*_fault_audit.csv` contains evaluator-only prevalence/volume counts.
- `models/`: four separately trained bundles, tuning records, development
  predictions, feature schemas, target clocks, hashes and package versions.
- `calibration.json`: empirical envelopes, approach support and model/config hashes.
- `results/<partition>_<suite>/`: scheduled forecasts including unavailable
  decisions, condition/horizon/approach errors, paired vessel bootstrap intervals,
  day/seed/category/support/seen-vessel breakdowns and worst observed failures.
- Review results: `review_summary.csv`, `error_coverage_curves.csv` and
  `matched_coverage.csv`. Full-cohort errors precede any acceptance filtering.
- `results/evaluation_primary/adoption_check.json`: the fixed 10% degraded gain,
  <=5% nominal cost and B+guard contribution checks. A failed check is a negative
  finding, not permission to retune on this evaluation.

Existing parsing, approach construction, original feature summaries, model
constructors, imputation, fitting, weighting and scoring are reused. The shared
predictor now serializes its feature schema and clock while supporting old A/B
joblib bundles. Only trusted local bundles should be loaded.

The reviewed OllyC1 repository inspired speed summaries, navigation stability,
physical consistency and preprocessing packaging, as recorded in `PLAN.md` at
revision `dda0d078c6365929f128627cf289907f700bcb48`. This implementation does not
copy its source code or use its complete-journey or target-derived features.

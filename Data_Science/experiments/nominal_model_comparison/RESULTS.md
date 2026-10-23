# All-nominal A/B/C: 2023 fitting, full March 2024 test

**C in this comparison is the nominal-only C artifact (`C_nominal.joblib`).**
All three models use original AIS reports without injected delays or position
errors during fitting, tuning or this evaluation. Their model-specific feature
sets, guard behavior and target clocks remain as implemented.

## Shared periods and records

| Period | Role | Decisions | Approaches |
|---|---|---:|---:|
| January 1–June 29, 2023 | Fitting | 27,263 | 1,319 |
| June 30–July 19, 2023 | Hyperparameter selection / early stopping | 3,108 | 140 |
| March 1–31, 2024 | Test | 5,382 per model | 243 |

The fitting and tuning decision identities match exactly between A, B and
nominal C. Fitted preprocessing uses the fitting partition. The test includes
all 31 days of March and the same 219 vessels, schedules and original arrival
labels for every model. No March records enter fitting or tuning, and no April
2024 records are evaluated. Qualifying cargo/tanker analytical-gate approaches
define the cohort; this is not a verified docking-time benchmark.

## Full-March results

| Model | Approach-weighted MAE (min) | Forecast MdAE (min) | Forecast P95 AE (min) | Prediction coverage |
|---|---:|---:|---:|---:|
| A: quadratic ridge | 7.019 | 3.459 | 36.725 | 100% |
| B: ordinary XGBoost | 6.643 | 3.164 | 37.361 | 100% |
| C: nominal-only optimized XGBoost | 6.610 | 3.097 | 37.097 | 100% |

MAE gives each approach equal weight. MdAE is the median absolute error across
individual forecasts, and P95 is their 95th-percentile absolute error.

Nominal C has the lowest MAE and MdAE in this comparison. Its advantage over B
is **0.033 minutes (1.97 seconds) in MAE** and **0.067 minutes (4.01 seconds) in
MdAE**. C improves on B's mean error for 133 of 243 approaches (54.7%).
The paired vessel-bootstrap 95% interval for C-minus-B MAE is
**[-0.125, +0.050] minutes**, spanning zero. The observed gain is small and does
not establish a clear population-level advantage. A has the lowest forecast P95.

These are point predictions before interval-based deferral. This comparison
does not apply the augmented C's calibration to nominal C. It does not evaluate
the models' robustness to simulated faults. March was held out from fitting
and tuning, but choosing this C variant after examining March results is a
post-hoc model-selection decision; March is not a fresh confirmation set for
that choice.

## Saved model and reproducibility

Nominal C was already fitted as part of the 2023 run. The audit checks its
nominal-only fitting flag, training/development view hashes, exact row counts,
matching A/B decision identities and 2023 time boundaries. Fresh inference
validates saved model/configuration/code signatures. All test predictions are
available and finite, with identical decision sets across A/B/C.

The underlying artifacts are retained:

- A/B: `artifacts/data_eval/optimized/frozen_baselines/{quadratic,xgboost}/model.joblib`
- Nominal C used here: `artifacts/data_eval/optimized/models/C_nominal.joblib`
- Augmented C retained separately: `artifacts/data_eval/optimized/models/C.joblib`

Paths are relative to `Data_Science`. No model was refitted, overwritten or
switched in the serving application. [verification.json](verification.json)
records exact artifact paths/hashes, verified fitting periods and results.
Detailed predictions, summary and uncertainty are under
`artifacts/data_eval/nominal_comparison/`.

To reproduce from the `data_eval` worktree's `Data_Science` folder:

```powershell
& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -m experiments.nominal_model_comparison.run
```

The command was executed successfully against the actual saved models and data.

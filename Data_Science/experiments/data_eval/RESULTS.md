# 220-day 2023 retraining; March 2024 evaluation

A: quadratic ridge regression. B: ordinary XGBoost. C: degradation-aware XGBoost.

All 220 declared official NOAA daily point archives (January 1–August 8, 2023) were acquired. The regional source contains 33,094,542 reports.

Malformed national CSV rows quarantined during ingestion: 15. Original rejected lines and parser reasons are preserved in daily reject logs. This national count is not a count of Hampton Roads omissions.

January 1–June 29, 2023: fit (180 days); June 30–July 19: hyperparameter selection (20 days); July 20–29: internal check (10 days); July 30–August 8: calibration (10 days). Entire March 2024: evaluation. April 2024 data were not used. Boundary-spanning approaches are purged. March was used in earlier project runs, so this is a held-out comparison for these new fits, not a previously unseen research dataset.

## Original March reports

| Model | Approaches | MAE (min) | Median AE (min) | P95 AE (min) | Coverage |
|---|---:|---:|---:|---:|---:|
| A | 243 | 7.019 | 3.459 | 36.725 | 100.0% |
| B | 243 | 6.643 | 3.164 | 37.361 | 100.0% |
| C | 243 | 7.032 | 3.616 | 38.643 | 100.0% |

MAE gives each approach equal weight. Median and P95 describe individual forecasts. Coverage includes unavailable scheduled forecasts; interval-based deferral is reported separately.

## Interpretation and calibration

B has the lowest approach-weighted MAE on the original March reports. C's MAE is
0.389 minutes higher than B's; the paired vessel-bootstrap 95% interval is
[0.290, 0.522] minutes. C beats B on 50 of 243 approaches (20.6%). This nominal
evaluation does not establish that C improves accuracy or robustness under faults.
A produced 9 expired forecasts, B produced 16, and C produced none.

Prediction availability is 100%, but the existing calibrated acceptance policy
accepts **zero forecasts** from all three models. The interval half-widths are
30.56 minutes for A, 44.58 for B and 45.34 for C, exceeding the configured
five-minute maximum. Whole-approach interval coverage on March is 90.1%, 96.3%
and 95.5%, respectively. These broad intervals were calibrated on the separate
69-approach 2023 cohort. The five-minute rule was retained; it was not relaxed
after inspecting March. Prediction coverage therefore must not be interpreted
as useful accepted-output coverage. See
`artifacts/data_eval/optimized/results/evaluation_nominal/review_summary.csv`.

## Training augmentation

C retains its established four-condition training mixture. Added delivery delays and position offsets are simulated disruption applied only to training/development views. July 30–August 8 calibration and March evaluation use original reports without injected faults. Instant nominal delivery remains an assumption because source delivery timestamps are unavailable. No robustness gain under simulated faults is claimed by this nominal evaluation.

## Cohort and artifacts

```json
{
  "calibration": {
    "decisions": 1407,
    "approaches": 69,
    "vessels": 67
  },
  "evaluation": {
    "decisions": 5382,
    "approaches": 243,
    "vessels": 219
  },
  "exploratory": {
    "decisions": 1780,
    "approaches": 87,
    "vessels": 87
  },
  "train": {
    "decisions": 27263,
    "approaches": 1319,
    "vessels": 799
  },
  "validation": {
    "decisions": 3108,
    "approaches": 140,
    "vessels": 136
  }
}
```

Arrival means an interpolated east-to-west crossing of the existing analytical gate, not docking. Results are conditional on qualifying observed cargo/tanker crossings. Repeated vessels may occur across periods; MMSI is not a model feature.

The supplied GeoPackage has 7,596,268 summarized track segments without per-report timing and was audited, not converted into fabricated reports. See `compatibility_report.json`.

Models and detailed predictions are under `artifacts/data_eval/`. See `optimized/results/evaluation_nominal/` for paired vessel uncertainty, per-vessel errors, coverage and calibration/deferral diagnostics. The three additional fitted C controls support internal attribution only.

Saved models:

- A: `artifacts/data_eval/baselines/quadratic/model.joblib`
- B: `artifacts/data_eval/baselines/xgboost/model.joblib`
- C: `artifacts/data_eval/optimized/models/C.joblib`

Paths above are relative to `Data_Science`. The branch is `data_eval`, checked out
at `C:\Users\jerem\Downloads\the_antidote_data_eval`. Earlier model artifacts were
retained. All 556 tests passed. [verification.json](verification.json) records
model hashes and final source, date, metric and serialization checks.

Source: https://www.coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/index.html

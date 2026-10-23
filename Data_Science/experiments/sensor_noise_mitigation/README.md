# Sensor noise: replacement versus blending

This follow-up measures the current sensor-noise mitigation against no additional
mitigation, a 50/50 blend, and a blend fitted on March development observations.
It does not change the deployed strategy, retrain an ETA model, or recalibrate
the forecast review policy.

## Model version

The available local C bundle is `artifacts/optimized/march_gate_v1/models/C.joblib`.
The current vessel-class v2 bundles referenced by the updated demo are absent on
this machine. These results must therefore be labeled **exploratory v1 results**,
never attributed to the updated v2 model or combined with its saved attack table.

The experiment checks the v1 bundle hash and reproduces every saved nominal v1
prediction before reporting. The ordinary demo compatibility checks remain
unchanged. This experiment intentionally loads the legacy bundle for a separate,
explicitly identified study. It does not make that bundle current or compatible
with the v2 service.

## Comparison

- All strategies retain the existing position support checks, 2-knot speed
  threshold, 15-degree course threshold and decision-time review behavior.
- Only flagged speed/course fields are blended. Unflagged readings remain as
  received. Invalid or unsupported reference tracks receive no repair.
- Replacement moves all the way to the position estimate. The 50/50 control
  moves halfway along the difference.
- The development blend learns separate fixed correction fractions for speed
  and course on March 20–24, using squared deviation from original AIS readings.
  Each approach has equal total weight per scenario/seed realization. Fractions
  are frozen before April evaluation. Original readings are evaluator references,
  not independently verified physical truth.
- Course interpolation follows the shortest compass arc, so 359 and 1 degrees
  blend toward north. It never uses a plain arithmetic mean of compass angles.
- Position estimates use only each report's causal prefix. Position calculations
  are cached with neutral speed/course placeholders preserving observable
  missingness. All source histories must have unique observation times.
- Cached reconstruction is checked against `SensorNoiseMitigation.reconstruct_reports`
  on the entire extreme-noise history of every evaluation approach. Final high-noise
  decision features are checked against `mitigated_noise_view` on every approach.
- The same frozen C model receives the resulting derived motion features. Raw
  quality evidence, source records, prediction clocks and arrival labels are kept.

## Evaluation

April 8–21 has 112 approaches, 110 vessels and 2,402 scheduled decision times.
The design includes clean input and all four Gaussian-noise severities, each with
three paired seeds and 100% of eligible speed/course reports selected. Source
positions and timestamps are unchanged. Instant delivery is a simulation
assumption. April has been inspected previously; this is not a pristine holdout.

ETA MAE gives each approach equal weight, averaging decisions and seeds within
approaches. Median, P95 and MSE pool supported decisions/seed realizations.
Paired MAE-difference intervals use 2,000 vessel-cluster bootstrap draws.
Unavailable forecasts remain in the coverage denominator. Mitigation support and
actual intervention share are reported separately from ETA output coverage.

Sensor MSE/MAE measure deviation from the original AIS reference, with equal
approach weights. RMSE is the square root of that aggregate MSE. This measures
recovery from injected corruption, not absolute real-world sensor accuracy.

Run from `Data_Science`:

```sh
.venv/bin/python experiments/sensor_noise_mitigation/run.py --workers 4
```

See `results/REPORT.md` for findings and `results/protocol.json` for the exact
configuration, model hash, cohort and validation results. Detailed prediction
and sensor CSVs are locally generated and ignored by the repository.

## Research behind the alternatives

- [Duran-Martin et al., Outlier-robust Kalman Filtering through Generalised Bayes
  (ICML 2024)](https://arxiv.org/html/2405.05646v2): uncertainty-weighted filtering,
  smooth downweighting, and threshold-based rejection. This motivates comparing
  a blend with a hard switch; it does not establish which works best here.
- [Cole and Schamberg, Unscented Kalman Filter for Long-Distance Vessel Tracking
  in Geodetic Coordinates (2021)](https://arxiv.org/abs/2111.13254): AIS state
  estimation with a dynamic filtering model, evaluated in simulation and field
  testing. Our five-minute line fit is a simpler constant-velocity approximation.
- [Wang et al., Outlier-robust Kalman Filter in the Presence of Correlated
  Measurements](https://arxiv.org/abs/2011.13353): correlation and outliers matter
  when weighting observations. AIS position and navigation fields may share
  errors, so independent inverse-variance weighting requires justification.

The fitted blend in this experiment is a fixed development baseline, not an
adaptive uncertainty model or a Kalman filter. Any further threshold or method
selection after inspecting April requires a new untouched evaluation period.

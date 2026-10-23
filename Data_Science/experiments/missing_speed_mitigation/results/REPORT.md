# MissingSpeedMitigation on frozen optimized XGBoost

Simulated missing-speed corruption on original AIS histories. No model retraining. Poly and ordinary XGBoost remain unchanged. Negative paired delta favors mitigation.

Policy is fixed before evaluation: five-minute trailing fit, at least three positions spanning 60 seconds, no gap over 120 seconds, max speed 60 knots, max fit residual 50 m, max pair-velocity disagreement 2 knots. Unsupported speeds stay missing. The existing C guard runs first. No report timestamps or positions change; the original missing-speed fraction and history_missing feature remain visible to C.

## March development

| Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Reconstructed missing bins |
|---:|---:|---:|---:|---:|---|---:|---:|
| 0% | 5.2772 | 5.2772 | 2.8610 | 2.8610 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| 10% | 5.3988 | 5.2710 | 2.9733 | 2.8610 | -0.1278 [-0.1893, -0.0655] | 100.00% | 72.22% |
| 25% | 5.6800 | 5.3203 | 3.2064 | 2.9068 | -0.3597 [-0.5111, -0.2190] | 100.00% | 72.21% |
| 50% | 5.9612 | 5.3385 | 3.7357 | 2.9068 | -0.6227 [-0.8712, -0.3926] | 100.00% | 72.29% |
| 100% | 9.3465 | 5.4286 | 7.1809 | 2.9388 | -3.9179 [-4.7146, -2.9373] | 100.00% | 72.42% |

## April follow-up evaluation

| Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Reconstructed missing bins |
|---:|---:|---:|---:|---:|---|---:|---:|
| 0% | 5.8598 | 5.8598 | 2.8070 | 2.8070 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| 10% | 6.0323 | 5.8763 | 3.0199 | 2.8070 | -0.1560 [-0.2091, -0.1047] | 100.00% | 73.74% |
| 25% | 6.2740 | 5.9377 | 3.3397 | 2.8329 | -0.3363 [-0.4250, -0.2421] | 100.00% | 73.27% |
| 50% | 6.7409 | 6.0205 | 3.9444 | 2.9254 | -0.7204 [-0.8839, -0.5513] | 100.00% | 73.43% |
| 100% | 10.6382 | 6.1905 | 7.8980 | 3.0130 | -4.4478 [-5.0593, -3.7851] | 100.00% | 73.33% |

MAE weights approaches equally, with seeds averaged within approach. MdAE/P95 pool errors. Both arms use identical support, decision times and original crossing labels. Reconstruction rate counts missing guarded bins repeated across decision windows, not unique raw reports. Full masking is seed-invariant and runs once. Partial masking uses seeds 4201–4203.

## Interpretation and variation across approaches

At 10% masking: 84 approaches improved, 28 worsened, 0 were unchanged. Worst approach-level mean change: +0.5051 minutes.
At 25% masking: 87 approaches improved, 25 worsened, 0 were unchanged. Worst approach-level mean change: +0.8827 minutes.
At 50% masking: 96 approaches improved, 16 worsened, 0 were unchanged. Worst approach-level mean change: +2.7305 minutes.
At 100% masking: 105 approaches improved, 7 worsened, 0 were unchanged. Worst approach-level mean change: +4.2661 minutes.

The clean selected cohort had no missing guarded SOG requiring repair; its exact identity is not validation on naturally missing-speed cases. Aggregate gains do not imply that every vessel or every decision benefits.

A fit estimates recent average motion, not independently verified instantaneous speed. Turns, acceleration and coherent position errors can still defeat reconstruction. C's trees and imputer are unchanged; derived values can still change their split/missing-indicator behavior. Keeping original missingness features exposes uncertainty but does not guarantee calibrated predictions.

This is a fixed-policy follow-up experiment on previously inspected data, not evidence of universal protection. Stress fractions are not measured source failure rates. Arrival means analytical crossing, not docking. P95, diagnostics and per-decision results are in locally ignored CSVs.

Reproduce from Data_Science: `python experiments/missing_speed_mitigation/run.py`.

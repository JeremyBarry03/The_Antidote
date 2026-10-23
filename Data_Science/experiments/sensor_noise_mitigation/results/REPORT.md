# Sensor noise mitigation: replacement versus blending

**Exploratory frozen v1 C model. These are not vessel-class v2 demo results.**

The current v2 bundles are absent locally. The available v1 bundle hash was verified, and all 2,402 nominal predictions were reproduced against the saved v1 evaluation before reporting. No model was retrained, no review policy recalibrated, and no production strategy changed.

## ETA accuracy

MAE in minutes to the analytical crossing, with equal approach weights. Lower is better. Every method has the same scheduled decisions; unsupported mitigation leaves the existing forecast inputs unchanged.

| Noise | No additional mitigation | Current replacement | 50/50 blend | Development blend |
|---|---:|---:|---:|---:|
| No added noise | 5.8086 | 5.8227 | 5.8046 | 5.8208 |
| Low | 5.8275 | 5.8501 | 5.8290 | 5.8485 |
| Medium | 6.6252 | 6.4036 | 6.3908 | 6.3973 |
| High | 9.5404 | 6.7999 | 7.1173 | 6.7922 |
| Extreme | 20.5170 | 7.1345 | 10.1057 | 7.1537 |

## Coverage and tail errors

Output coverage is separate from permission to reconstruct. Declining a repair does not remove that forecast from accuracy metrics.

| Noise | Method | Output coverage | Mitigation supported | Intervention share | Median error (min) | P95 error (min) | MSE (min²) |
|---|---|---:|---:|---:|---:|---:|---:|
| No added noise | unmitigated | 100.00% | 95.92% | 0.00% | 2.8696 | 22.3041 | 115.4531 |
| No added noise | replacement | 100.00% | 95.92% | 10.87% | 2.8963 | 22.3041 | 115.1651 |
| No added noise | half_blend | 100.00% | 95.92% | 10.87% | 2.8746 | 22.3041 | 115.0077 |
| No added noise | development_blend | 100.00% | 95.92% | 10.87% | 2.8905 | 22.3041 | 115.2075 |
| Low | unmitigated | 100.00% | 95.92% | 0.00% | 2.9153 | 22.7312 | 117.2259 |
| Low | replacement | 100.00% | 95.92% | 16.56% | 2.9646 | 22.7039 | 116.6025 |
| Low | half_blend | 100.00% | 95.92% | 16.56% | 2.9171 | 22.7039 | 116.6184 |
| Low | development_blend | 100.00% | 95.92% | 16.56% | 2.9538 | 22.7039 | 116.6032 |
| Medium | unmitigated | 100.00% | 95.92% | 0.00% | 3.4705 | 23.8191 | 161.4300 |
| Medium | replacement | 100.00% | 95.92% | 52.28% | 3.4520 | 23.5658 | 138.9156 |
| Medium | half_blend | 100.00% | 95.92% | 52.28% | 3.3947 | 23.5554 | 140.2802 |
| Medium | development_blend | 100.00% | 95.92% | 52.28% | 3.4360 | 23.6025 | 138.9061 |
| High | unmitigated | 100.00% | 95.92% | 0.00% | 4.7518 | 33.5845 | 375.9058 |
| High | replacement | 100.00% | 95.92% | 95.17% | 3.7307 | 24.1279 | 153.2607 |
| High | half_blend | 100.00% | 95.92% | 95.17% | 4.0512 | 24.5541 | 170.9846 |
| High | development_blend | 100.00% | 95.92% | 95.17% | 3.7104 | 23.9220 | 153.1137 |
| Extreme | unmitigated | 100.00% | 95.92% | 0.00% | 8.2872 | 91.8925 | 1483.0191 |
| Extreme | replacement | 100.00% | 95.92% | 95.92% | 3.6788 | 24.9553 | 188.6410 |
| Extreme | half_blend | 100.00% | 95.92% | 95.92% | 5.3026 | 34.3501 | 394.3761 |
| Extreme | development_blend | 100.00% | 95.92% | 95.92% | 3.7351 | 24.8240 | 189.3049 |

## Paired uncertainty

Differences are method MAE minus reference MAE, in minutes. Negative favors the method. Intervals use 2,000 paired vessel-cluster bootstrap draws across 110 vessels; they describe this selected cohort, not universal reliability.

| Noise | Method | Reference | MAE difference | 95% interval | Approach win share |
|---|---|---|---:|---:|---:|
| No added noise | replacement | unmitigated | +0.0141 | [-0.0110, +0.0399] | 24.11% |
| No added noise | half_blend | unmitigated | -0.0040 | [-0.0189, +0.0106] | 21.43% |
| No added noise | development_blend | unmitigated | +0.0122 | [-0.0111, +0.0366] | 23.21% |
| No added noise | half_blend | replacement | -0.0180 | [-0.0382, +0.0003] | 23.21% |
| No added noise | development_blend | replacement | -0.0018 | [-0.0100, +0.0055] | 11.61% |
| Low | replacement | unmitigated | +0.0226 | [-0.0096, +0.0534] | 41.07% |
| Low | half_blend | unmitigated | +0.0016 | [-0.0160, +0.0191] | 36.61% |
| Low | development_blend | unmitigated | +0.0210 | [-0.0091, +0.0505] | 39.29% |
| Low | half_blend | replacement | -0.0210 | [-0.0426, -0.0002] | 48.21% |
| Low | development_blend | replacement | -0.0016 | [-0.0097, +0.0059] | 23.21% |
| Medium | replacement | unmitigated | -0.2216 | [-0.3561, -0.1011] | 56.25% |
| Medium | half_blend | unmitigated | -0.2344 | [-0.3497, -0.1331] | 70.54% |
| Medium | development_blend | unmitigated | -0.2278 | [-0.3599, -0.1087] | 57.14% |
| Medium | half_blend | replacement | -0.0128 | [-0.0533, +0.0309] | 55.36% |
| Medium | development_blend | replacement | -0.0062 | [-0.0143, +0.0012] | 58.04% |
| High | replacement | unmitigated | -2.7405 | [-3.1224, -2.3615] | 95.54% |
| High | half_blend | unmitigated | -2.4230 | [-2.7501, -2.0989] | 97.32% |
| High | development_blend | unmitigated | -2.7482 | [-3.1307, -2.3718] | 94.64% |
| High | half_blend | replacement | +0.3174 | [+0.2130, +0.4308] | 28.57% |
| High | development_blend | replacement | -0.0077 | [-0.0317, +0.0133] | 54.46% |
| Extreme | replacement | unmitigated | -13.3825 | [-14.3726, -12.4635] | 100.00% |
| Extreme | half_blend | unmitigated | -10.4113 | [-11.1852, -9.6393] | 100.00% |
| Extreme | development_blend | unmitigated | -13.3633 | [-14.3366, -12.4497] | 100.00% |
| Extreme | half_blend | replacement | +2.9712 | [+2.5840, +3.3833] | 2.68% |
| Extreme | development_blend | replacement | +0.0192 | [-0.0199, +0.0591] | 39.29% |

## Recovery of injected sensor corruption

RMSE versus original AIS readings. These readings are evaluator references, not verified physical truth. Equal approach weights; speed is knots, course is shortest-arc degrees. All reports remain in this score, including ones that could not be repaired.

| Noise | Field | No additional mitigation | Current replacement | 50/50 blend | Development blend |
|---|---|---:|---:|---:|---:|
| No added noise | speed | 0.0000 | 0.1398 | 0.0699 | 0.1361 |
| No added noise | course | 0.0000 | 2.3179 | 1.1589 | 2.0456 |
| Low | speed | 0.4991 | 0.5239 | 0.4967 | 0.5218 |
| Low | course | 1.9790 | 3.0426 | 2.2650 | 2.8330 |
| Medium | speed | 0.9980 | 0.8797 | 0.8827 | 0.8768 |
| Medium | course | 4.9475 | 5.3494 | 4.8992 | 5.2034 |
| High | speed | 1.9957 | 1.0556 | 1.3198 | 1.0522 |
| High | course | 9.8950 | 7.5486 | 7.8521 | 7.4325 |
| Extreme | speed | 3.9575 | 1.2378 | 2.2270 | 1.2374 |
| Extreme | course | 19.7899 | 8.4624 | 12.0144 | 8.5447 |

## Design and interpretation

- March 20–24 development: 36 approaches. The fitted correction moves 97.3676% of a flagged speed discrepancy and 88.2524% of a flagged course discrepancy toward the position estimate. These fixed fractions are frozen before April scoring; they are not an adaptive uncertainty model or a Kalman filter.
- April 8–21: 112 approaches, 110 vessels, 2,402 decision clocks and 11,605 source reports. April has previously been inspected, so this is a follow-up analysis rather than a new protected holdout.
- Both navigation fields receive independent Gaussian noise on 100% of eligible reports. Low sigma: 0.5 kn / 2°; medium: 1 kn / 5°; high: 2 kn / 10°; extreme: 4 kn / 20°. Three paired attack seeds per severity; clean input is evaluated once.
- Every alternative changes only flagged fields after the same geometry checks. This is a comparison of the action taken after detection, not a comparison of new detectors or blending every observation. Small errors beneath the existing thresholds remain untouched.
- Only already received position prefixes support reconstruction. Speed/course reference values and arrival labels are excluded from prediction inputs. Course blends follow the shortest compass arc.
- Current C quality features continue to describe the raw received stream. Only its derived motion inputs are changed, matching the production adapter.
- Validation: 224 checks compare cached reconstruction or model features with the actual mitigation/serving code. Maximum nominal prediction difference: 1.42e-14 minutes. Source and model hashes unchanged.
- The clock and target represent an analytical gate crossing, not berth docking. Positions are unchanged by this attack and delivery is simulated as immediate. Coherent position errors, maneuvers and other attacks require separate evaluation.
- A reduction in sensor-reference error does not establish an equal reduction in ETA error. Original reference readings are not a guarantee of physical accuracy, and a clean-input intervention is an intervention without injected noise, not proof of a false alarm in real operation.

## Research

[Duran-Martin et al. (ICML 2024)](https://arxiv.org/html/2405.05646v2) describe uncertainty-weighted Kalman updates and both smooth downweighting and threshold rejection for outliers. [Cole and Schamberg (2021)](https://arxiv.org/abs/2111.13254) evaluate dynamic AIS vessel-state filtering in simulation and field tests. [Wang et al.](https://arxiv.org/abs/2011.13353) study outliers with correlated measurements. These support the candidate mechanisms, not an accuracy claim for this implementation.

Reproduce from Data_Science: `.venv/bin/python experiments/sensor_noise_mitigation/run.py --workers 4`. The script preserves source data and model bundles. See protocol.json, eta_summary.csv, sensor_summary.csv, paired_intervals.csv and predictions.csv for details.

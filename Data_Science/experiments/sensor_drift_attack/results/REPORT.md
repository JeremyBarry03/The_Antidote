# SensorDriftAttack: automatic speed bias, frozen corrected A/B

This is a simulated sensor fault on original AIS observations. Original reported
speed is a reference, not independently verified physical truth. The tested rates
are stress settings, not estimated real-world sensor drift rates. Nothing forces
ETA degradation: prediction errors may worsen, improve or remain unchanged.

Only sog changes. Every report, position, course, class, identity, measurement and
delivery timestamp, decision clock and analytical crossing label is retained.
The bias starts at zero at each approach's first supplied report and progresses
in one direction, with a gently varying rate and a smooth 3-knot limit. Negative
rates underreport speed; positive rates overreport it. Variation is 25% with a
20-minute cycle. Seeds 4201/4202/4203 change one reproducible phase per vessel;
they are not training seeds. No individual reports are randomly selected.

Corrected saved A (quadratic Ridge) and B (XGBoost) are unchanged. The evaluation
uses 112 April approaches / 110 vessels / 2,402 decision times. Both original-feed
baselines are reproduced against the preceding corrected-model study. Models are
neither retrained nor recalibrated, and no new mitigation is introduced.

## Whole-approach errors

MAE gives approaches equal weight, averaging realizations within each approach.
MdAE and P95 pool prediction/seed absolute errors. All values are minutes to the
analytical crossing, not verified docking. Lower is better.

| Drift rate (knots/minute) | A MAE / MdAE | B MAE / MdAE | A P95 | B P95 |
|---|---:|---:|---:|---:|
| 0 (original) | 7.3169 / 4.9187 | 6.2989 / 2.5565 | 23.4782 | 21.8750 |
| -0.025 | 9.1270 / 6.4934 | 8.7195 / 5.4973 | 28.5080 | 23.7459 |
| -0.050 | 11.3240 / 8.6682 | 11.7602 / 7.8214 | 34.0099 | 30.5001 |
| -0.100 | 13.4101 / 10.4148 | 14.3794 / 9.7887 | 37.6435 | 35.7014 |
| +0.025 | 8.1885 / 6.3549 | 7.0028 / 3.9431 | 23.6279 | 23.4559 |
| +0.050 | 9.0876 / 7.4956 | 7.8165 / 4.9251 | 24.7358 | 23.8854 |
| +0.100 | 9.8643 / 8.2843 | 8.4543 / 5.4866 | 26.9072 | 26.3776 |

## Paired MAE changes

Changes compare each attacked prediction with its own original-feed forecast. Intervals use 1,000 paired vessel-cluster bootstrap draws.

| Drift rate | A change [95% interval] | B change [95% interval] |
|---|---:|---:|
| -0.025 | +1.8101 [+1.5582, +2.1176] | +2.4206 [+2.0648, +2.7915] |
| -0.050 | +4.0071 [+3.6002, +4.4721] | +5.4613 [+4.7907, +6.3358] |
| -0.100 | +6.0933 [+5.5091, +6.7401] | +8.0805 [+7.0547, +9.3847] |
| +0.025 | +0.8717 [+0.5936, +1.1648] | +0.7039 [+0.3184, +1.0715] |
| +0.050 | +1.7707 [+1.3451, +2.1792] | +1.5176 [+0.9558, +2.0808] |
| +0.100 | +2.5474 [+2.0135, +3.0404] | +2.1554 [+1.4914, +2.8303] |

## Bounds and interpretation

Reported speeds are bounded to 0–102.2 knots. Existing missing speed remains missing. Audit files separate requested bias from the actual applied change and mark faults only when a valid speed changes. The smooth 3-knot bias limit is a cap, not a promise of a 3-knot error at 30 minutes. Near zero or the upper speed bound, clipping can further reduce the applied bias.

| Drift rate | Reports changed | Reports clipped | Maximum absolute requested / applied bias |
|---|---:|---:|---:|
| -0.025 | 34,479 | 0 | 2.7172 / 2.7172 knots |
| -0.050 | 34,479 | 0 | 2.9854 / 2.9854 knots |
| -0.100 | 34,479 | 0 | 3.0000 / 3.0000 knots |
| +0.025 | 34,479 | 0 | 2.7172 / 2.7172 knots |
| +0.050 | 34,479 | 0 | 2.9854 / 2.9854 knots |
| +0.100 | 34,479 | 0 | 3.0000 / 3.0000 knots |

Forecast coverage is 100.00% across all configurations. Report-count exposure totals pool three scenario realizations, not distinct source measurements. April was inspected previously; this is a follow-up study, not a pristine holdout. Original reports can already contain imperfections. These results do not prove that natural sensor drift caused the baseline ETA errors.

The attack never changes forecasts or recovers missing data. Audit truth is excluded from model inputs. No source CSVs, saved models, shared feature/training code, service or frontend files change. CSV outputs remain local and ignored.

Reproduce from Data_Science: `python experiments/sensor_drift_attack/run.py`.

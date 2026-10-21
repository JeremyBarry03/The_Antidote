# PositionJumpAttack: frozen A/B/C robustness

Simulated corruption of copied AIS latitude/longitude. Original reported coordinates are references, not independently verified physical truth. The pattern is motivated by original jump-and-return inconsistencies; the underlying GPS/identity/timing/processing cause was not established.

Percentages select eligible reports using the existing seed/vessel/timestamp hash threshold. Requested percentages are not exact-count quotas. A reproducible bearing per MMSI displaces selected fixes; unselected fixes retain their original positions. At 100% the whole supplied feed/window is displaced, with no intervening correct fixes inside it. The Python/API window is half-open [start,end). No reports are removed. Speed, course, classification, identity, timing, decision schedule and original crossing targets stay unchanged.

The cohort contains 112 April approaches / 110 vessels / 2,402 decision times. A/B/C saved artifacts passed their compatibility/hash checks. No retraining, recalibration or new mitigation. C retains its existing guard.

Completed settings: [(2000.0, 0.1), (2000.0, 0.2), (2000.0, 0.25), (2000.0, 0.5), (2000.0, 1.0), (500.0, 0.25), (20000.0, 0.25), (40000.0, 0.25)]. Each attacked setting uses seeds 4201–4203 to vary selection and bearing, not model training. Main prevalence comparison holds displacement at 2000 meters; additional distances are compared at 25%. All are stress settings; observed severe source jumps were much rarer than these injected percentages.

Window: Whole supplied approach feed

MAE weights approaches equally, averaging scenario realizations within each approach. MdAE and P95 pool absolute errors over decision/seed pairs. Changes compare identical supported original/attacked decisions. Coverage retains every scheduled decision in the denominator. Units are minutes to the analytical crossing, not docking.

| Displacement | Selected fraction | Model | MAE | MdAE | Δ MAE | Δ MdAE | P95 | Coverage |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Original | 0% | A | 7.3169 | 4.9187 | +0.0000 | +0.0000 | 23.4782 | 100.00% |
| Original | 0% | B | 6.2989 | 2.5565 | +0.0000 | +0.0000 | 21.8750 | 100.00% |
| Original | 0% | C | 5.8598 | 2.8070 | +0.0000 | +0.0000 | 22.1674 | 100.00% |
| 2 km | 10% | A | 9.5360 | 6.3600 | +2.2192 | +1.4413 | 30.4843 | 100.00% |
| 2 km | 10% | B | 6.6221 | 2.8428 | +0.3232 | +0.2863 | 22.0259 | 100.00% |
| 2 km | 10% | C | 6.3081 | 3.1309 | +0.4484 | +0.3239 | 23.1622 | 100.00% |
| 2 km | 20% | A | 11.4098 | 7.7767 | +4.0929 | +2.8579 | 35.5294 | 100.00% |
| 2 km | 20% | B | 6.9454 | 3.1391 | +0.6466 | +0.5826 | 22.5572 | 100.00% |
| 2 km | 20% | C | 6.6509 | 3.4095 | +0.7911 | +0.6025 | 23.7527 | 100.00% |
| 2 km | 25% | A | 12.1304 | 8.5186 | +4.8135 | +3.5999 | 36.7556 | 100.00% |
| 2 km | 25% | B | 7.1202 | 3.3297 | +0.8213 | +0.7732 | 22.8385 | 100.00% |
| 2 km | 25% | C | 6.7720 | 3.5171 | +0.9122 | +0.7101 | 23.8583 | 100.00% |
| 2 km | 50% | A | 14.4446 | 11.3111 | +7.1278 | +6.3923 | 39.4758 | 100.00% |
| 2 km | 50% | B | 7.7887 | 4.1733 | +1.4898 | +1.6168 | 23.6158 | 100.00% |
| 2 km | 50% | C | 7.4377 | 4.3142 | +1.5779 | +1.5071 | 25.0227 | 100.00% |
| 2 km | 100% | A | 9.6237 | 7.3921 | +2.3068 | +2.4734 | 28.1958 | 100.00% |
| 2 km | 100% | B | 9.4628 | 5.3116 | +3.1639 | +2.7551 | 25.4920 | 100.00% |
| 2 km | 100% | C | 7.5957 | 4.8019 | +1.7360 | +1.9949 | 24.3794 | 100.00% |
| 0.5 km | 25% | A | 7.8367 | 5.6587 | +0.5198 | +0.7399 | 24.2670 | 100.00% |
| 0.5 km | 25% | B | 6.3875 | 2.6317 | +0.0886 | +0.0752 | 21.8751 | 100.00% |
| 0.5 km | 25% | C | 5.8938 | 2.8841 | +0.0340 | +0.0770 | 22.2962 | 100.00% |
| 20 km | 25% | A | 164.2318 | 52.3506 | +156.9149 | +47.4319 | 732.9888 | 100.00% |
| 20 km | 25% | B | 15.7561 | 5.1222 | +9.4572 | +2.5657 | 54.1468 | 100.00% |
| 20 km | 25% | C | 10.0464 | 3.8854 | +4.1867 | +1.0784 | 41.7210 | 100.00% |
| 40 km | 25% | A | 560.4295 | 104.4454 | +553.1126 | +99.5267 | 2846.4198 | 100.00% |
| 40 km | 25% | B | 19.2195 | 5.9714 | +12.9206 | +3.4149 | 72.2192 | 100.00% |
| 40 km | 25% | C | 11.4086 | 3.9550 | +5.5488 | +1.1480 | 51.7176 | 100.00% |

CSV outputs include all predictions, per-seed summaries, displacement/selection audit and 1,000-draw paired vessel-cluster MAE-change intervals. CSVs remain locally ignored. Hashes of source data, frozen models and existing inference/training code are checked before and after. Audience-only injection truth is never fed to the predictors.

Model histories and analytical crossing labels are never rebuilt from corrupted coordinates, even if an injected fix appears across the gate. The original 112-approach cohort did not include the severe jump endpoints identified by the location audit. This experiment tests a simulated failure pattern on that cohort; it does not attribute its original ETA errors to those source anomalies. April has been inspected previously and is not a pristine holdout.

Completed 24 attacked configurations and 180,150 model forecasts including originals. Minimum forecast coverage: 100.00%. Protected hashes unchanged: True.

Reproduce from Data_Science: `python experiments/position_jump_attack/run.py`.
Optional timed run: `--window-start-minutes 20 --window-duration-minutes 15 --output artifacts/position_jump_window`. Other settings are listed by `--help`.

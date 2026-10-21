# PositionJumpAttack: frozen A/B/C robustness

Simulated corruption of copied AIS latitude/longitude. Original reported coordinates are references, not independently verified physical truth. The pattern is motivated by original jump-and-return inconsistencies; the underlying GPS/identity/timing/processing cause was not established.

Percentages select eligible reports using the existing seed/vessel/timestamp hash threshold. Requested percentages are not exact-count quotas. A reproducible bearing per MMSI displaces selected fixes; unselected fixes retain their original positions. At 100% the whole supplied feed/window is displaced, with no intervening correct fixes inside it. The Python/API window is half-open [start,end). No reports are removed. Speed, course, classification, identity, timing, decision schedule and original crossing targets stay unchanged.

The cohort contains 112 April approaches / 110 vessels / 2,402 decision times. A/B/C saved artifacts passed their compatibility/hash checks. No retraining, recalibration or new mitigation. C retains its existing guard.

Completed settings (mean meters, fraction): [(2000.0, 0.1), (2000.0, 0.2), (2000.0, 0.25), (2000.0, 0.5), (2000.0, 1.0)]. Each attacked setting uses seeds 4201–4203 to vary selection, bearing and report distances, not model training. Main prevalence comparison holds mean displacement at 2000 meters. Distance standard deviation: 200 meters. Additional means, if requested, are compared at 25%. All are stress settings; observed severe source jumps were much rarer than these injected percentages.

Distances are independent normal draws per vessel/timestamp identity, clipped to [0, half Earth's circumference]. Sigma zero reproduces fixed distances. Duplicate identities share a draw; sampling order, future reports and percentage do not change it. The clipping is audited separately. The seed/identity namespace for distance is separate from report selection and vessel bearing.

Window: Whole supplied approach feed

MAE weights approaches equally, averaging scenario realizations within each approach. MdAE and P95 pool absolute errors over decision/seed pairs. Changes compare identical supported original/attacked decisions. Coverage retains every scheduled decision in the denominator. Units are minutes to the analytical crossing, not docking.

| Mean displacement | Selected fraction | Model | MAE | MdAE | Δ MAE | Δ MdAE | P95 | Coverage |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Original | 0% | A | 7.3169 | 4.9187 | +0.0000 | +0.0000 | 23.4782 | 100.00% |
| Original | 0% | B | 6.2989 | 2.5565 | +0.0000 | +0.0000 | 21.8750 | 100.00% |
| Original | 0% | C | 5.8598 | 2.8070 | +0.0000 | +0.0000 | 22.1674 | 100.00% |
| 2 km | 10% | A | 9.5470 | 6.3410 | +2.2302 | +1.4222 | 30.5880 | 100.00% |
| 2 km | 10% | B | 6.6302 | 2.8501 | +0.3313 | +0.2936 | 22.0235 | 100.00% |
| 2 km | 10% | C | 6.2620 | 3.1004 | +0.4023 | +0.2934 | 22.8653 | 100.00% |
| 2 km | 20% | A | 11.4099 | 7.7622 | +4.0931 | +2.8435 | 35.5356 | 100.00% |
| 2 km | 20% | B | 6.9633 | 3.1425 | +0.6644 | +0.5860 | 22.5572 | 100.00% |
| 2 km | 20% | C | 6.6086 | 3.3740 | +0.7489 | +0.5670 | 23.8360 | 100.00% |
| 2 km | 25% | A | 12.1267 | 8.4744 | +4.8098 | +3.5556 | 36.2569 | 100.00% |
| 2 km | 25% | B | 7.1362 | 3.3263 | +0.8373 | +0.7698 | 22.8385 | 100.00% |
| 2 km | 25% | C | 6.7937 | 3.5122 | +0.9340 | +0.7052 | 23.9489 | 100.00% |
| 2 km | 50% | A | 14.4693 | 11.1933 | +7.1524 | +6.2745 | 40.4713 | 100.00% |
| 2 km | 50% | B | 7.8096 | 4.1878 | +1.5107 | +1.6313 | 23.6639 | 100.00% |
| 2 km | 50% | C | 7.4692 | 4.2765 | +1.6094 | +1.4695 | 25.3531 | 100.00% |
| 2 km | 100% | A | 9.9896 | 7.6236 | +2.6727 | +2.7049 | 28.7516 | 100.00% |
| 2 km | 100% | B | 9.5170 | 5.2627 | +3.2181 | +2.7062 | 25.6258 | 100.00% |
| 2 km | 100% | C | 7.5842 | 4.7756 | +1.7245 | +1.9686 | 24.3069 | 100.00% |

CSV outputs include all predictions, per-seed summaries, displacement/selection audit and 1,000-draw paired vessel-cluster MAE-change intervals. CSVs remain locally ignored. Hashes of source data, frozen models and existing inference/training code are checked before and after. Audience-only injection truth is never fed to the predictors.

Model histories and analytical crossing labels are never rebuilt from corrupted coordinates, even if an injected fix appears across the gate. The original 112-approach cohort did not include the severe jump endpoints identified by the location audit. This experiment tests a simulated failure pattern on that cohort; it does not attribute its original ETA errors to those source anomalies. April has been inspected previously and is not a pristine holdout.

Completed 15 attacked configurations and 115,296 model forecasts including originals. Minimum forecast coverage: 100.00%. Protected hashes unchanged: True.

Reproduce from Data_Science: `python experiments/position_jump_attack/run.py`.
Optional timed run: `--window-start-minutes 20 --window-duration-minutes 15 --output artifacts/position_jump_window`. Other settings are listed by `--help`.

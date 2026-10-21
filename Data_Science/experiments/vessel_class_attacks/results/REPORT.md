# Missing vessel class: historical binary-class models

MissingVesselClassAttack sets vessel_type to NaN. All reports, motion, clocks and crossing labels are retained. The original cohort is selected before injection; no class filter is reapplied.

## What reaches the models

These historical frozen models use only is_tanker: cargo and unknown both produce 0. The corrected models/results are in ../results_vessel_class_v2/REPORT.md. This table preserves the old model version; it does not describe the corrected input contract.

Evaluation uses the same 112 April approaches / 110 vessels / 2,402 decision times. Each model is compared with its own original-feed baseline within this version. Partial selections use seeds 4201/4202/4203, which vary the fault selection, not model training. 100% selection is seed independent and scored once. MAE gives approaches equal weight; MdAE pools prediction/seed absolute errors. Both are minutes to the analytical crossing, not verified docking. Lower is better.

## MissingVesselClassAttack: selection per report

| Selected fraction | A MAE / MdAE | B MAE / MdAE | Coverage |
|---|---:|---:|---:|
| 0% | 7.3163 / 4.9189 | 6.2989 / 2.5565 | 100.00% |
| 10% | 7.3261 / 4.9174 | 6.3027 / 2.5507 | 100.00% |
| 25% | 7.3278 / 4.9174 | 6.3181 / 2.5461 | 100.00% |
| 50% | 7.3656 / 4.9099 | 6.3446 / 2.5553 | 100.00% |
| 100% | 7.4269 / 4.9330 | 6.4071 / 2.5853 | 100.00% |

## MissingVesselClassAttack: selection per vessel

| Selected fraction | A MAE / MdAE | B MAE / MdAE | Coverage |
|---|---:|---:|---:|
| 0% | 7.3163 / 4.9189 | 6.2989 / 2.5565 | 100.00% |
| 10% | 7.3196 / 4.9189 | 6.3132 / 2.5614 | 100.00% |
| 25% | 7.3417 / 4.9137 | 6.3288 / 2.5767 | 100.00% |
| 50% | 7.3716 / 4.9360 | 6.3553 / 2.5785 | 100.00% |
| 100% | 7.4269 / 4.9330 | 6.4071 / 2.5853 | 100.00% |

## Class balance

107 original cargo approaches and 5 original tanker approaches. Class-specific scores use original classes in evaluator audit only, never as recovered model inputs.

Tanker-only A MAE: 8.7782 to 11.2540 minutes under full removal.

Tanker-only B MAE: 6.9313 to 9.3559 minutes under full removal.

## Interpretation and limits

The encoding fix does not guarantee lower errors or a monotonic response to increasing faults. An unknown state absent from nominal training can still follow a learned cargo-like decision path. Report MdAE and tail errors alongside MAE. No class reconstruction, metadata cache, forced ETA shift, outcome-based targeting or row removal is introduced.

These are simulated faults on real histories. Original missingness does not establish valid-but-wrong source classifications. Fractions are selection probabilities, not exact quotas. April was already inspected, so these are follow-up results rather than a pristine holdout. All forecasts remain available.

Source CSVs, historical frozen models and frontend/service files are preserved. New models live under artifacts/march_2024_vessel_class_v2; local CSVs remain ignored. The original service config still points to the original run. For the corrected A/B/C runtime use Optimized_Model/config_vessel_class_v2.json after preparing/training that version. Historical calibration and timelines are not evidence for the new models.

Reproduce from Data_Science: `python experiments/vessel_class_attacks/run.py --legacy`.

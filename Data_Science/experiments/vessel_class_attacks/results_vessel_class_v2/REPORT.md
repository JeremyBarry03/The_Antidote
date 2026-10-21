# Missing vessel class: explicit unknown class, retrained A/B

MissingVesselClassAttack sets vessel_type to NaN. All reports, motion, clocks and crossing labels are retained. The original cohort is selected before injection; no class filter is reapplied.

## What reaches the models

Both models receive is_cargo/is_tanker/vessel_class_unknown: cargo=(1,0,0), tanker=(0,1,0), unknown=(0,0,1). Unknown stays distinct after median imputation. A/B were retrained on nominal March with the original splits, seed 42 and previously selected hyperparameters. The source cohort excludes missing classes, so there are zero unknown-class training examples. This fixes representation without adding synthetic missing-class training or claiming learned robustness to an unseen class state.

Evaluation uses the same 112 April approaches / 110 vessels / 2,402 decision times. Each model is compared with its own original-feed baseline within this version. Partial selections use seeds 4201/4202/4203, which vary the fault selection, not model training. 100% selection is seed independent and scored once. MAE gives approaches equal weight; MdAE pools prediction/seed absolute errors. Both are minutes to the analytical crossing, not verified docking. Lower is better.

## MissingVesselClassAttack: selection per report

| Selected fraction | A MAE / MdAE | B MAE / MdAE | Coverage |
|---|---:|---:|---:|
| 0% | 7.3169 / 4.9187 | 6.2989 / 2.5565 | 100.00% |
| 10% | 8.6808 / 5.3878 | 6.3027 / 2.5507 | 100.00% |
| 25% | 10.6415 / 5.9088 | 6.3181 / 2.5461 | 100.00% |
| 50% | 13.7616 / 6.7070 | 6.3446 / 2.5553 | 100.00% |
| 100% | 21.3752 / 8.5061 | 6.4071 / 2.5853 | 100.00% |

## MissingVesselClassAttack: selection per vessel

| Selected fraction | A MAE / MdAE | B MAE / MdAE | Coverage |
|---|---:|---:|---:|
| 0% | 7.3169 / 4.9187 | 6.2989 / 2.5565 | 100.00% |
| 10% | 9.2080 / 5.4524 | 6.3132 / 2.5614 | 100.00% |
| 25% | 10.9568 / 6.0275 | 6.3288 / 2.5767 | 100.00% |
| 50% | 13.6497 / 6.8729 | 6.3553 / 2.5785 | 100.00% |
| 100% | 21.3752 / 8.5061 | 6.4071 / 2.5853 | 100.00% |

## Class balance

107 original cargo approaches and 5 original tanker approaches. Class-specific scores use original classes in evaluator audit only, never as recovered model inputs.

Tanker-only A MAE: 8.7891 to 14.0595 minutes under full removal.

Tanker-only B MAE: 6.9313 to 9.3559 minutes under full removal.

## Interpretation and limits

The encoding fix does not guarantee lower errors or a monotonic response to increasing faults. An unknown state absent from nominal training can still follow a learned cargo-like decision path. Report MdAE and tail errors alongside MAE. No class reconstruction, metadata cache, forced ETA shift, outcome-based targeting or row removal is introduced.

These are simulated faults on real histories. Original missingness does not establish valid-but-wrong source classifications. Fractions are selection probabilities, not exact quotas. April was already inspected, so these are follow-up results rather than a pristine holdout. All forecasts remain available.

Source CSVs, historical frozen models and frontend/service files are preserved. New models live under artifacts/march_2024_vessel_class_v2; local CSVs remain ignored. The original service config still points to the original run. For the corrected A/B/C runtime use Optimized_Model/config_vessel_class_v2.json after preparing/training that version. Historical calibration and timelines are not evidence for the new models.

Reproduce from Data_Science: `python experiments/vessel_class_attacks/run.py --train`.

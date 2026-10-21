# Model A versus Model B: three input attacks

A is degree-two polynomial ridge regression; B is XGBoost. Both are existing frozen models, not new training runs.

112 April approaches / 110 vessels / 2402 original decision times. Identical inputs, seeds, labels and clocks for each pair.

## Whole approach: current missing-value handling

| Attack | Setting | A MAE | A MdAE | B MAE | B MdAE |
|---|---|---:|---:|---:|---:|
| Original | No added fault | 7.3163 | 4.9189 | 6.2989 | 2.5565 |
| ReportingGapAttack | 5 minute gap | 7.6152 | 5.2692 | 6.3292 | 2.5618 |
| ReportingGapAttack | 10 minute gap | 8.5624 | 5.6944 | 6.4833 | 2.6016 |
| ReportingGapAttack | 15 minute gap | 8.6388 | 5.7982 | 6.6322 | 2.6894 |
| ReportingGapAttack | 30 minute gap | 9.0437 | 6.2175 | 7.2426 | 3.0606 |
| MissingSpeedAttack | 10% removed | 8.0953 | 5.3370 | 6.5942 | 2.9007 |
| MissingSpeedAttack | 25% removed | 9.1225 | 5.8265 | 7.0035 | 3.4333 |
| MissingSpeedAttack | 50% removed | 10.9606 | 6.7687 | 7.7041 | 4.3039 |
| MissingSpeedAttack | 100% removed | 9.5217 | 6.8987 | 10.0991 | 6.9798 |
| MissingCourseAttack | 10% removed | 7.6028 | 4.8287 | 6.4228 | 2.7028 |
| MissingCourseAttack | 25% removed | 7.9441 | 4.7052 | 6.5936 | 2.8260 |
| MissingCourseAttack | 50% removed | 8.4130 | 4.4538 | 6.5784 | 2.9943 |
| MissingCourseAttack | 100% removed | 9.8690 | 4.0892 | 7.0947 | 3.4032 |

## Only prediction times inside reporting gaps

| Attack | Setting | A MAE | A MdAE | B MAE | B MdAE |
|---|---|---:|---:|---:|---:|
| ReportingGapAttack | 5 minute gap | 9.0616 | 6.4587 | 8.7483 | 4.7024 |
| ReportingGapAttack | 10 minute gap | 9.0616 | 6.4587 | 8.7483 | 4.7024 |
| ReportingGapAttack | 15 minute gap | 9.0616 | 6.4587 | 8.7483 | 4.7024 |
| ReportingGapAttack | 30 minute gap | 9.0983 | 6.4748 | 9.0548 | 4.7212 |

## Separate zero-fill controls

| Attack | Setting | A MAE | A MdAE | B MAE | B MdAE |
|---|---|---:|---:|---:|---:|
| MissingSpeedAttack | 10% removed | 16.5985 | 9.5350 | 20.5621 | 3.8565 |
| MissingSpeedAttack | 25% removed | 31.8701 | 21.6401 | 39.6748 | 6.7809 |
| MissingSpeedAttack | 50% removed | 59.1133 | 53.5593 | 69.6158 | 27.0536 |
| MissingSpeedAttack | 100% removed | 113.4536 | 108.1884 | 103.0180 | 88.2450 |
| MissingCourseAttack | 10% removed | 15.2139 | 5.9158 | 25.9127 | 3.3802 |
| MissingCourseAttack | 25% removed | 26.2196 | 7.5319 | 52.3885 | 5.0337 |
| MissingCourseAttack | 50% removed | 44.7673 | 15.3029 | 98.5127 | 16.4010 |
| MissingCourseAttack | 100% removed | 83.6867 | 68.9636 | 189.9958 | 64.8344 |

## Interpretation and limits

Errors are minutes relative to analytical crossing, not verified docking. Lower is better. MAE gives each approach equal weight; MdAE pools absolute errors across decision/seed/placement pairs. Coverage and paired MAE-change intervals are in summary.csv.
Reporting gaps reuse the exact saved attacked features at 5/10/15/30 minutes and three fixed onsets after the first forecast. Partial speed/course removal uses the same 4201/4202/4203 selection seeds as B; these vary missing reports, not trained models. Total removal is seed independent and scored once.
Current missingness stays NaN before each model applies its own trained imputer. Zero-fill controls substitute zero before feature construction, including naturally missing fields, and use matched original-feed control references. They are not current endpoint behavior or newly proposed mitigations.
Only affected feature columns are recomputed for field masking. Formula agreement with the standard builder is checked at first/middle/last decisions per approach/configuration/handling; every reproduced B forecast is compared with its previous saved result. Outage features are reused after reproducing all saved B outage forecasts.
The models are not clipped or recalibrated to improve results. Outages are bounded windows; missing-field removal is distributed over approaches. These different exposure designs do not establish real-world relative failure frequencies. April data have previously been inspected; this is a follow-up study.
No source data, model artifacts, attack semantics, frontend code or previous result files are changed.

Reproduce from Data_Science: `python experiments/model_a_attack_comparison/run.py`.
# ReportingGapAttack: Model B evaluation

Original-feed MAE: **6.2989 minutes**. 2402 decisions, 112 approaches, 110 vessels.

## Whole approach

| gap_minutes | original_mae_minutes | attacked_mae_minutes | mae_change_minutes | change_ci_low | change_ci_high | scheduled | output_coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 6.2989 | 6.3292 | 0.0303 | 0.0071 | 0.0539 | 7206 | 1.0000 |
| 10 | 6.2989 | 6.4833 | 0.1844 | 0.0711 | 0.3772 | 7206 | 1.0000 |
| 15 | 6.2989 | 6.6322 | 0.3333 | 0.1192 | 0.7144 | 7206 | 1.0000 |
| 30 | 6.2989 | 7.2426 | 0.9437 | 0.4310 | 1.8695 | 7206 | 1.0000 |

## During the outage: same-clock matched comparisons

| gap_minutes | original_mae_minutes | attacked_mae_minutes | mae_change_minutes | change_ci_low | change_ci_high | scheduled | output_coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 8.1337 | 8.7483 | 0.6146 | 0.1646 | 1.1046 | 335 | 1.0000 |
| 10 | 7.1092 | 8.7483 | 1.6391 | 0.6344 | 3.3034 | 670 | 1.0000 |
| 15 | 6.6163 | 8.7483 | 2.1320 | 0.8905 | 4.3282 | 1005 | 1.0000 |
| 30 | 5.6900 | 9.0548 | 3.3648 | 1.6148 | 6.4923 | 1988 | 1.0000 |

## First ten minutes after the outage

| gap_minutes | original_mae_minutes | attacked_mae_minutes | mae_change_minutes | change_ci_low | change_ci_high | scheduled | output_coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 5.8577 | 5.8885 | 0.0308 | -0.0795 | 0.1370 | 670 | 1.0000 |
| 10 | 5.4914 | 5.6231 | 0.1318 | -0.0652 | 0.3245 | 670 | 1.0000 |
| 15 | 5.0039 | 5.0481 | 0.0442 | -0.1340 | 0.2311 | 664 | 1.0000 |
| 30 | 3.4994 | 3.5146 | 0.0152 | -0.0834 | 0.1176 | 582 | 1.0000 |

## Interpretation

Positive MAE change means the gap worsened ETA accuracy. Whole-approach averages include unaffected decisions. During/recovery rows compare the same clocks and cases with the original feed; their reference MAE differs from the full-cohort reference because their case/time mixes differ.
Three fixed onset offsets after the first scheduled forecast are used per approach. Short approaches can finish before later outages; they stay in whole-approach denominators. During-gap results are conditional on the approach still having a scheduled forecast in the configured window.
A 95% change interval is a vessel-cluster bootstrap interval; repeated clocks and placements are not independent cases. There is no retraining, new mitigation, or selection of onset based on errors. Reports missing inside the window do not return afterward. Initial history is retained because outages start after the first forecast.
This is a controlled missing-update simulation on real tracks, not evidence of naturally occurring poisoning or actual transmission outages. April has been inspected previously, so this is a follow-up evaluation. Arrival means analytical gate crossing, not docking.

Reproduce from Data_Science: `python experiments/reporting_gap_attack/run.py`. Settings, hashes, validation, predictions and dropped-report logs are saved in this directory.
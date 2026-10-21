# MissingSpeedAttack and MdAE across active attacks

Model B is unchanged. 112 April approaches / 110 vessels / 2402 original decision times.

## Current Model B handling

| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |
|---|---|---|---|---:|---:|---:|
| Original | No added fault | whole_approach | preserve_missing | 6.2989 | 2.5565 | 2.5565 |
| ReportingGapAttack | 5 minute gap | whole_approach | existing_B | 6.3292 | 2.5618 | 2.5565 |
| ReportingGapAttack | 10 minute gap | whole_approach | existing_B | 6.4833 | 2.6016 | 2.5565 |
| ReportingGapAttack | 15 minute gap | whole_approach | existing_B | 6.6322 | 2.6894 | 2.5565 |
| ReportingGapAttack | 30 minute gap | whole_approach | existing_B | 7.2426 | 3.0606 | 2.5565 |
| MissingSpeedAttack | 10% speed missing | whole_approach | preserve_missing | 6.5942 | 2.9007 | 2.5565 |
| MissingSpeedAttack | 25% speed missing | whole_approach | preserve_missing | 7.0035 | 3.4333 | 2.5565 |
| MissingSpeedAttack | 50% speed missing | whole_approach | preserve_missing | 7.7041 | 4.3039 | 2.5565 |
| MissingSpeedAttack | 100% speed missing | whole_approach | preserve_missing | 10.0991 | 6.9798 | 2.5565 |

## Reporting gap: only prediction times inside the outage

| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |
|---|---|---|---|---:|---:|---:|
| ReportingGapAttack | 5 minute gap | during_gap | existing_B | 8.7483 | 4.7024 | 4.2702 |
| ReportingGapAttack | 10 minute gap | during_gap | existing_B | 8.7483 | 4.7024 | 3.6098 |
| ReportingGapAttack | 15 minute gap | during_gap | existing_B | 8.7483 | 4.7024 | 3.4480 |
| ReportingGapAttack | 30 minute gap | during_gap | existing_B | 9.0548 | 4.7212 | 2.6921 |

## Separate zero-fill control

| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |
|---|---|---|---|---:|---:|---:|
| MissingSpeedAttack | 10% speed missing | whole_approach | zero_fill_control | 20.5621 | 3.8565 | 2.5565 |
| MissingSpeedAttack | 25% speed missing | whole_approach | zero_fill_control | 39.6748 | 6.7809 | 2.5565 |
| MissingSpeedAttack | 50% speed missing | whole_approach | zero_fill_control | 69.6158 | 27.0536 | 2.5565 |
| MissingSpeedAttack | 100% speed missing | whole_approach | zero_fill_control | 103.0180 | 88.2450 | 2.5565 |

## Definitions and limits

MdAE means median absolute prediction error across decision/seed pairs, not the median of approach MAEs. MAE gives each approach equal weight; the two statistics have different weighting. Intervals in CSVs apply to mean absolute-error changes, not MdAE.
MissingSpeedAttack preserves positions, course, timing and report counts, and replaces selected observed speeds with NaN. The current path uses the existing trained imputer and history_missing feature. This is not a new learned mitigation.
The zero-fill control changes all missing sog to zero before building features, including naturally missing values. Its matched original-feed reference uses that same control. It is separate from the actual endpoint, which never zero-fills.
Missing-speed removal is spread over an approach; reporting gaps are bounded outages at three fixed offsets. These are different exposure designs. During-gap comparisons have their own matched original MdAE and must not use the whole-cohort median as their reference.
Rates of 10-100% are stress assumptions, much higher than observed missing speeds. Partial selection uses three fixed seeds; full selection is seed invariant and runs once. Original missing values are retained and never counted as injected defects.
April results were previously inspected, so these are follow-up analyses. Error is relative to analytical gate crossing, not docking. No retraining or frontend changes. DuplicateReportAttack remains removed and is excluded from the active-attacks table.

Run from Data_Science: `python experiments/missing_speed_attack/run.py`.
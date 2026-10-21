# MissingCourseAttack: Model B results

112 April approaches, 110 vessels, 2402 decision times. No retraining, no altered crossing truth.

## Current missing-value handling

| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |
|---|---|---|---|---:|---:|---:|
| MissingCourseAttack | 10% course missing | whole_approach | preserve_missing | 6.4228 | 2.7028 | 2.5565 |
| MissingCourseAttack | 25% course missing | whole_approach | preserve_missing | 6.5936 | 2.8260 | 2.5565 |
| MissingCourseAttack | 50% course missing | whole_approach | preserve_missing | 6.5784 | 2.9943 | 2.5565 |
| MissingCourseAttack | 100% course missing | whole_approach | preserve_missing | 7.0947 | 3.4032 | 2.5565 |

## Separate zero-fill control

| Attack | Setting | Scope | Handling | MAE (min) | MdAE (min) | Reference MdAE (min) |
|---|---|---|---|---:|---:|---:|
| MissingCourseAttack | 10% course missing | whole_approach | zero_fill_control | 25.9127 | 3.3802 | 2.5565 |
| MissingCourseAttack | 25% course missing | whole_approach | zero_fill_control | 52.3885 | 5.0337 | 2.5565 |
| MissingCourseAttack | 50% course missing | whole_approach | zero_fill_control | 98.5127 | 16.4010 | 2.5565 |
| MissingCourseAttack | 100% course missing | whole_approach | zero_fill_control | 189.9958 | 64.8344 | 2.5565 |

## All active attacks: whole approaches

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
| MissingCourseAttack | 10% course missing | whole_approach | preserve_missing | 6.4228 | 2.7028 | 2.5565 |
| MissingCourseAttack | 25% course missing | whole_approach | preserve_missing | 6.5936 | 2.8260 | 2.5565 |
| MissingCourseAttack | 50% course missing | whole_approach | preserve_missing | 6.5784 | 2.9943 | 2.5565 |
| MissingCourseAttack | 100% course missing | whole_approach | preserve_missing | 7.0947 | 3.4032 | 2.5565 |

## Limits

Course over ground is a circular angle. A valid zero means north; missing course is not a valid zero. The current path preserves NaN before the existing sine/cosine feature imputation. The control instead replaces missing cog with zero before encoding, including any naturally missing course. Each control has a matched original-feed reference using the same preprocessing.
Only course_sin and course_cos depend on cog in B. Other features and observation clocks are reused; exact equivalence with standard feature extraction is checked at first, middle, and last scheduled decisions in every approach/configuration/seed.
MAE averages approach MAEs equally. MdAE pools absolute errors across decision/seed pairs, so the weighting differs. Bootstrap intervals in CSVs apply to paired MAE changes. Partial removal uses three fixed seeds; total removal is seed invariant and runs once.
Rates of 10-100% are simulated stress assumptions, not measured field-failure rates. Removal is spread across an approach; reporting gaps are bounded windows. Do not rank differently exposed scenarios as equally severe real-world events.
April data have already been inspected; this is follow-up evidence. Arrival is an analytical crossing, not docking. No new learned mitigation, no frontend changes, and DuplicateReportAttack remains removed.

Reproduce from Data_Science: `python experiments/missing_course_attack/run.py`.
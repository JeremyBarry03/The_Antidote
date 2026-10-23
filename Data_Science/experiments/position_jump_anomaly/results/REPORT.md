# Position anomaly-only evaluation

Simulated disruption of copied AIS positions: mean displacement 2 km, SD 0.2 km. The detector compares adjacent positions against SOG/COG-implied movement. It fits no trusted track, changes no features and supplies no replacement observations. The previous correction estimator, adapter and all its results have been deleted.

## Fixed policy

The innovation is observed east/north displacement minus the average of endpoint SOG/COG velocities multiplied by elapsed seconds. Isotropic effective variance is 2*(25 m)^2 + 0.5*(0.5 m/s)^2*dt^2. Score is squared innovation divided by this variance. Threshold 1.948477151551384 is the vessel-balanced March 99.5th percentile over 25,202 eligible pairs from 242 approaches / 218 vessels; no April data or ETA labels select it. The scales are experimental normalizers, not measured sensor specifications. The empirical threshold is not a calibrated probability of bad GPS.

Pairs over 120 seconds apart or with unavailable velocity are unassessed. Invalid/missing coordinates and conflicting same-time positions warn separately. Warnings persist while flagged evidence is within the past five minutes, then expire. Silence is handled independently by the existing gap detector. No alert does not certify correct navigation or ETA.

## March development

All attacked settings use seeds 4201-4203; rows pool scenario/decision or pair counts. A separate 100% burst starts after 20 minutes and lasts 15 minutes. Affected pair means EITHER endpoint injected; unassessed pairs are excluded from pair rates. An affected decision window contains an affected pair ending within the last five minutes.

| Scenario | Selected | Assessed affected pairs flagged | Affected windows warned | Unmodified pair alert rate | All decision alert rate |
|---|---:|---:|---:|---:|---:|
| clean | 0% | n/a | n/a | 0.37% | 1.32% |
| warm_burst | 100% | 87.16% | 99.53% | 0.23% | 19.07% |
| whole_feed | 10% | 99.12% | 100.00% | 0.38% | 45.22% |
| whole_feed | 20% | 98.16% | 100.00% | 0.44% | 71.47% |
| whole_feed | 25% | 97.71% | 100.00% | 0.42% | 79.92% |
| whole_feed | 50% | 94.31% | 100.00% | 0.44% | 97.49% |
| whole_feed | 100% | 83.67% | 99.91% | n/a | 99.91% |

## April follow-up

All attacked settings use seeds 4201-4203; rows pool scenario/decision or pair counts. A separate 100% burst starts after 20 minutes and lasts 15 minutes. Affected pair means EITHER endpoint injected; unassessed pairs are excluded from pair rates. An affected decision window contains an affected pair ending within the last five minutes.

| Scenario | Selected | Assessed affected pairs flagged | Affected windows warned | Unmodified pair alert rate | All decision alert rate |
|---|---:|---:|---:|---:|---:|
| clean | 0% | n/a | n/a | 0.19% | 0.71% |
| warm_burst | 100% | 86.14% | 99.78% | 0.21% | 19.19% |
| whole_feed | 10% | 99.22% | 99.84% | 0.19% | 44.14% |
| whole_feed | 20% | 98.10% | 99.90% | 0.20% | 69.36% |
| whole_feed | 25% | 97.68% | 99.86% | 0.19% | 77.95% |
| whole_feed | 50% | 94.43% | 99.91% | 0.19% | 97.29% |
| whole_feed | 100% | 83.84% | 99.88% | n/a | 99.79% |

## ETA behavior and regression

All A/B/C inference frames and cards remain unchanged when enabling the detector, including point estimates, forecast availability and interval metadata. This is warning-only risk handling: it does not remove corruption or improve underlying ETA MAE/MdAE. A full ETA accuracy rerun was not performed for every corruption setting because warnings supply no model features. Complete-frame unit assertions and the saved-model regression check validate prediction invariance.

The prior severe failure was replayed on saved models: `249489000_20240421T162855:2024-04-21 14:40:00`, seed 4203, 50% corruption. Warning triggered: True. C's absolute error remains 5.732316 minutes with warnings both off and on. No attempted correction introduces the former 256-minute error. Source reports, original reference arrivals and all A/B/C cards match exactly.

## Detection limits

Unmodified-pair and clean-feed alerts are false-alarm proxies, not proof of accurate GPS: legitimate maneuvers, SOG/COG errors or motion approximations can cause disagreement. The warning does not determine which endpoint or sensor is wrong. No causal poisoning claim is made about source AIS records.

At 100%, the tested distances vary randomly around 2 km, creating detectable inconsistency. A coherent fixed offset present from the first report can remain invisible; a unit test explicitly demonstrates this limit. Unsupported intervals are not counted as successfully checked. April was previously inspected and is a follow-up cohort, not a pristine holdout.

All 336 approach/seed profiles in each attacked April setting had an affected-pair detection before the last scheduled forecast. Median first-pair detection delay was zero minutes: this measures observation-time detection among detected profiles, starting at the first affected eligible PAIR, not the first corrupted standalone report. It does not measure HTTP polling, frontend notification or scheduled-decision latency.

## Validation

5,624 independent public-detector first/last prefix checks matched the in-order adjacent-pair replay. Truth labels join only after observable decisions. 136 protected data/model/other-mitigation/attack/frontend files have unchanged hashes: True. Implementation unchanged during run: True. Elapsed: 63.9 seconds.

See tests.json for test commands and totals. CSV outputs remain local and ignored. Reproduce with `python experiments/position_jump_anomaly/run.py`.

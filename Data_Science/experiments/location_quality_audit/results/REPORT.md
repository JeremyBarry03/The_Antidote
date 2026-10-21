# Location quality audit

Read-only audit of original local March/April 2024 extracts. No attack was implemented or injected. Source hashes were checked before and after.

| Month | Scope | Rows | Missing lon | Missing lat | Unusable coordinates | Out-of-world bounds | (0,0) |
|---|---|---:|---:|---:|---:|---:|---:|
| march | all | 4,495,639 | 0 | 0 | 0 | 0 | 0 |
| march | cargo_tanker | 600,738 | 0 | 0 | 0 | 0 | 0 |
| april | all | 3,229,675 | 0 | 0 | 0 | 0 | 0 |
| april | cargo_tanker | 393,613 | 0 | 0 | 0 | 0 | 0 |

Motion checks use consecutive unambiguous vessel/time keys, 30–300 seconds apart, with spherical great-circle displacement. Cargo/tanker pairs require both endpoints to have type 70–89. An isolated jump-and-return requires both legs >60 knots but <=30 knots when the middle report is skipped. Exact repeated coordinates with endpoint SOG >=3 knots and disagreement between stable reported SOG and geometric speed are separate consistency flags.

| Month | Scope | Compared pairs | >60 kn | >100 kn | Same position while reporting motion | Stable SOG disagreement >10 kn | Jump-and-return |
|---|---|---:|---:|---:|---:|---:|---:|
| march | all | 4,200,118 | 68 | 50 | 49 | 77 | 20 |
| march | cargo_tanker | 574,473 | 27 | 25 | 0 | 0 | 13 |
| april | all | 3,024,908 | 27 | 20 | 33 | 86 | 10 |
| april | cargo_tanker | 381,118 | 8 | 8 | 0 | 1 | 4 |

Verified original-record example: MAERSK SEOUL, MMSI 563032900, 27 March 2024 (UTC):

| Time | Longitude | Latitude | SOG (knots) |
|---|---:|---:|---:|
| 10:44:04 | -76.35004 | 36.87790 | 0.0 |
| 10:45:32 | -75.88680 | 36.89419 | 10.1 |
| 10:47:05 | -76.35006 | 36.87792 | 0.0 |

The first leg spans approximately 41.24 km in 88 seconds (910.93 knots), followed by a return near the original location 93 seconds later. This sequence cannot represent the vessel's real motion. It establishes inconsistent position/time/identity records, but does not identify whether the cause was GPS, identity collision, timing or source processing.

Additional original examples: MMSI 563032700 on April 1 has a 42.51 km jump in 70 seconds followed by a return; MMSI 352003673 on April 12 has a 21.14 km jump in 67 seconds followed by a return. April extracts have no vessel-name column, and those MMSIs had no matching March name in this lookup.

Model-history cross-check: Checked all hash-validated cached model histories, including training and evaluation. Matches among the flagged high-speed leg endpoints: 0. Evaluation contains 112 approaches and 2402 decisions. Zero matches means these examples cannot explain the existing model benchmark errors.

These are consistency screens, not confirmed location errors. Either positions or SOG could be inaccurate; turns and changing speed also affect comparisons. No independent physical position truth is available.

The available files are geographic extracts, not untouched national AIS messages. The April acquisition explicitly filters ST_X/ST_Y to longitude [-76.6,-75.8] and latitude [36.7,37.2], which excludes null/unlocatable positions. All zero counts are conditional on the local extract and cannot establish source-wide prevalence.

There is no dedicated MissingLocationAttack in the active attacks package. Existing replay scenarios already simulate incorrect positions: quality_0.5nm_25pct shifts 25% of reports by 0.5 nautical miles (926 m); reserved_drift grows a position offset over time. These are simulated, not defects observed in the source.

Model preprocessing currently rejects missing/invalid positions before building approaches. A future missing-location attack would need explicit handling of reports with unusable coordinates; zero-filling would invent a location. No runtime, frontend, model, attack or source data changes were made.

CSV review candidates and summary outputs are locally ignored. Reproduce from Data_Science: `python experiments/location_quality_audit/run.py`.

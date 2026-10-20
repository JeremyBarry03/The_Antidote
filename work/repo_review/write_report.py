from pathlib import Path
import json
base=Path(r'C:\Users\jerem\Downloads\the_antidote\2026_WM_Hackathon\work\repo_review')
out=Path(r'C:\Users\jerem\Documents\Codex\2026-10-19\c-users-jerem-downloads-aisvesseltracks2013-zip\outputs')
sha='dda0d078c6365929f128627cf289907f700bcb48'
url=f'https://github.com/OllyC1/Maritime_eta_prediction/blob/{sha}'
report='''# Deep review: Maritime_eta_prediction and implications for The Antidote

Reviewed 20 October 2026. Immutable upstream revision: `COMMIT`.

## Recommendation

Use this repository as a source of feature and UI ideas, not as a validated ETA benchmark or a ready-to-use model. Preserve our A/B models and train-only preprocessing, causal approach snapshots, chronological splits and observed gate-crossing outcomes. Adapt useful strategies as declared development variants and test the final countermeasure on a new protected period. The reviewed source contains a definite answer-leakage path in its basic model and does not fully reproduce the enhanced model's training features. Its impressive reported accuracy does not validate our task or establish a target to beat.

No Antidote training source, saved model, label or prediction was changed during this review. Downloaded model files were not deserialized. The 771,151,204-byte Git LFS CSV was not downloaded; this review does not claim a full numerical reproduction of upstream results. Stored notebook outputs are the author's recorded results, not independently verified measurements.

## Inspection and verification

Read every executable notebook cell, the dashboard's prediction/feature/uncertainty and callback paths, README, Summary, requirements, license and Git LFS pointer. The repository contains one notebook, a single dashboard script, two model artifacts and a CSV LFS reference. No test suite, CI workflow, pinned environment lock or separate reusable preparation package is tracked at this revision.

Executed only selected, reviewed pure feature functions in isolation on synthetic examples. Checks are recorded in `maritime_repo_source_checks.json`. Compared source behavior with our current feature builder, calendar split logic, model constructor and saved nominal results. Did not install or run the upstream dashboard, retrain its models or obtain its full original data.

## 1. What problem does it actually train on?

The basic preparation groups the entire available data by MMSI, sets journey duration to each vessel's last timestamp minus first timestamp, and summarizes those same complete records into features. Stored outputs show one day's observations on 31 March 2022. A daily observation span is not a verified voyage, port arrival or remaining travel time. A vessel observed for most of a day can have a roughly 24-hour target despite being moored, making multiple trips, or having a journey extending beyond the file.

By contrast, ours predicts time to a specified directional analytical gate from a prefix of an enrolled approach. These are different outcomes, cohorts, units of evaluation and horizons. The upstream recorded 0.290-hour MAE equals 17.4 minutes, but it cannot be compared directly with our roughly 6.65-minute approach-weighted MAE. The percentage and R-squared claims are also not interchangeable with operational reliability or probability of correctness.

Source: [notebook cells 10–11](URL/AIS%20analysis.ipynb). README claims: [README](URL/README.md).

## 2. Critical: the basic model exposes its target

Cell 10 calculates average speed from bounding-box distance divided by journey duration. Cell 11 supplies that average speed and distance as predictors for the same duration. Therefore:

`duration = distance / derived_average_speed`

The prediction problem includes the answer algebraically. A synthetic three-observation example passed through the actual preparation function produced a 2.0-hour target, reconstructed from its input features with exactly zero error. This does not depend on the quality of XGBoost.

Do not confuse this derived quantity with reported SOG or velocity measured from an already observed history window; those can be causal. Future full-journey duration cannot enter their calculation. A random holdout does not remove this feature leakage.

The enhanced model's exact X/y construction is missing, so this review cannot assert that its 38-feature artifact has precisely the same leakage. It can establish the basic-model issue and the inability to verify the enhanced feature lineage from the committed notebook.

## 3. Enhanced training cannot be reproduced end-to-end from the committed cells

Cell 16 computes a dataframe of whole-vessel aggregates. Cell 22 calls its trainer with global variables X and y, then saves an enhanced artifact. No executable cell assigns those global variables or implements the transformation from the aggregate dataframe to the advertised 38-feature training matrix. An AST check found no top-level assignments to X/y. A clean notebook run reaches an undefined-variable problem if it reaches this call without external interactive state.

Stored output reports 14,091 samples and 38 inputs. That output may reflect omitted interactive work; it is not enough to identify how targets and features were made. The saved models cannot substitute for missing provenance. Request a clean-run training script, exact feature formulas, split IDs and training manifest before using its reported enhanced accuracy as evidence.

## 4. Whole-trajectory features need causal replacements

Total record count, final geographic extents, whole-journey speed quantiles, mean hour and route coverage are unavailable early in a journey. Computing them from the entire recorded vessel history before making an early ETA prediction leaks future behavior even when the target is not directly used.

Safe adaptations are trailing-window speed medians, interquartile ranges, acceleration, circular direction stability and elapsed history coverage, using only reports received by the decision time. Use timestamped windows, not an assumed fixed number of reports. In delayed experiments, compute them after withholding reports rather than attaching clean features to corrupted examples.

## 5. Geometry and units require care

The basic 'distance' is haversine distance between independent minimum-latitude/minimum-longitude and maximum-latitude/maximum-longitude coordinates. This is a geographic extent diagonal. Those corners need not be visited positions; the value is neither traveled route length nor remaining navigable distance to a destination.

The dashboard mixes distance labeled kilometers with speed labeled knots in several distance/speed calculations. A physical hours estimate requires dividing kilometers by knots multiplied by 1.852, or converting distance into nautical miles first. Hand-adjusted factors are not a substitute for dimensional consistency.

For us, use local projected position offsets, a fixed gate reference and, if useful, training-derived or independently specified navigable route geometry. Never use actual remaining future path length. Position-derived speed disagreement must use elapsed seconds and consistent units. Heading/course averages should be circular: ordinary averaging of 359 and 1 degrees gives 180 degrees, while the circular direction is approximately north.

Dashboard sources: [feature preparation](URL/dashboard.py#L84-L125), [baseline calculation](URL/dashboard.py#L348-L376).

## 6. Validation is not the claimed temporal deployment test

Both basic and enhanced trainers use a random 80/20 split. The optional enhanced search applies TimeSeriesSplit after random splitting, with no demonstrated calendar sort; ordering folds over shuffled rows does not restore time order. Whole-data aggregation is by MMSI, not by clearly defined voyage episodes. This does not itself prove same-vessel row leakage across those aggregated splits, but it does not evaluate future operations chronologically.

RobustScaler is fitted before the optional cross-validation folds, so fold preprocessing is not fully isolated. Scaling is generally unnecessary for tree splits and does not itself reject corrupt observations. The default executed enhanced call disables hyperparameter tuning. The full optional search has 6,561 combinations and 19,683 cross-validation fits before refit, with all-core parallelism inside and outside the estimator. It is excessive for our deadline and can oversubscribe a laptop.

Our existing temporal approach groups and bounded search should remain. The current March test has already been examined, so any changes motivated by those results must be treated as development and evaluated finally on new days.

## 7. Anomaly detection is described but not demonstrated

IsolationForest is imported but not instantiated/fitted in the committed executable code. It is not evidence that an isolation-forest filter improved ETA. Warning thresholds and physical plausibility are useful ideas, but they must be measured against retained valid maneuvers, false alarms, review burden and downstream ETA performance.

For our model C, start with observable freshness, reporting gaps and motion disagreement. If an anomaly model is later used, fit it on training data only, disclose contamination assumptions, and initially use its score as an observable input or review signal. Do not automatically delete all unusual turns or stops.

## 8. The dashboard's uncertainty is not calibrated future-error coverage

The enhanced path repeatedly adds Gaussian noise with standard deviation 0.05 to the scaled input and takes prediction percentiles. This measures local sensitivity to an assumed perturbation, not a bootstrap of independent fitted models, a confidence interval for an expected quantity, or a validated future-outcome prediction interval.

The basic path resamples feature-column indices with replacement. A speed may replace a distance column, changing feature meanings. That is not a valid observation bootstrap. Separately, displayed confidence begins from a hand-written 95% base and adjusts it with heuristic penalties; no held-out frequency establishes that percentage. The 'historical distribution' chart draws a normal curve around the current forecast rather than showing observed historical residuals. References derived from the interval's own lower bound are not independent historical expectations.

Borrow the visual structure, but use empirically calibrated residual bands and measured coverage on separate approaches. Display width, coverage, age and support count. Do not turn 1 minus MAPE into confidence, or portray global feature importance as a causal explanation for one prediction.

Sources: [prediction and input perturbations](URL/dashboard.py#L127-L249), [distribution chart](URL/dashboard.py#L858-L926), [confidence score](URL/dashboard.py#L929-L965).

## 9. Training-serving feature mismatch

The enhanced dashboard feature function synthesizes 39 possible values from a few form inputs. Several are constants: position standard deviations 0.01, speed efficiency 0.9, distance efficiency 5.0, mean hour 12, hour variability 4 and weekend ratio 0.29. Quantiles are reconstructed from mean/std assumptions instead of observed history. Course is substituted for heading; unknown model input names fall back to zero.

We verified the function's 39 outputs and constants in isolation. Thirty-nine generated keys versus 38 advertised inputs is not by itself proof of a shape bug: the code selects the saved feature-name list. The concern is unverified definitions and fabricated values, not merely their count.

The fallback dashboard path passes a dict into code that expects dataframe rename/indexing behavior, giving another reproducibility concern. It also adds predicted duration to the computer's current clock without an observation-history replay contract. Do not use the supplied joblib artifacts as drop-in models for our feature schema or gate. Rebuild feature extraction once and reuse it for training, validation and serving, as our FeatureBuilder/EtaPredictor already do.

Source: [dashboard enhanced features](URL/dashboard.py#L1089-L1163).

## 10. No actual weather-fusion benefit is established

The dashboard has constants named weather, port operations and safety margin; there is no historical weather lookup or measured environmental fusion in the inspected prediction path. Do not describe those constants as weather-aware learning. Our AIS-only model should remain explicit about missing wind/current observations. A future environmental experiment needs location/time matching and information actually available at the decision time.

## 11. Strategies worth adapting

| Strategy | Adaptation for our existing architecture | Priority / test |
|---|---|---|
| Robust speed summaries | Trailing median, IQR, stop fraction and endpoint speed change | High; shared causal feature builder, compare with/without on development approaches |
| Direction stability | Circular dispersion and changes between recent velocity estimates | High; preserve valid maneuvers and missing COG |
| Physical consistency | Position-derived versus reported speed, gap duration and conflicting-bin spread | High; observable quality features and guard ablations |
| Vessel context | Length, width, draft and missingness after reviewing validity and availability | Medium; supply to ordinary-B control too; no mass inference from cargo code |
| Multiple timescales | Recent 2/5/10-minute motion summaries | Medium; tune without later outcomes; quantify sparse-history support |
| XGBoost regularization | Small declared search over child weight/subsample/regularization | Medium; evaluate on development, not current test; no giant grid |
| Uncertainty UI | ETA, evidence timestamp, warning reason and verification action | High; calibrate actual residual bands, report false alarms and coverage |
| Feature diagnostics | Training feature importance plus development permutation checks grouped by approach | Medium; correlational evidence, not proof of mechanism |
| Package artifacts | Model, preprocessing, feature schema, config and versions together | Already largely present; retain shared inference contract |

This repository does not implement our central degradation-aware training experiment. Borrowing its features alone is not the hackathon countermeasure. C still needs age/quality features, earlier nominal/stale/quality/combined training views, paired frozen A/B comparisons, source-volume controls and a held-out failure condition.

## 12. Connection to our current outliers

Our XGBoost model's largest inspected error used a report only about nine seconds old. An age-only detector would not explain that case. An additional read-only audit found training observation-to-arrival targets reaching 552.8 minutes, with >6-hour examples concentrated in two approaches from one identifier; test targets reach about 148 minutes. These are actual training-label distributions, not evidence that those long approaches are mislabeled.

Squared-error learning can be sensitive to long-target cases even with equal total approach weights. Check the long training trajectories for valid waiting versus inappropriate episode enrollment, test causal movement features and regularization on development data, and retain legitimate waits. A declared robust-loss experiment is possible but should be separated from the primary matched-objective comparison in the execution plan. Do not delete long waits simply to improve MAE, and do not claim a new strategy fixes the 348-minute error without a controlled test.

## 13. Code quality and maintainability

The repository is a research prototype. The notebook repeats fit/save calls and includes installation cells, missing interactive state and warning suppression. The dashboard combines model loading, feature generation, validation, presentation and callbacks in one large module, with broad exception handling and duplicated feature formulas. Dependencies use lower bounds rather than a reproduced pinned environment. No automated leakage, timing, schema or calibration checks are tracked.

Our CODE_GUIDELINES.md favors typed, focused, reusable components. Adapt individual ideas into the existing feature/config/training/prediction modules. Add tests that future records cannot alter past features, angular wraparound works, missing fields are not zero, feature generation is identical in serving, and injected truth labels never enter model inputs. Leave A/B artifacts frozen while creating separate C/ablation artifacts.

## 14. License and attribution

The committed MIT license permits reuse/modification/distribution, subject to retaining the copyright and permission notice in copies or substantial portions. If copying code, retain the exact license and copyright in a third-party notices file, identify files and the reviewed revision, and disclose the adaptation in the competition materials. Do not present copied code or borrowed methodology as our invention. The software license is not proof of independent rights for an externally sourced AIS dataset; the README refers generally to data-sharing agreements without the detailed provenance needed for our manifest. We already have our NOAA source and should keep using it.

Source: [MIT license](URL/LICENSE). This review checks the repository's own text; it is not an independent audit of every upstream right.

## 15. Proposed adoption sequence

1. Keep the current A/B artifacts as the documented nominal reference. Map-review the inferred crossing labels and long training approaches.
2. Create a causal feature extension in the one shared FeatureBuilder. Compute speed quantiles, circular course stability and position/SOG disagreement from received history only; validate with small deterministic tests.
3. Train a nominal-data B-with-features control. Separately train C on matched degraded training views with observable age/quality features. Preserve equal total approach weights across augmented replicas.
4. Compare fixed B, B+guard, nominal enhanced-feature B and C to separate filtering, richer information, augmentation and learned freshness effects.
5. Calibrate review intervals on a separate period. Score ETA MAE, tail error, useful-output rate, accepted coverage, ordinary-condition cost and human effort on new approaches.
6. Build the website around saved paired results, with real replay timestamps and clearly labeled simulated failures. Show a valid maneuver flagged in error and a failure the method misses.

This is an adoption proposal, not implemented model improvement. Nothing in the reviewed repository establishes that any listed feature will improve Hampton Roads ETA; the controlled experiments must decide.
'''
report=report.replace('COMMIT',sha).replace('URL',url)
(out/'maritime_eta_repository_deep_review.md').write_text(report,encoding='utf8')
(out/'maritime_repo_source_checks.json').write_text((base/'source_checks.json').read_text(),encoding='utf8')
print('Saved review:',len(report.split()),'words')

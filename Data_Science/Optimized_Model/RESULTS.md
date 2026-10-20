# Model C implementation and measured results

Completed October 20, 2026. UI work is deferred at the user's request.

Model C and all three learned controls are implemented and trained. A/B prediction
behavior and nominal preprocessing remain compatible. Upstream baseline files were
rewritten during this run at 15:07; their source of change is unknown. The original B
artifact was recovered byte-for-byte. A was checked against every distinct stored
primary/volume input and retained as a numerically equivalent run-local snapshot.
`baseline_integrity.json` records exact hashes, comparison counts and tolerances.
Future commands use checked local snapshots so upstream retraining cannot change
the comparison. The already-scored forecasts and trained C/control files are unchanged.

## Primary April comparison

MAE below is the mean of each approach's mean absolute arrival-time error, in minutes,
before warnings or deferral. All methods have identical scheduled cases and output
coverage: 100% normally and 95.34% under the 15-minute delay. Unsupported initial
decisions remain in the denominators. Five paired seeds share original reference labels.

| Condition | A | B | B + guard | C |
| --- | --- | --- | --- | --- |
| Nominal | 7.32 | 6.30 | 6.30 | 5.86 |
| 15-minute delay | 8.99 | 10.88 | 10.89 | 7.66 |
| 0.5-nm offset, 25% affected | 9.35 | 6.58 | 6.58 | 5.96 |
| Delay plus offsets | 11.38 | 11.33 | 11.34 | 7.82 |
| Reserved drift | 8.86 | 7.71 | 7.71 | 6.90 |

Across the three degraded primary conditions, C's average MAE is
**25.5% lower than B**. Nominal MAE is
**7.0% lower** as a point estimate. C also improves
on B plus guard; the guard alone makes little difference in these primary conditions.
These are results on this selected, simulated-fault cohort, not production guarantees.

![Primary model comparison](../artifacts/optimized/march_gate_v1/model_comparison.png)

## Uncertainty and how often C wins

Negative differences favor C. Bootstrap intervals cluster repeated approaches by
vessel. The clearest evidence favors C on stale and combined inputs. Other intervals
include zero. Mean gains mainly reduce large errors; typical approach improvements
are smaller, and C loses slightly on many individual approaches.

| Condition | Mean C minus B | 95% interval | C wins | Median difference |
| --- | --- | --- | --- | --- |
| Nominal | -0.44 | [-1.72, 0.30] | 40.2% | 0.16 |
| 15-minute delay | -3.22 | [-5.79, -1.29] | 49.1% | 0.07 |
| 0.5-nm offset, 25% affected | -0.62 | [-1.93, 0.17] | 47.3% | 0.06 |
| Delay plus offsets | -3.51 | [-6.12, -1.47] | 43.8% | 0.13 |
| Reserved drift | -0.81 | [-2.19, 0.01] | 62.5% | -0.29 |

## What the controls show

All controls are separately fitted artifacts. They do not replace removed features
with zeros at evaluation. The motion-only augmented control performs worse than full
C, supporting a contribution from freshness/quality information in this experiment.
Nominal-only C extrapolates poorly to stale inputs, supporting the degraded-training
comparison. Its target remains decision-anchored, whereas frozen B is observation-anchored.

| Model | Nominal | Stale | Quality | Combined | Drift |
| --- | --- | --- | --- | --- | --- |
| B_rich_nominal | 6.43 | 11.13 | 6.76 | 11.81 | 7.90 |
| C_nominal | 6.41 | 19.04 | 6.83 | 19.11 | 7.78 |
| augmented_motion | 8.05 | 11.23 | 8.31 | 11.15 | 10.16 |
| C | 5.86 | 7.66 | 5.96 | 7.82 | 6.90 |

## Source-volume evidence

All 16 volume scenarios ran on the full 112-approach evaluation cohort with five
paired seeds. These distinguish prevalence at fixed volume, exact/nonidentical biased
repetition, total volume at fixed quality share and reference-only repetition.
Selected rows follow; the CSV contains every control and uncertainty estimate.

| Scenario | B | B + guard | C |
| --- | --- | --- | --- |
| fixed_volume_share_0.1 | 6.41 | 6.41 | 5.90 |
| fixed_volume_share_0.25 | 6.58 | 6.58 | 5.96 |
| fixed_volume_share_0.5 | 6.83 | 6.83 | 6.04 |
| nonidentical_biased_repetition_3 | 6.59 | 6.58 | 5.96 |
| nonidentical_biased_repetition_5 | 6.60 | 6.58 | 5.96 |
| nonidentical_all_volume_3 | 6.58 | 6.58 | 5.96 |
| nonidentical_all_volume_5 | 6.58 | 6.58 | 5.96 |
| reference_volume_5 | 6.30 | 6.30 | 5.86 |

Exact duplicate reports have common preprocessing across every method. The separate
fault-audit files retain pre-deduplication counts. Minute binning bounds contributions
to history summaries, but biased majorities within a bin can still move its median.
The measured volume effect is small here: B changes from about 6.58 to 6.60 minutes
under fivefold nonidentical biased repetition. Do not present duplication as a major
failure of the existing baseline. Increasing affected share from 10% to 50% increases
B's error from about 6.41 to 6.83 minutes, versus 5.90 to 6.04 for C. The strongest
countermeasure evidence remains the stale/combined comparison.

## Warning policy: a negative result

The predeclared five-minute empirical-envelope tolerance accepts **zero** C forecasts.
It therefore fails the warning-policy promotion goal. The measured envelopes are about
34-47 minutes wide on each side, with 50 supporting calibration approaches. High
interval coverage comes at an unusable review burden, not better ETA accuracy.
Keep the age-only rule as the simpler comparator and keep these failed calibration
results visible. Neither rule has a validated operational safety guarantee. No threshold
was relaxed after inspecting evaluation outcomes. Full curves and matched-coverage
comparisons are saved alongside raw errors.

## Data, checks and limits

- Training: March 1-19, 153 approaches; development: March 20-24, 36 approaches.
- Calibration: April 1-7, 50 approaches/48 vessels; evaluation: April 8-21,
  112 approaches/110 vessels. Eighteen evaluation vessels appeared in training.
- All 21 April days were obtained: 3,229,675 geographic-subset records before
  shared cargo/tanker filtering. Source checksums and daily counts are saved.
- 33 tests pass, covering future-data invariance, timestamp arithmetic, missing inputs,
  circular headings, augmented weights, guard limits, source-volume audits, legacy
  bundles, calibration separation, outcome-independent review and snapshot integrity.
- All 39 configured stress/volume scenarios additionally passed a small end-to-end
  smoke check. The full separate 23-scenario stress grid was not run; primary reserved
  drift and the complete 16-scenario volume suite were evaluated on the full cohort.
- A replay audit found stationary drift fallback is seed-dependent. It was rescored
  with all five seeds; nominal/delay-only views alone reuse seed-invariant features.
  Predictors and hyperparameters were unchanged during this correction.
- Long training episodes were retained. Visual review shows extended waiting and
  backtracking; inferred destination intent remains uncertain. They were not discarded
  to improve errors. A rare evaluation approach still produces C errors above two hours.
- Arrival remains the original analytical gate crossing, **not verified docking or VIG
  arrival**. The cohort is conditional on observed qualifying arrivals. Reference
  brackets, unresolved-episode audits and geographic assumptions must accompany claims.
- Nominal instant delivery and fault rates are simulation assumptions. This does not
  establish actual NOAA poisoning, measured receiver latency or broad domain generalization.

## Saved files and reproduction

Run commands and module ownership are in [README.md](README.md). The trained bundle
is `../artifacts/optimized/march_gate_v1/models/C.joblib`; the three learned controls
are beside it. Full primary and volume predictions, condition summaries, paired
uncertainty, breakdowns, failures, review curves and provenance live under that run.
`final_validation.json` reconciles scheduled counts and checks supported timestamps.
The model meets the stated point-estimate accuracy goals; the warning policy does not.

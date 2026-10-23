# First combination screen: findings

## What was evaluated

The current frozen **vessel-class-v2** models and dashboard mitigation policy were replayed across **112 April approaches / 110 vessels**. We selected four existing decision clocks per approach without looking at errors: first, first at/after 20 minutes from approach start, middle and last. That gives **448 clocks per setting**, rather than all 2,402 original clocks.

The **39 settings** cover original records, eight single attacks, all 28 pairs, and two all-eight stacks. There are **17,472 matched replay cases / 69,888 forecasts**, using one simulated-fault seed (4201). Models, thresholds and source records were frozen. No verified location anchors were supplied, matching the dashboard.

**C guard** below means the frozen C model with its original input guard and the additional dashboard strategies disabled. **Antidote** adds those strategies to that same C model. This comparison isolates their incremental effect. It is different from comparing Antidote with ordinary XGBoost B.

![Changes in mean absolute ETA error across single and paired attacks](combination_screen.png)

## Where the additional repairs help

MAE is mean absolute ETA error in minutes, averaging within each approach and then across approaches.

| Setting | C guard MAE | Antidote MAE | Reduction | Paired 95% interval for change, minutes |
|---|---:|---:|---:|---:|
| Missing speed | 7.81 | 7.34 | 6.1% | -0.87 to -0.09 |
| Missing course | 8.63 | 7.42 | 14.1% | -2.00 to -0.18 |
| Sensor noise | 9.10 | 7.90 | 13.1% | -2.24 to -0.42 |
| Reporting gap + missing course | 10.48 | 7.39 | 29.5% | -4.28 to -1.97 |
| Missing speed + missing course | 9.75 | 7.53 | 22.8% | -3.14 to -1.21 |
| Missing speed + speed drift | 9.07 | 7.65 | 15.7% | -1.85 to -1.03 |
| Speed drift alone | 8.66 | 8.54 | 1.4% | -0.27 to +0.01 |

- **16 of 28 pairs lower average absolute error; 12 are unchanged.** None has higher average MAE in this screen. Thirteen paired intervals exclude zero, but intervals are exploratory and unadjusted for multiple comparisons.
- Noise-only MSE falls from **332.20 to 204.86 min²**, and its pooled 95th percentile absolute error falls from **32.58 to 26.58 minutes**. These support the average noise result, while individual forecasts can still worsen.
- Speed-drift correction changes features at only **9.8%** of sampled clocks. Its small average gain and interval crossing zero do not establish reliable drift recovery.

## Where the present integration stops helping

- Position faults pause speed/course repairs that depend on those positions. Noise plus speed drift pauses their overlapping corrections. A zero change in the matrix often means **repair was paused**, rather than a successful recovery.
- Reporting-gap and position-jump strategies provide warnings. Location drift receives no coordinate correction in this dashboard configuration because it lacks independent verified fixes.
- With **all eight at moderate settings**, MAE is **14.27 → 14.26 minutes** (0.09% lower; paired interval -0.052 to +0.014 minutes). The only applied additional strategy is vessel-class recovery, used at 40.2% of clocks. Navigation repairs are paused.
- With **all eight at severe settings**, MAE is **15.63 → 15.63 minutes**, and no additional feature correction applies. At 100% class masking there is no received class to carry forward.
- Original-record MAE is **7.26 minutes**. The stacked errors remain substantially above that level. Warning status does not withhold a forecast or reduce its measured error.

## Two issues to prioritize

### 1. Review status is too common to interpret as attack detection

On original records, **400/448 clocks (89.3%)** request review. The speed-drift strategy alone requests review at **397/448 clocks (88.6%)**. Its motion-reference check rejects maneuvering tracks at **336/448 clocks (75%)**. This does not prove those original reports are malicious or that all warnings are false; they are unverified historical AIS. It does show a high operational review burden.

The frontend should eventually distinguish inability to support an optional reconstruction from a detected anomaly, while retaining genuinely unsupported forecasts and visible uncertainty. Validate any revised policy on development data before claiming lower review burden on a new evaluation period. Do not simply suppress warnings to improve this score.

### 2. Missing-course repair restores a model weakness in a large outlier

Missing-course MAE improves, but **MSE rises 173.80 → 195.56 min² (+12.5%)**. Missing course plus drift also raises MSE **211.49 → 240.08 min²**. Averages hide some very large misses.

For approach **538007166_20240411T125452**, at **2024-04-11 12:10 UTC**:

| Input setting | C guard error | Antidote error |
|---|---:|---:|
| Original records | +141.97 min | +141.97 min |
| Missing course | +42.03 min | +143.28 min |
| Missing course + sensor noise | +62.29 min | +167.02 min |

The missing-course repair makes the first attacked comparison **101.25 minutes worse**; adding noise produces the screen's largest increase, **104.72 minutes**. The underlying model already misses badly with original records. Reconstructing course largely brings back that weakness; this is not evidence that a nonsensical course was inserted. The repaired latest course is about **168.2°**, versus **177.9°** in the original report. Other derived course summaries also change.

As a diagnostic sensitivity check, excluding this one approach changes missing-course MSE to **171.27 → 131.51 min²**. **The official metrics retain the approach.** This sensitivity identifies a model failure to investigate; it is not grounds for excluding a difficult vessel or selecting a new threshold on April.

## Simulation and evidence limits

- Moderate pairs use 50% non-gap sliders and a fixed 15-minute outage beginning ten minutes into each approach. Severe stacking uses 100% sliders and a 30-minute gap. Speed drift is under-reporting only in this screen.
- Missing-field and position-jump selections share a deterministic report hash and seed. Equal-severity selections therefore overlap, subject to field eligibility. These results do **not** establish performance under independently sampled dropout masks.
- The fleet policy knows the selected simulated fault families when it decides which references may be trusted. It is not blind automatic classification of real faults.
- This is one seed, four sampled clocks per approach, selected severities and an April period already inspected during development. It is **exploratory**, not a new holdout and not validation of all 256 subsets, continuous slider values or coordinated spoofing.
- The target is the existing analytical harbor crossing, not independently verified docking. Original arrivals are retained for every comparison.

## Validation and files

- Model manifest compatibility was checked before inference. Source/model checksums, causal receipt times, original labels, unique case keys, and unchanged raw A/B inputs and original C quality signals were checked.
- **52 forecasts across 13 cases** match the scalar prediction path used by the dashboard within 0.00001 minutes. The chosen cases include each single attack, both stacks, and the largest positive and negative individual changes.
- [Full 39-setting table](REPORT.md), [numeric summary](summary.json), [protocol](protocol.json), [validation](validation.json), [scalar spot checks](spot_checks.json), [nominal warning reasons](nominal_warning_review.json).
- `run_snapshot.py` preserves the exact evaluated runner. The current runner subsequently received report-wording and pandas-warning fixes; the attack, mitigation and prediction implementations remain unchanged.
- Local per-forecast CSVs are ignored by Git. Reproduce from `Data_Science` with its pinned environment: `python experiments/fleet_combinations/run.py`. Use `--clocks all` for the complete original schedule and `--seed N` for another fault realization. Validate with `python experiments/fleet_combinations/validate.py <result-directory>`.

Next evidence work should cover all original clocks and more seeds for these candidate gains and failures, use development data to investigate course/model outliers and review policy, then confirm changes on a new untouched period.

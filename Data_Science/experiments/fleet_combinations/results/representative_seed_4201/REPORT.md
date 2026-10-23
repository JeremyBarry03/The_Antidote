# Combined attacks: current Antidote integration

## Scope

This is an exploratory screen of 112 April approaches / 110 vessels at 448 original decision clocks per scenario. It covers 39 declared settings with fault seed 4201.

The 28 pairs use 50% for each non-gap slider and a fixed 15-minute reporting gap. At 50%: speed drift is -0.05 knots/min capped at 1.5 knots, location drift is 10 m/min capped at 926 m, noise sigma is 1 knot / 5 degrees, and position jumps affect half the reports (2,000 m mean / 200 m SD). Missing fields use deterministic report selection at 50%. Equal-severity missing-field and position-jump attacks share the same selection hash and seed, so their selected reports overlap; these are not independent dropout masks. All-eight cases also include one severe setting (100%, 30-minute gap).

Representative clocks are the first, first at/after 20 minutes from approach start, middle and last existing scheduled decision. Duplicates are removed. Clock selection uses no forecast errors. These are not scores across all 2,402 clocks unless the protocol says all.

Antidote uses the current frozen vessel-class-v2 C plus the dashboard strategies. C guard is the identical frozen C and trained guard with additional strategies disabled. A and B see the same raw attacked reports. Verified fixes are absent, matching the current dashboard. Missing outputs remain in coverage denominators; accuracy uses available outputs. MAE and MSE first average within each approach and then across approaches; RMSE is the square root of that MSE. P95 and change shares pool decision clocks. Paired intervals resample vessels 1,000 times and retain repeated approaches within vessel. They are exploratory, unadjusted for 39 comparisons.

## Results

| Setting | C guard MAE | Antidote MAE | Change [95% paired interval] | B MAE | Repairs used | Review |
|---|---:|---:|---:|---:|---:|---:|
| nominal | 7.263 | 7.263 | +0.000 [+0.000, +0.000] | 7.914 | 0.0% | 89.3% |
| reporting gap | 7.236 | 7.236 | +0.000 [+0.000, +0.000] | 9.224 | 0.0% | 92.4% |
| missing speed | 7.809 | 7.336 | -0.473 [-0.872, -0.087] | 8.901 | 99.6% | 99.6% |
| missing course | 8.632 | 7.416 | -1.216 [-2.003, -0.175] | 8.367 | 99.6% | 99.6% |
| missing vessel class | 7.332 | 7.263 | -0.069 [-0.189, +0.003] | 8.019 | 46.9% | 89.3% |
| sensor drift | 8.659 | 8.537 | -0.122 [-0.266, +0.014] | 9.708 | 9.8% | 100.0% |
| location drift | 7.440 | 7.440 | +0.000 [+0.000, +0.000] | 8.388 | 0.0% | 100.0% |
| sensor deterioration | 9.096 | 7.901 | -1.195 [-2.244, -0.421] | 12.470 | 55.4% | 97.8% |
| position jump | 9.752 | 9.752 | +0.000 [+0.000, +0.000] | 10.388 | 0.0% | 100.0% |
| reporting gap + missing speed | 8.047 | 7.384 | -0.663 [-1.322, -0.085] | 9.835 | 99.1% | 99.6% |
| reporting gap + missing course | 10.478 | 7.385 | -3.093 [-4.285, -1.972] | 12.683 | 99.1% | 99.6% |
| reporting gap + missing vessel class | 7.272 | 7.236 | -0.036 [-0.099, +0.005] | 9.291 | 49.8% | 93.1% |
| reporting gap + sensor drift | 8.465 | 8.340 | -0.125 [-0.243, -0.039] | 10.617 | 4.5% | 99.8% |
| reporting gap + location drift | 7.518 | 7.518 | +0.000 [+0.000, +0.000] | 9.919 | 0.0% | 99.8% |
| reporting gap + sensor deterioration | 9.176 | 8.110 | -1.067 [-2.028, -0.300] | 13.792 | 37.7% | 99.1% |
| reporting gap + position jump | 10.470 | 10.470 | +0.000 [+0.000, +0.000] | 15.173 | 0.0% | 100.0% |
| missing speed + missing course | 9.750 | 7.526 | -2.224 [-3.140, -1.206] | 8.807 | 99.6% | 99.6% |
| missing speed + missing vessel class | 7.856 | 7.336 | -0.520 [-0.911, -0.129] | 8.996 | 99.6% | 99.6% |
| missing speed + sensor drift | 9.071 | 7.649 | -1.421 [-1.850, -1.034] | 10.001 | 99.6% | 100.0% |
| missing speed + location drift | 7.943 | 7.943 | +0.000 [+0.000, +0.000] | 9.282 | 0.0% | 99.8% |
| missing speed + sensor deterioration | 9.596 | 8.704 | -0.892 [-1.326, -0.463] | 13.373 | 99.8% | 99.8% |
| missing speed + position jump | 10.326 | 10.326 | +0.000 [+0.000, +0.000] | 11.271 | 0.0% | 100.0% |
| missing course + missing vessel class | 8.699 | 7.416 | -1.283 [-2.086, -0.227] | 8.433 | 99.6% | 99.6% |
| missing course + sensor drift | 10.087 | 8.743 | -1.344 [-2.195, -0.251] | 10.037 | 99.6% | 100.0% |
| missing course + location drift | 8.737 | 8.737 | +0.000 [+0.000, +0.000] | 8.770 | 0.0% | 99.8% |
| missing course + sensor deterioration | 9.541 | 7.955 | -1.586 [-2.459, -0.462] | 9.775 | 99.8% | 99.8% |
| missing course + position jump | 11.451 | 11.451 | +0.000 [+0.000, +0.000] | 10.252 | 0.0% | 100.0% |
| missing vessel class + sensor drift | 8.721 | 8.537 | -0.184 [-0.349, -0.030] | 9.790 | 51.8% | 100.0% |
| missing vessel class + location drift | 7.509 | 7.440 | -0.069 [-0.189, +0.003] | 8.510 | 46.9% | 100.0% |
| missing vessel class + sensor deterioration | 9.162 | 7.901 | -1.261 [-2.265, -0.454] | 12.500 | 75.4% | 97.8% |
| missing vessel class + position jump | 9.787 | 9.753 | -0.035 [-0.138, +0.033] | 10.502 | 37.5% | 100.0% |
| sensor drift + location drift | 8.844 | 8.844 | +0.000 [+0.000, +0.000] | 10.135 | 0.0% | 100.0% |
| sensor drift + sensor deterioration | 10.222 | 10.222 | +0.000 [+0.000, +0.000] | 14.249 | 0.0% | 100.0% |
| sensor drift + position jump | 10.647 | 10.647 | +0.000 [+0.000, +0.000] | 12.274 | 0.0% | 100.0% |
| location drift + sensor deterioration | 9.277 | 9.277 | +0.000 [+0.000, +0.000] | 12.834 | 0.0% | 100.0% |
| location drift + position jump | 9.702 | 9.702 | +0.000 [+0.000, +0.000] | 10.498 | 0.0% | 100.0% |
| sensor deterioration + position jump | 11.199 | 11.199 | +0.000 [+0.000, +0.000] | 15.009 | 0.0% | 100.0% |
| all eight 50 | 14.270 | 14.257 | -0.013 [-0.052, +0.014] | 16.253 | 40.2% | 100.0% |
| all eight 100 | 15.631 | 15.631 | +0.000 [+0.000, +0.000] | 16.846 | 0.0% | 100.0% |

Negative change means lower ETA absolute error. Review is an input-status warning, not a withheld forecast, and does not count as an accuracy improvement.

## Limits

- This April period has already been inspected. These are exploratory follow-up results, not a new holdout.
- Models, thresholds, source records, original crossing labels and UI behavior are frozen during the run.
- The fleet runner knows the selected simulation fault families to choose reference assumptions and pause incompatible repairs. It is not blind automatic fault isolation.
- Location faults and navigation faults together pause position-based corrections. Noise plus speed drift pauses their overlapping repairs. Class carry-forward can still operate. These no-op cases assess the current conservative integration, not recovery capability.
- Gap and jump strategies provide warnings; location drift has no coordinate correction without an independently verified reference.
- This is one seed and selected settings. It does not validate all 256 on/off subsets, all slider values, coordinated attacks or deployment safety.
- Scores measure the original analytical harbor crossing, not verified docking. No calibration envelope is transferred to repairs.

## Reproduce

`python experiments/fleet_combinations/run.py` from Data_Science. Use `--clocks all` for all original decision clocks, `--seed N` for another fault realization. Checkpoints are versioned by the protocol hash under ignored model artifacts. Raw predictions, repair audit and ranked failures are local CSVs; protocol/summary/validation are JSON.

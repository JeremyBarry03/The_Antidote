# Median-error diagnosis and comparison with prior C

The new main C has the highest median absolute error on the original March
reports. Relative to the old March-trained C on matched records, it improves
mean and tail error but worsens typical forecast error.

## Entire March: newly trained A/B/C

| Model | Approach-weighted MAE (min) | Forecast MdAE (min) | Forecast P95 AE (min) |
|---|---:|---:|---:|
| A | 7.019 | 3.459 | 36.725 |
| B | 6.643 | 3.164 | 37.361 |
| C | 7.032 | 3.616 | 38.643 |

All models cover the same 5,382 decisions across 243 approaches and 219 vessels.
MdAE is the median of absolute forecast errors; it is not the median of signed
errors or the median of approach means. Main C's MdAE is 27.1 seconds worse than
B's. A's MAE is only 0.76 seconds better than C's, so the ordinal ranking hides
how close those two mean-error estimates are.

## Matched prior/new comparison

The earlier "30-day" run used March 1–19 for fitting and March 20–24 for tuning.
The new run fits on January 1–June 29, 2023 and tunes on June 30–July 19, 2023.
Comparing both versions over all of March would include the prior C's fitting
and tuning records. Instead, this comparison selects whole approaches beginning
on or after March 25, with their crossing brackets ending before April 1.

Both versions predict exactly the same **1,107 decisions / 53 approaches**:

| Model | Approach-weighted MAE (min) | Forecast MdAE (min) | Forecast P95 AE (min) |
|---|---:|---:|---:|
| Prior C, March-trained | 5.424 | 2.633 | 17.180 |
| New C, 2023-trained | 4.787 | 3.271 | 13.994 |
| New A, 2023-trained | 4.801 | 3.098 | 14.765 |
| New B, 2023-trained | 4.435 | 2.645 | 13.683 |

New C improves approach-weighted MAE by 11.7% and forecast P95 by 18.5%, while
MdAE worsens by 24.2% (38.3 seconds). The legacy 32-feature C and prior
34-feature vessel-class C give identical forecasts on these selected cases.
This is a comparison of frozen artifacts on a previously inspected project
cohort, rather than a new confirmatory generalization experiment.

## What the existing internal control shows

The completed 2023 run already fitted a nominal-only C control. It retains C's
rich features, guard and decision-time target, while removing the simulated
disruption training mixture and selecting on nominal development cases.

| Internal diagnostic | Entire March MdAE (min) | March 25–31 MdAE (min) |
|---|---:|---:|
| Main C, four-condition mixture | 3.616 | 3.271 |
| Nominal-only C control | 3.097 | 2.622 |

The nominal-only control's entire-March approach-weighted MAE is 6.610 minutes,
versus 7.032 for main C. This is evidence that the current augmentation and
selection setup contributes to the normal-feed accuracy loss. It does not
identify a unique cause: fitting distribution, validation objective and early
stopping differ together. Its robustness under faults has not been evaluated
in this comparison, and it has not replaced the main C artifact.

Main C's fitting uses XGBoost squared-error loss; candidates are selected by
average condition-specific approach MAE, rather than MdAE. The old selection
was depth 6 / learning rate 0.1; the new selection is depth 2 / rate 0.1.
The changed year and seasonal coverage also change the fitting distribution.
These are observed differences and plausible contributors, not a proven
single explanation for every error.

## Reproduce and verify

From the `data_eval` worktree's `Data_Science` directory:

```powershell
& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -m experiments.prior_model_comparison.run --prior-root 'C:/Users/jerem/Downloads/the_antidote/2026_WM_Hackathon/Data_Science'
```

No model is retrained or modified, no faults are injected, and no April records
are evaluated. The runner verifies prior model and training-view hashes,
the shared March source hash, and all required numeric features and timing
against **4,255 saved nominal inputs for each prior C version**. It reproduces
all **16,146 saved new A/B/C predictions** before comparing the matched cases.
The models use identical schedules and original arrival labels.

[summary.csv](summary.csv) records all metrics. Detailed predictions and the
verification audit are under `artifacts/data_eval/prior_comparison/`, relative
to `Data_Science`. The runner was executed successfully on the actual artifacts.

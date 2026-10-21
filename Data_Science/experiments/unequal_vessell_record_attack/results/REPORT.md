# Unequal vessel record volume: A and B

This attack amplifies representation in training. It repeats the existing examples
of the top 20% of training vessels by row count, without changing any
feature, target, timestamp or evaluation row. It is a simulation, not evidence
that the original records were poisoned or that each replica is a new measurement.

## Data and protocol

Original March cargo/tanker source: 600,738 rows / 397 vessels;
median 669 records per vessel, maximum 36,373.
These raw counts include vessels/records without usable crossing labels.
The actual training cohort has 3,498 examples / 153 approaches /
137 vessels, with median 21 examples per vessel
and maximum 419.

The selected 28 vessels originally contribute 38.14% of
training rows. At 50x they contribute 96.86% of 68,864 rows.
Their share of supervised weight under current approach weighting stays
28.76%, rather than growing to match their row share.

Training settings are fixed at the original selected A/B hyperparameters and seed
42. Only training rows are replicated. The original March validation data govern
XGBoost early stopping. No April error is used to select vessels or settings.
Evaluation: 112 April approaches / 110 vessels /
2,402 unchanged prediction times. Both original current-pipeline
forecasts were reproduced before amplification. Deployed models are unchanged.

## Current pipeline: equal approach training weights

| Selected vessels' row multiplier | A MAE | A MdAE | B MAE | B MdAE |
|---|---:|---:|---:|---:|
| 1x | 7.3163 | 4.9189 | 6.2989 | 2.5565 |
| 3x | 7.3067 | 4.9534 | 6.3530 | 2.6331 |
| 5x | 7.3012 | 4.9701 | 6.2824 | 2.6328 |
| 10x | 7.2967 | 4.9673 | 6.3024 | 2.6383 |
| 50x | 7.2960 | 4.9365 | 6.4335 | 2.6096 |

## Counterfactual: ordinary row-weighted training

This is a separately retrained pipeline with uniform training-row weights, not the
deployed A/B configuration. Its 1x scores are its own matched references.

| Selected vessels' row multiplier | A MAE | A MdAE | B MAE | B MdAE |
|---|---:|---:|---:|---:|
| 1x | 9.4934 | 6.3406 | 6.5136 | 3.2081 |
| 3x | 10.9992 | 7.2331 | 7.0831 | 2.9681 |
| 5x | 11.7124 | 7.7082 | 7.2801 | 2.9701 |
| 10x | 12.6633 | 8.4496 | 7.5851 | 3.4167 |
| 50x | 14.6331 | 10.6275 | 8.5791 | 3.5165 |

## Interpretation and limits

At 50x, current-pipeline MAE changes by -0.0203 minutes for A and +0.1346 for B.
Current approach weighting therefore largely limits this stress in these runs.
With ordinary row weighting, MAE rises 5.1397 minutes for A and 2.0655 for B,
relative to each row-weighted 1x reference. The large increases describe the
counterfactual pipeline, not a major failure of the deployed weighting.

All errors are minutes to the analytical crossing, not verified docking. MAE
weights approaches equally; MdAE pools prediction errors. Coverage remains 100%.
`summary.csv` also contains equal-vessel MAE, P95, and paired vessel-cluster
bootstrap intervals for change against each weighting's own 1x reference.
`evaluation_slices.csv` separates seen/unseen and amplified/other vessel identities.

Equal approach weighting is an existing partial protection, not a newly deployed
fix. The full pipeline need not be invariant: training medians and A's scaler
are unweighted, vessels can have multiple approaches, and mean-one weight
normalization changes the total ridge loss weight as row count grows. XGBoost
early stopping also responds to changed training. The row-weighted comparison
changes both weighting and its resulting fit; it is not the current system.

Replicas are repeated exposure to existing prepared examples, not extra reports
passing raw-data deduplication. These results do not establish that natural
record-volume imbalance caused the baseline errors, nor that more imbalance
must worsen every metric. This is one fixed training seed and a deterministic
count-based vessel selection. April was already inspected in prior experiments;
results are follow-up evidence, not a new pristine holdout.

No source data, prepared examples, existing model artifacts, service endpoints,
or frontend files are changed. Reproduce from `Data_Science`:
`python experiments/unequal_vessell_record_attack/run.py`.

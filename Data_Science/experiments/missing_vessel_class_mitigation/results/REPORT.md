# MissingVesselClassMitigation on frozen optimized XGBoost

Simulated loss of vessel classification on original AIS histories. The model is unchanged; only the existing cargo/tanker/unknown flags may be recovered. Every AIS row remains available. Negative paired MAE change favors mitigation.

The fixed policy requires three distinct earlier reports agreeing on a supported broad class inside a 60-minute history window. No history, stale evidence, conflicts, and unsupported classes remain unknown. The cache is rebuilt solely from each scenario's received history. Hidden clean classifications never initialize it, and exact AIS subtypes are not invented.

Cold report masking tests missing individual labels. Cold whole-vessel masking removes all class evidence for deterministically selected MMSIs, so no recovery is possible for those vessels. The separate warm-dropout case retains legitimately received class labels during the first 10 minutes after the first observation and masks types thereafter. The onset is fixed independently of prediction errors and crossing outcomes. Warm evidence can expire under the same fixed policy; recording the pre-dropout history does not provide future class labels.

## March development

| Mode | Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Unknown decisions recovered |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| clean | 0% | 5.2772 | 5.2772 | 2.8610 | 2.8610 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| report | 10% | 5.2845 | 5.2772 | 2.8610 | 2.8610 | -0.0073 [-0.0188, +0.0000] | 100.00% | 100.00% |
| report | 25% | 5.3053 | 5.2772 | 2.8829 | 2.8610 | -0.0281 [-0.0738, +0.0000] | 100.00% | 100.00% |
| report | 50% | 5.3284 | 5.2772 | 2.8994 | 2.8610 | -0.0512 [-0.1373, +0.0000] | 100.00% | 99.91% |
| report | 100% | 5.3657 | 5.3657 | 2.9068 | 2.9068 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 10% | 5.2772 | 5.2772 | 2.8610 | 2.8610 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 25% | 5.2772 | 5.2772 | 2.8610 | 2.8610 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 50% | 5.3062 | 5.3062 | 2.8356 | 2.8356 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 100% | 5.3657 | 5.3657 | 2.9068 | 2.9068 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| warm_dropout | 100% | 5.3657 | 5.2818 | 2.9068 | 2.8610 | -0.0839 [-0.2101, +0.0000] | 100.00% | 53.52% |

## April follow-up evaluation

| Mode | Masked | C MAE | C+mit MAE | C MdAE | C+mit MdAE | Paired ΔMAE (95% interval) | Coverage | Unknown decisions recovered |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| clean | 0% | 5.8598 | 5.8598 | 2.8070 | 2.8070 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| report | 10% | 5.8645 | 5.8598 | 2.8089 | 2.8070 | -0.0047 [-0.0104, -0.0009] | 100.00% | 100.00% |
| report | 25% | 5.8755 | 5.8598 | 2.8089 | 2.8070 | -0.0157 [-0.0312, -0.0038] | 100.00% | 99.94% |
| report | 50% | 5.8917 | 5.8598 | 2.8249 | 2.8070 | -0.0319 [-0.0620, -0.0070] | 100.00% | 99.56% |
| report | 100% | 5.9296 | 5.9296 | 2.8378 | 2.8378 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 10% | 5.8685 | 5.8685 | 2.8051 | 2.8051 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 25% | 5.8785 | 5.8785 | 2.8160 | 2.8160 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 50% | 5.8994 | 5.8994 | 2.8249 | 2.8249 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| vessel | 100% | 5.9296 | 5.9296 | 2.8378 | 2.8378 | +0.0000 [+0.0000, +0.0000] | 100.00% | 0.00% |
| warm_dropout | 100% | 5.9277 | 5.8619 | 2.8378 | 2.8249 | -0.0658 [-0.1316, -0.0153] | 100.00% | 52.93% |

MAE gives approaches equal weight, averaging mask seeds within approach. MdAE and P95 pool absolute errors over decision/seed pairs. The paired interval resamples vessels 1,000 times. Both arms use identical decisions, original crossing labels and support. Partial cold masks use seeds 4201–4203; full masks are seed-invariant and run once. Warm dropout has no random seed. Mask fractions are selection probabilities, not guaranteed exact cohort percentages. Selection counts per seed are recorded in selection_audit.csv; a small cohort may select no vessel.

## April variation across approaches

report, 10%: 5 approaches improved, 0 worsened, 107 were unchanged. Worst approach mean change: +0.0000 minutes.
report, 25%: 5 approaches improved, 0 worsened, 107 were unchanged. Worst approach mean change: +0.0000 minutes.
report, 50%: 5 approaches improved, 0 worsened, 107 were unchanged. Worst approach mean change: +0.0000 minutes.
report, 100%: 0 approaches improved, 0 worsened, 112 were unchanged. Worst approach mean change: +0.0000 minutes.
vessel, 10%: 0 approaches improved, 0 worsened, 112 were unchanged. Worst approach mean change: +0.0000 minutes.
vessel, 25%: 0 approaches improved, 0 worsened, 112 were unchanged. Worst approach mean change: +0.0000 minutes.
vessel, 50%: 0 approaches improved, 0 worsened, 112 were unchanged. Worst approach mean change: +0.0000 minutes.
vessel, 100%: 0 approaches improved, 0 worsened, 112 were unchanged. Worst approach mean change: +0.0000 minutes.
warm_dropout, 100%: 5 approaches improved, 0 worsened, 107 were unchanged. Worst approach mean change: +0.0000 minutes.

This does not infer vessel class from speed, position, future labels or vessel identity alone. Consistent history can still be consistently wrong; the policy is not a verified vessel registry or a defense against MMSI spoofing. Missing type never defaults to cargo. Recovering classification may have little ETA effect if C makes little use of those features. Actual changes are reported without forcing degradation or improvement.

Stress rates are proposed experimental settings, not observed source failure rates. April has been inspected previously and is a follow-up cohort, not a pristine holdout. Arrival means the analytical crossing, not verified docking. The prepared cargo/tanker cohort was selected before masking, so this does not establish recovery of unknown-type vessels excluded upstream or an enrollment-coverage gain. No retraining or frontend edits. Source/model and earlier speed/course result hashes remain unchanged. P95, reasons and individual decisions are saved in locally ignored CSVs.

Reproduce from Data_Science: `python experiments/missing_vessel_class_mitigation/run.py`.

# Implementation plan: model C, degradation-aware arrival prediction

Prepared October 20, 2026. Status: **plan only**. No model C, detector, calibration
method, UI integration or performance improvement is implemented by this document.

## 1. Fixed objective and scope

Predict when an expected inbound cargo/tanker vessel crosses the same analytical
arrival reference used by A and B. Improve useful forecasts when received AIS
information becomes stale, inconsistent or dominated by repeated erroneous reports.

Keep the existing target geometry: longitude -76.30, latitude 36.95–37.05,
east-to-west crossing. This is a research reference, not verified docking, cargo
delivery or an official port entrance. Review the geometry and representative
approaches before treating inferred labels as ground truth.

The three presentation systems remain:

| System | Predictor | Training | Input handling |
|---|---|---|---|
| A | Quadratic ridge regression | Nominal earlier approaches | Existing baseline preprocessing |
| B | Standard XGBoost | Same nominal approaches | Existing baseline preprocessing |
| C | Separately fitted XGBoost | Nominal and controlled degraded views of the same earlier approaches | Observable quality features and a robust input guard |

Store A/B plus guard separately to measure whether any benefit comes from input
handling rather than the learned model. Evaluate numerical prediction quality
before deferral; evaluate calibrated warnings and human review separately.

## 2. What we adapt from the reviewed GitHub project

Reference: OllyC1/Maritime_eta_prediction, revision
`dda0d078c6365929f128627cf289907f700bcb48`.

| Strategy | Adaptation here | Priority |
|---|---|---|
| Speed distribution summaries | Received-history median, IQR, variability and low-speed fraction | Required |
| Navigation stability | Circular COG dispersion and recent turning, preserving valid maneuvers | Required |
| Journey complexity summaries | Past displacement, observation support and gaps; no whole-journey aggregates | Required |
| Physical consistency warnings | Compare timestamp-derived motion with reported SOG/course | Required |
| Vessel characteristics | Optional length/width/draft and explicit missingness; category already exists | Second stage |
| XGBoost regularization | Bounded search, chronological selection, same objective/budget controls | Required |
| Prediction intervals and warning presentation | Empirical residual calibration and measured review performance | Required, reimplemented |
| Feature-importance display | Supporting diagnostic, labeled global association rather than causal explanation | Optional |
| Packaging model and preprocessing | Extend our existing saved predictor contract | Required |

Do not copy target-derived average speed, complete-future trajectory features,
random temporal validation, arbitrary confidence percentages, feature-column
resampling, fabricated feature defaults or fixed weather multipliers. Isolation
Forest is imported upstream but not demonstrated as a fitted countermeasure;
an unsupervised detector is not required for our first implementation.

If source code is copied, retain the upstream MIT copyright and permission notice,
record revision/files in THIRD_PARTY_NOTICES.md, and disclose the adaptation.
Using its software license does not establish rights to an external dataset.

## 3. Protect labels, cohorts and evaluation periods first

Reuse `eta_baselines/approaches.py` and the original source to create one immutable
reference-event table. Never regenerate crossing labels from corrupted inputs.
All compared methods share approach IDs, decision clocks, crossing times and
reference uncertainty brackets. Keep turnaways, unresolved episodes, insufficient
history and unavailable outputs in audit counts.

Inspect the few long training approaches before designing exclusions. Training
targets reach approximately 553 minutes, whereas the inspected March test reaches
approximately 148 minutes. Valid waiting must remain. If review reveals a bug in
episode construction, version the dataset and regenerate every affected method;
do not silently correct labels only for C or remove cases because predictions fail.

Use the existing nominal March training partition (March 1–19) for model fitting
and March 20–24 for development. March 25–31 is now an **inspected exploratory
comparison**, not untouched final evidence. Do not use it to select C. Any design
inspired by its outliers must be disclosed as exploratory.

Obtain additional later observations before final calibration and evaluation:

| Proposed period, UTC | Purpose |
|---|---|
| April 1–7 | Calibration only after predictor and guard selection |
| April 8–21 | New protected evaluation, including reserved failure patterns |

These dates are a proposal: availability, source compatibility and qualified
approach counts have not been established in this project. Count episodes before
committing. Aim for at least 30 calibration and 60 evaluation approaches as
feasibility targets, not statistical guarantees; extend dates before looking at
comparative errors if support is inadequate. Report calendar/operational changes.
Purge episodes and feature/label windows crossing partitions. Keep repeat vessels
grouped in uncertainty estimates; report vessel overlap without using MMSI as a
predictor. If new data cannot be obtained, publish an explicitly exploratory result.

## 4. Use one replay contract for every system

Each delivered report needs:

- Stable source record ID, MMSI, observation time, delivered time and observed fields.
- Optional-field missingness and parsing flags.
- Injection provenance in a separate audit table unavailable to feature builders.

The source has observation time but no measured reception time. Nominal delivered
time equals observation time as an explicit replay assumption. This does not imply
the archive was actually received instantaneously in operation.

At decision time t, expose only records with delivered time <= t and observation
time <= t. History statistics must be recomputed from these delivered records
after each degradation. Do not attach clean rolling summaries to degraded rows.
Maintain the latest usable observation's true timestamp after filtering.

Keep a common five-minute prediction schedule after causal enrollment, including
when reports stop. Retain current slowdowns and stops. End scoring at the reference
crossing, but expose arrival information only to the outcome/scoring layer.

Separate failures:

1. **Stale:** delay delivery, freeze updates, or apply an event-time cutoff. Preserve
   retained values and original observation timestamps. Record actual report age.
2. **Quality:** introduce timestamp-preserving position offsets or biased bursts.
   Keep event times and nominal delivery schedules fixed.
3. **Combined:** apply both in a declared order to the same underlying records.

Source-volume controls must distinguish increasing biased share at fixed total
volume, repeating biased reports at fixed event support, and increasing overall
volume at fixed quality share. Include a reference-only volume control. Synthetic
source identity and true fault labels must never tell C which report is correct;
AIS transceiver class A/B is not provider identity.

## 5. Feature contract: richer history plus observable quality

Reuse the baseline ten-feature contract unchanged for frozen A/B. Build an
additional feature set using small, pure transformations on received history.
Start with a ten-minute window; add a second thirty-minute window only after the
first version is verified. Neither window reaches back beyond enrollment.

| Feature group | Initial fields | Why it may help |
|---|---|---|
| Motion | Existing position/SOG/COG features; position-derived east/north velocity | Distinguish reported from observed movement |
| Speed distribution | Median, Q25, Q75, IQR, variability, fraction <=0.5 knots | Describe waiting, noise and acceleration; low speed is not itself bad data |
| Turning | Circular dispersion, heading of derived displacement, recent angular change | Characterize maneuvers without the 359/1-degree discontinuity |
| Freshness | Latest received age, latest usable age, maximum gap, time since last supported velocity | Expose missing or obsolete evidence |
| Support | Occupied minute bins, history span, missing-field fractions | Distinguish rich evidence from sparse sampling |
| Consistency | Position/SOG velocity disagreement, fit residual, within-bin spread, flagged fraction | Expose contradictory observations |

Convert knots into meters/second before comparing reported and derived velocity.
Estimate position-derived velocity from a small trailing least-squares fit to
positions versus actual elapsed seconds. Start with median/binning robustness;
only add a separate robust estimator if development evidence justifies it. Long
gaps, insufficient history and very small displacement must produce explicit
unavailable flags rather than fabricated zero motion.

Fit imputation only on training examples. Missing values remain distinguishable
from measured zero. Do not calculate endpoint displacement using a future point.
Use circular direction calculations and mark direction unreliable near zero speed.
Temporal bins should have bounded influence so message multiplicity alone does not
control the summary. Physical consistency is evidence, not a definitive fault label.

Optional vessel dimensions require an additive reader change: the current loader
retains only seven fields. Preserve existing A/B parsing and conflict semantics;
new columns must not create new duplicate conflicts in the baseline cohort.
Take only values available in the replay, validate units, and avoid future fill.
Cargo classification is not mass. Do not estimate weight from it.

## 6. Robust input guard

The guard is a separate component, callable around frozen A/B and inside C.

1. Apply shared standard parsing/range/exact-duplicate rules equally to all methods.
2. Aggregate non-identical reports within one-minute event-time bins with bounded
   contributions, tracking count/spread. Handle circular course separately.
3. Screen implausible movement using elapsed time and consistency of neighboring
   **already available** reports. Select thresholds on development data.
4. Retain valid turning/stopping as behavior. Conflicting alternatives may require
   unsupported status instead of pretending the true point is identifiable.
5. Return usable history, latest usable time, quality summaries and reason codes.

The current loader discards conflicting MMSI/timestamp keys. Preserve that common
rule for frozen-baseline reproduction. Represent quality experiments as a replay
overlay after reference preparation; exact duplicates should be handled identically
for everyone. Use distinct observed event times or predeclared non-identical
repetition controls to test influence beyond trivial deduplication. Do not change
baseline cleaning only for a stress test without versioning that comparison.

Median-based aggregation can fail if plausible erroneous records dominate. Make
that an explicit stress case. Record excluded records and useful information lost.

## 7. Train model C and the controls that explain its contribution

For each original training decision, create nominal, stale-only, quality-only and
combined views. Use training-only seeds. Preserve original arrival labels. Keep
each approach's total training weight equal, divide it across its decision times,
then divide each decision's weight across condition groups and replicas.

Initial training delays: 0, 5, 15 and 30 minutes. Initial position offsets: 0.1,
0.5 and 2 nautical miles, affecting 10%, 25% or 50% of reports. These are declared
stress settings, not measured NOAA failure rates. Use a bounded sample of views
per decision instead of an uncontrolled Cartesian expansion.

C predicts `reference_crossing_time - decision_time`, in minutes. A/B continue
predicting observation-anchored duration and applying correct timestamp correction.
Every method is scored as an absolute arrival timestamp on the same decisions.

Use XGBoost CPU histogram training with squared-error objective initially. Match B's
six depth/rate combinations (depth 2/4/6; learning rate 0.03/0.1), maximum 500 rounds
and weighted development early stopping. Keep the primary objective matched.
Regularization/robust-loss searches are separately labeled extensions, with the
same search budget offered to the relevant baseline control.

Select C by the equally weighted average of approach-weighted MAE across the four
development conditions. Report nominal-data cost explicitly. Use separate train,
development, calibration and evaluation seeds. Never supply requested severity,
scenario identity, true offset or fault-channel labels as features.

Required explanatory comparisons:

- Frozen A and B, and each with guard: isolates input-handling gains.
- Nominal B with richer causal motion features: isolates better ordinary context.
- C's features trained nominal-only: isolates degraded-example training.
- Decision-time XGBoost on the same augmented views and guarded motion features,
  without added freshness/quality features: controls for target anchoring and augmentation.
- Full C: added observable quality features, degradation training and guard.
- An age-only review rule: practical comparator for a more complex warning policy.

Train these as separately named artifacts; removing a learned feature requires
retraining, not replacing it with zero at test time.

## 8. Reuse existing code and preserve A/B artifact compatibility

Follow `../../CODE_GUIDELINES.md`: typed contracts, focused responsibilities,
composition, centralized configuration, logging, explicit seeds and pinned
dependencies. Existing baselines must still run and load identically.

Reuse observation parsing, ApproachBuilder, configuration primitives, file hashes,
approach weighting, error scoring and feature/prediction concepts. Do not copy
the baseline preparation/training scripts into this folder.

The current code has two interfaces to extend deliberately:

1. `EtaPredictor.predict()` hard-codes FEATURE_COLUMNS and observation-anchored
   duration. Add an explicit serialized feature schema and target-clock contract,
   with compatibility handling for existing joblib artifacts. Confirm original
   A/B predictions are unchanged to numerical precision. Do not reinterpret an
   observation-duration model as a decision-duration model.
2. `BaselineTrainer` assumes two model names and always scores test data. Extract
   small shared candidate-fitting, reporting and serialization operations or
   compose them into C's trainer. Separate fit/select/calibrate/evaluate commands
   so training C cannot accidentally read protected evaluation outcomes.

Proposed ownership (create modules only as their work starts):

```text
Data_Science/
  eta_baselines/             # Reused data, feature, inference and evaluation contracts
  Optimized_Model/
    PLAN.md                 # This document
    configuration.py        # Typed degradation, feature, guard and review settings
    replay.py               # Delivered-time views and logged simulated faults
    quality.py              # Observable metrics, robust bins and consistency guard
    model.py                # C model construction and fit orchestration
    calibration.py          # Residual bands and frozen review operating point
    __main__.py             # Thin command entry point
    config.json             # Explicit run configuration once implemented
  tests/                    # Shared and optimized-model behavior tests
  artifacts/optimized/<run_id>/
```

Keep pure motion transforms in the shared feature domain, not duplicate formulas
inside UI callbacks. Reuse XGBoost and existing NumPy/pandas functionality before
adding dependencies. Store feature-schema version, target clock, source/label
hashes, split IDs, model settings, seeds and package versions in every artifact.

## 9. Calibration, evaluation and adoption rules

After model/guard selection, use the independent calibration period to estimate
residual intervals. Start with one maximum absolute residual per approach for a
conservative whole-approach error envelope. This is not an ordinary pointwise
interval. Use age bands only where at least thirty distinct calibration approaches
support them; otherwise use pooled calibration and expose limited support.
Approach dependence and distribution change prevent universal coverage claims.

Start the demo with a predeclared five-minute interval half-width tolerance for
provisional versus verify recommendations. This is an analytical setting, not
a port-approved operating requirement. Show error-versus-coverage curves and
sensitivity to alternative tolerances. Unsupported input should remain explicit.

Evaluate all primary systems on identical decision IDs under normal, stale,
quality and combined conditions, plus a reserved gradual along-route position
drift pattern not used in development. Repeat randomized faults with five paired
evaluation seeds. Do not regenerate outcomes for each corruption.

Report approach-weighted MAE/bias, tail errors, invalid/expired forecasts, accepted
coverage, useful-output rate, interval coverage/width, unnecessary review and
missed unreliable forecasts. Score raw ETA errors before deferral. Compare
accepted-error at matched coverage and retain unavailable outputs in denominators.
Break down by prediction horizon, vessel category, history support and seen/unseen
vessel. Use paired vessel-level resampling for uncertainty; show day/seed variation.

Development promotion targets, fixed before evaluation:

- At least 10% lower average degraded-condition MAE than frozen B, with no more
  than 5% worse nominal approach-weighted MAE. These are project goals, not promises.
- Demonstrable contribution versus B+guard; otherwise attribute gains to the guard.
- Review policy must improve useful-output tradeoffs over an age-only rule, or
  retain the simpler policy. Show the full curve rather than one selected point.
- Report valid rare-event losses, plausible-bias failures and full-outage limits.

Missing any target means iterate or report a negative finding, not alter the
protected cohort or discard bad cases. A legitimately strong baseline is allowed.

## 10. UI and inference handoff

Expose one typed inference result containing model/version, decision time, latest
received and usable timestamps, absolute ETA, remaining minutes, supported state,
interval and calibration support, reason codes and guard record counts. Keep
reference arrival and injection truth in an evaluation-only response.

Show A/B/C cards with a shared map, report-age clock, consistency evidence and
normal/stale/quality/combined controls. After reveal, display recorded crossing
and all errors, with a link to full-cohort metrics. Precomputed results are fine
when labeled; sliders must select computed scenarios rather than invent scores.

Add an inspect/verify action that records human effort. A verified update becomes
available at its actual entry time and triggers recomputation. If supplied by the
demo, identify it as simulated verification; keep human-assisted benefit separate
from unattended C. Never display fabricated confidence percentages or borrow the
upstream dashboard's noise perturbation bands as validated intervals.

## 11. Execution milestones and completion checks

| Order | Work | Evidence required to finish |
|---|---|---|
| 1 | Freeze reference and inspect approach quality | Versioned labels/cohort, reviewed tracks, preserved A/B artifacts |
| 2 | Implement shared replay and causal quality features | Future-data invariance, timestamp/missingness tests, injection logs |
| 3 | Implement guard and nominal feature control | Fixed thresholds; duplicate/volume checks; normal-maneuver examples |
| 4 | Train C and required ablations | Separate models, weights reconciliation, reproducible tuning logs |
| 5 | Obtain disjoint calibration/evaluation approaches | Counts, source manifests and chronological split audit |
| 6 | Calibrate and freeze review policy | Empirical band support, fixed operating point and config hashes |
| 7 | Run paired protected comparisons | Complete results, denominators, uncertainty and failure analysis |
| 8 | Connect UI to evidence and verification | Display/result reconciliation and recorded operator walkthrough |

Mandatory tests include: adding a future report changes nothing earlier; stale
views preserve values; quality-only preserves timing; truth labels never enter
features; course wraps correctly; duplicate volume cannot silently dominate the
guard; age is measured from the retained observation; all augmented weights sum
correctly; no approach crosses partitions; existing A/B artifact predictions remain
unchanged; nominal and degraded serving use the same extractor; calibrated policy
does not read future outcomes; accepted/deferred/unavailable counts reconcile.

Training C on cached nominal examples alone is insufficient because corruption
changes the history summaries. Preserve raw received-history access for replay.

## 12. Rubric evidence and sources

| Criterion | Evidence this plan produces |
|---|---|
| C1 | Actual report age, controlled delay, ETA effect and correct timestamp arithmetic |
| C2 | Explicit fault, contribution-volume controls, observable disagreement and downstream error |
| C3 | Paired four-condition results across replay time and ordered stress progression |
| C4 | C versus B/B+guard, unseen drift, normal cost, ablations and failures |
| E1–E3 | Fixed decision/reference, runnable models, protected evaluation and honest uncertainty |
| E4–E5 | Visible review/correction, measured human effort, provenance and accountable use limits |
| E6–E7 | Evidence-based iterate/stop decision, reproducible artifacts and working demonstration |

Verified implementation references:

- Existing shared code: `../eta_baselines/`, baseline A `../Simple_baseline/model.py`,
  baseline B `../XGBoost_Model/model.py`, current run `../artifacts/march_2024/`.
- [Upstream source at reviewed revision](https://github.com/OllyC1/Maritime_eta_prediction/tree/dda0d078c6365929f128627cf289907f700bcb48).
- [Notebook](https://github.com/OllyC1/Maritime_eta_prediction/blob/dda0d078c6365929f128627cf289907f700bcb48/AIS%20analysis.ipynb).
- [Dashboard](https://github.com/OllyC1/Maritime_eta_prediction/blob/dda0d078c6365929f128627cf289907f700bcb48/dashboard.py).
- [MIT license](https://github.com/OllyC1/Maritime_eta_prediction/blob/dda0d078c6365929f128627cf289907f700bcb48/LICENSE).

The full repository review and isolated source-check results are saved separately
in this chat's outputs. The parent caseathon execution plan remains context; this
document explicitly updates its calendar to the March dataset and its now-inspected
test evidence. It does not claim that any proposed feature, guard or model has
already improved Hampton Roads ETA.

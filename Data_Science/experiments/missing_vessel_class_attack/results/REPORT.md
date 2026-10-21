# MissingVesselClassAttack: A/B accuracy and coverage

> Historical row-filter experiment. These coverage-loss results are superseded
> for the active attack, which now retains all reports. Current field-only
> removal/swap results: [REPORT.md](../../vessel_class_attacks/results/REPORT.md).

This simulated attack removes only `vessel_type`. It keeps MMSI, motion, timing
and original crossing references unchanged. The existing cargo/tanker filter then
excludes unknown-class records. Empty history yields no forecast, not a zero error.

## Plan and protocol

1. Reuse BaseAttack and shared deterministic missing-field masking.
2. Test intermittent missing class per report and persistent missing class per vessel.
3. Apply the existing type-70-through-89 filter after masking, without guessing classes.
4. Reuse frozen A/B models and all 2,402 original prediction times from
   112 April approaches / 110 vessels.
5. Report coverage and conditional accuracy; compare to the exact same surviving
   original predictions. Keep fully excluded cases in the coverage denominator.
6. Verify causal features, unchanged labels/data/models, full-removal behavior and API parity.

## Actual source observations

March has 24,762 missing-class rows out of
4,495,639; April has 22,072
out of 3,229,675. These counts cover all records, not only cargo/tankers.
MMSIs with both a missing-class row and a classified cargo/tanker row in the same
month number 0 in March and
0 in April. Identity overlap
does not establish class or a crossing target for those unknown rows.

## Intermittent missing class: selection per report

| Class removed | Coverage | A MAE / MdAE | B MAE / MdAE | Matched original A / B MAE |
|---|---:|---:|---:|---:|
| Original | 100.00% | 7.3163 / 4.9189 | 6.2989 / 2.5565 | 7.3163 / 6.2989 |
| 10% | 100.00% | 7.6373 / 5.4309 | 6.3085 / 2.5873 | 7.3163 / 6.2989 |
| 25% | 100.00% | 8.2531 / 6.0773 | 6.3476 / 2.5809 | 7.3163 / 6.2989 |
| 50% | 99.99% | 9.9998 / 7.5922 | 6.5869 / 2.6555 | 7.3172 / 6.2969 |
| 100% | 0.00% | unavailable / unavailable | unavailable / unavailable | unavailable / unavailable |

## Persistent missing class: selection per vessel

| Class removed | Coverage | A MAE / MdAE | B MAE / MdAE | Matched original A / B MAE |
|---|---:|---:|---:|---:|
| Original | 100.00% | 7.3163 / 4.9189 | 6.2989 / 2.5565 | 7.3163 / 6.2989 |
| 10% | 87.11% | 7.3163 / 4.8860 | 6.2989 / 2.5258 | 7.3163 / 6.2989 |
| 25% | 72.48% | 7.3430 / 4.9099 | 6.3397 / 2.5834 | 7.3430 / 6.3397 |
| 50% | 47.95% | 7.4633 / 4.9309 | 6.5819 / 2.6487 | 7.4633 / 6.5819 |
| 100% | 0.00% | unavailable / unavailable | unavailable / unavailable | unavailable / unavailable |

Whole-vessel masking excludes selected vessels. The surviving vessels have exactly
the original predictions: their conditional MAE can change solely because the
cohort mix changes. The matched-original columns prevent calling this an accuracy
improvement or degradation. Actual per-seed coverage varies around each requested
vessel selection rate; rates are not exact quotas or measured real-world frequencies.

## Interpretation and limits

At 50% intermittent removal, A's MAE rises to 9.9998 minutes and B's to 6.5869;
paired changes are +2.6826 and +0.2901 minutes. Persistent 50% vessel selection
leaves 47.95% coverage for both. A is more sensitive to intermittent loss in these
runs, while whole-vessel exclusion is a shared pipeline limitation.

Intermittent missingness discards otherwise useful motion records, so an ETA may
use older evidence. Persistent missingness principally loses coverage. Both models
share the same ingestion gate, and neither can predict without eligible history.
At 100% removal both have zero coverage and undefined MAE/MdAE. These exclusions
are pipeline behavior, not proof that either regressor fails on a known input.

Errors are minutes to an analytical crossing, not verified docking. MAE weights
supported approaches equally; MdAE pools supported absolute errors. With partial
coverage these are conditional metrics, and matched original errors use the same
decision/seed pairs. `summary.csv` includes matched changes and vessel-cluster
bootstrap intervals; `per_seed_summary.csv` preserves each realization separately.

The baseline already excludes naturally unknown classes; it is not a verified
complete feed. Synthetic 10-100% masking applies to originally classified evaluation
histories and is not an estimate of natural source impact. Unknown-class source
records do not provide demonstrated cargo membership or reference arrivals here.
April was already inspected; this is follow-up evidence, not a pristine holdout.
Seeds 4201/4202/4203 change fault selection, with no retraining. Total removal is
seed independent and evaluated once. No forced ETA shifts or default classes.

Retaining an explicit unknown class would require a declared eligibility policy
and compatible model features/training; this experiment does not claim that fix.
The replay endpoint exposes exclusions and unavailable forecasts, without changing
the default ingestion pipeline, trained artifacts or frontend. CSVs remain local
and ignored by Git; this report, protocol and validation JSON can be tracked.

Reproduce from `Data_Science`: `python experiments/missing_vessel_class_attack/run.py`.

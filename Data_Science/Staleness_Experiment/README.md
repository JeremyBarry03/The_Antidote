# Missing-update and ETA experiment

Run from `Data_Science` using the existing Python 3.11 environment:

```powershell
python Staleness_Experiment/run.py
```

This is a separate follow-up experiment. It reads the existing frozen XGBoost B
and cached reference approaches. It does not retrain A/B/C, modify source data,
or update the demo. Rerunning replaces only this experiment's `results/` files.
The existing `Data_Science/requirements.txt` provides its dependencies.

## Design

- March 20-24 development chooses age triggers from 2, 5, 10, and 15 minutes.
- April 8-21 evaluation retains all 112 qualifying approaches and scheduled
  decisions, including forecasts unavailable because withholding removes all history.
- Each decision is replayed with 0, 2, 5, 10, and 15 minutes withheld. Future
  reports are never inputs. The arrival label stays the original analytical crossing.
- B uses its existing timestamp-correct prediction. No extra age subtraction or
  double-counting of elapsed time is introduced.
- Motion correction uses a straight-line motion fit from at most ten minutes
  before the last available observation. It must predict a future westward
  crossing inside the gate with adequate supporting history. Unsupported cases
  retain B. It is an experimental comparator, not a trained model.
- Verification requests begin when evidence age reaches the March-selected trigger.
  A successful simulated request restores only the latest original report at or
  before the decision time, if newer than the available evidence. This tests a
  conditional external-information intervention, not independent recovery of
  missing truth. It assumes successful access without acquisition delay.
- Natural gaps are audited separately as consecutive reports more than two minutes
  apart. These are observed gaps, not evidence of intentional poisoning or measured
  receiver delay. History filtering and qualifying-arrival selection affect counts.

Thresholds minimize mean condition-level, approach-weighted absolute error on March
development; ties prefer fewer interventions. April is a follow-up evaluation:
earlier project work and this conversation already inspected April aggregate results
and selected vessel cases. No claim of a new pristine holdout is made.

## Outputs

`results/REPORT.md` contains results and limitations. CSVs retain the predictions,
age, actual horizon, signed errors, interventions, unavailable cases, natural gaps,
per-approach results, and verification request burden. Paired uncertainty uses 1,000
vessel-cluster bootstrap samples of approach-level differences. Negative paired
differences favor the right-hand system; positive differences indicate harm.

MAE gives each approach equal weight. Median, 95th percentile and errors exceeding
15 minutes are decision-level descriptive metrics. The 15-minute cutoff is not a
validated operational tolerance. Coverage and matched-case denominators accompany
comparisons; unsupported forecasts are never assigned zero error.

Selected timeline examples explicitly show the largest motion recovery and loss
at fifteen-minute withholding (where the locked trigger activates), plus the first evaluation approach by ID with a natural
gap containing a scheduled decision. They are not representative samples.

## Boundaries

No human walkthrough, verification response time, or actual operator trust was
measured. Requests are a workload proxy, not minutes of human effort. Natural-gap
comparisons are observational and confounded by vessel behavior. We cannot restore
an unobserved position inside a natural gap. Docking timestamps, complete-outage
recovery and actual source latency remain unverified. Existing unresolved/nonarrival
episodes are outside this conditional crossing cohort.

# Findings: missing updates and ETA

## Verdict

Deliberately withholding recent reports worsened the existing XGBoost B model's
analytical-crossing ETA. Restoring one actual recent historical report recovered
most of that average loss. This is evidence for a conditional verification path,
not a newly successful model or autonomous data repair. The motion-only correction
failed. Natural gaps in this selected cohort did not establish an accuracy problem.

## April follow-up results

112 approaches, 110 vessels, 2,402 scheduled prediction times. No retraining.
Values below are approach-weighted mean absolute error in minutes; lower is better.

| Recent reports withheld | B | Motion intervention | One verified update | Output coverage |
|---|---:|---:|---:|---:|
| None | 6.30 | 6.30 | 6.30 | 100% |
| 2 minutes | 6.95 | 6.95 | 6.28 | 100% |
| 5 minutes | 7.95 | 7.95 | 6.26 | 100% |
| 10 minutes | 10.35 | 10.35 | 6.48 | 100% |
| 15 minutes | 10.88 | 14.06 | 6.28 | 95.34% |

At 15-minute withholding, 112 scheduled decisions have no remaining input history.
All interventions retain those unsupported cases; verification was not tested as
an outage-recovery mechanism. The 15-minute row therefore has a different available
case mix from the other rows. Paired comparisons below use identical supported
decisions, including when comparing with the original feed.

## Matched evidence

Withholding ten minutes increases B error by **4.05 minutes** against its same-case
original-feed forecasts (vessel-cluster bootstrap 95% interval **2.77 to 5.71**).
Restoring one recent report reduces error by **3.87 minutes** relative to stale B
(95% interval **2.59 to 5.49 minutes recovered**). It improves 59.4% of decisions and
worsens 40.6%, so recovery is not universal.

At 15 minutes, restoration reduces error by **4.60 minutes** (95% interval
**2.95 to 6.86 minutes recovered**). Motion correction instead increases error by
**3.18 minutes** (95% interval **2.44 to 4.00 minutes worse**).

March development selected a 15-minute age trigger for motion and a two-minute
trigger for verification. Motion does not activate at 0/2/5/10-minute withholding
on this evaluation set; its identical results there reflect fallback to B, not a
successful motion prediction. The threshold search did not include an off option;
the separate B comparator establishes why the motion intervention should be rejected.

## Observed natural gaps

The audit found **19 gaps longer than two minutes** inside qualifying April
approach histories, with a maximum of **8.5 minutes**. Fourteen gaps contain at least
one scheduled prediction: **16 decisions across 11 approaches**. Some decisions
occur soon after the preceding report; being inside a gap does not itself mean
the evidence is already old. Latest-report ages during those decisions range from
0.18 to 7.7 minutes.

Their approach-weighted B error is **3.69 minutes** versus **6.32 minutes** outside
these gaps, on unequal case mixes. This does not demonstrate harm from natural
gaps, nor prove that gaps help. Across 14 last-during/first-after gap pairs, error
actually increases by 1.29 minutes on average after reporting resumes. Decision
time and vessel state also change, so that is observational, not a causal test.

There is no newer recorded report to restore inside a natural gap. The verification
policy makes six requests on the original feed and has no eligible update for any
of them. We have not demonstrated a fix for those natural gaps.

## Practical limit of verification

At ten-minute withholding, the policy requests an update at every scheduled
decision: **2,402 requests, about 21.45 per approach**. It assumes an eligible
alternate report can be obtained without acquisition delay. No operator time,
verification success probability, or cost was measured. This could be a substantial
human burden. The result supports investigating a fresh-information channel,
not claiming a deployable human-review policy.

## Decision

Keep B. Reject the tested motion replacement. Treat verified updates as a promising
but conditional information-recovery experiment. Before a pilot, obtain a real
alternate update source and measure availability, latency, effort, and cost. Then
lock a lower-burden request policy on development data and evaluate it on a new
period; do not tune again against these April results and call them untouched.

The dataset and gate are a logistics proxy: errors are not docking-time errors.
April results were previously inspected in project work, so this is a follow-up
analysis. Source data and the frozen B artifact were preserved. Full settings,
checks, per-decision outputs, age/horizon summaries, workload and paired uncertainty
are saved alongside this report. No UI changes were made.

# Staleness experiment results

Existing frozen B; original source files untouched. April results are follow-up analyses, not a new pristine holdout. No models were retrained.

March-selected thresholds (minutes): {'motion': 15.0, 'verified_update': 2.0}.

## April condition results

withheld_minutes,system,scheduled,available,approaches,coverage,approach_mae,decision_median_error,decision_p95_error,over_15_minutes_rate,intervention_rate,verification_request_rate

0,B,2402,2402,112,1.0,6.2989,2.5565,21.875,0.102,0.0,0.0

0,motion,2402,2402,112,1.0,6.2989,2.5565,21.875,0.102,0.0,0.0

0,verified_update,2402,2402,112,1.0,6.2989,2.5565,21.875,0.102,0.0,0.0025

2,B,2402,2402,112,1.0,6.9486,2.7459,23.2307,0.1099,0.0,0.0

2,motion,2402,2402,112,1.0,6.9486,2.7459,23.2307,0.1099,0.0,0.0

2,verified_update,2402,2402,112,1.0,6.2815,2.5568,21.8738,0.1007,0.9975,1.0

5,B,2402,2402,112,1.0,7.9513,3.047,24.5418,0.1199,0.0,0.0

5,motion,2402,2402,112,1.0,7.9513,3.047,24.5418,0.1199,0.0,0.0

5,verified_update,2402,2402,112,1.0,6.2648,2.5853,21.5872,0.0987,0.9992,1.0

10,B,2402,2402,112,1.0,10.3481,3.5991,27.8934,0.1386,0.0,0.0

10,motion,2402,2402,112,1.0,10.3481,3.5991,27.8934,0.1386,0.0,0.0

10,verified_update,2402,2402,112,1.0,6.4763,2.6513,22.253,0.1032,1.0,1.0

15,B,2402,2290,112,0.9534,10.8821,3.934,28.622,0.1454,0.0,0.0

15,motion,2402,2290,112,0.9534,14.0615,4.7392,40.9552,0.2384,0.5837,0.0

15,verified_update,2402,2290,112,0.9534,6.2782,2.5994,21.8394,0.1013,0.9534,0.9534



## Paired changes and vessel-cluster bootstrap intervals

comparison,left,right,matched_decisions,approaches,vessels,mean_change,ci_low,ci_high,decision_improved_share,decision_worsened_share,withheld_minutes

0 min withheld: correction minus B,B,motion,2402,112,110,0.0,0.0,0.0,0.0,0.0,0

0 min withheld: correction minus B,B,verified_update,2402,112,110,0.0,0.0,0.0,0.0,0.0,0

0 min withheld B minus original B,original_B,withheld_B,2402,112,110,0.0,0.0,0.0,0.0,0.0,0

2 min withheld: correction minus B,B,motion,2402,112,110,0.0,0.0,0.0,0.0,0.0,2

2 min withheld: correction minus B,B,verified_update,2402,112,110,-0.6671,-1.2397,-0.2289,0.5233,0.4742,2

2 min withheld B minus original B,original_B,withheld_B,2402,112,110,0.6497,0.2107,1.2119,0.4788,0.5187,2

5 min withheld: correction minus B,B,motion,2402,112,110,0.0,0.0,0.0,0.0,0.0,5

5 min withheld: correction minus B,B,verified_update,2402,112,110,-1.6864,-2.4793,-1.1219,0.5616,0.4376,5

5 min withheld B minus original B,original_B,withheld_B,2402,112,110,1.6524,1.0825,2.4361,0.4442,0.555,5

10 min withheld: correction minus B,B,motion,2402,112,110,0.0,0.0,0.0,0.0,0.0,10

10 min withheld: correction minus B,B,verified_update,2402,112,110,-3.8719,-5.4889,-2.5858,0.5937,0.4063,10

10 min withheld B minus original B,original_B,withheld_B,2402,112,110,4.0492,2.7657,5.7097,0.4009,0.5991,10

15 min withheld: correction minus B,B,motion,2290,112,110,3.1794,2.4366,4.0006,0.2472,0.3651,15

15 min withheld: correction minus B,B,verified_update,2290,112,110,-4.6039,-6.8618,-2.9481,0.6127,0.3873,15

15 min withheld B minus original B,original_B,withheld_B,2290,112,110,4.9849,3.3754,7.2155,0.3624,0.6376,15



## Interpretation limits

Natural gaps are observed within cached qualifying approach histories. They do not establish receiver latency, corruption, or causation. Gaps with no scheduled decision are counted separately. Unresolved/nonarrival episodes are excluded by the existing cohort.
Matched withholding isolates missing recent information on the original-report reference; it is simulated, not naturally observed latency. The reference itself is not perfect ground truth.
Motion is a constant-velocity gate-crossing alternative with conservative support rules; otherwise it retains B. It can fail under stops and turns. Thresholds use March development, but other April findings had been inspected before this experiment.
Verified update restores at most one historical report measured by the decision time. This is conditional on a successful external verification; it is not an autonomous repair. Natural gaps have no invented update. Requests are counted, but no human effort duration or trust study has been measured.
Error is relative to analytical gate crossing, not verified docking. Report coverage and failure tails alongside averages. A 15-minute large-error threshold is descriptive, not a validated operational tolerance.
Examples are explicitly selected largest motion recovery/loss at fifteen-minute withholding; the natural-gap plot is the first qualifying evaluation approach by ID. These are illustrations, not representative performance estimates.

Run: `python Staleness_Experiment/run.py` from Data_Science. See protocol.json, locked_thresholds.json, and validation.json for settings and checks.
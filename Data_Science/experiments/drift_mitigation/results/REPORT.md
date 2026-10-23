# Drift mitigation: separate and combined attacks

## Findings

- Speed-only drift: average injected speed error falls from
  2.633 to 2.331
  knots (11.4% reduction). Only 13.1% of
  decision-time readings are repaired; 86.9%
  request review. Most reference refusals involve maneuvering/inconsistent position
  tracks or waiting for sufficient supported history after a reset.
- Independent speed and location drift together: average speed error falls to
  2.367 knots (10.1% reduction).
  All attacked approaches raise a location consistency warning. Coordinates are
  never repaired by this policy.
- The location warning also flags 18.75% of
  original-feed approaches (21/112), and every speed-only attacked approach. It
  detects disagreement but cannot identify which sensor is wrong.
- Under location-only drift, the speed policy makes 37 replacements that worsen
  agreement with untouched original speed. A naive location-warning veto blocks
  every speed replacement, including speed-only cases.
- The coordinated example below evades both checks. These policies are useful
  prototype components, but their current combination is not a validated automatic
  recovery system. Fault isolation and development calibration remain necessary.

The percentages above concern these fixed simulated settings. They do not measure
ETA accuracy or establish performance against other attack combinations.

## Scope and protocol

This study supplies no verified position anchors or independent navigation trust.
It measures detection-only location behavior; the optional anchored correction
extension is outside its scope. The archived results predate that extension.

This evaluates the existing default policies without fitting or changing thresholds.
The previously inspected April 8–21 replay contains 112 approaches, 110 vessels and
2,402 original decision clocks per scenario. Source AIS is the recovery reference,
not independently verified physical truth. This is an exploratory follow-up.

Speed drift is ±0.1 knots/minute with a smooth 3-knot cap. Location drift is
20 meters/minute with a smooth 1,852-meter cap and a seeded fixed bearing per
vessel. Default seed 42, 25% rate variation and a 20-minute cycle are used. Both
faults start at each approach's first supplied report. Combined scenarios compose
these two attacks; source timestamps, report counts and decision clocks stay fixed.
No missing-data, gap, noise or sudden-jump attacks are included in this study.

Each mitigation sees only received attacked reports at the current clock; it never
sees source values, injected biases or future reports. Both policies inspect the
raw attacked stream independently. Feeding repaired speed back into the location
check would artificially force agreement and is not done here.

## Sensor recovery

The speed policy replaces the current speed only when its existing persistence and
position-quality checks pass. Otherwise its output retains reported speed and may
request review. No decision, including review/warmup cases, is dropped from error
calculations. MAE below gives each approach equal weight. These are sensor errors
in knots, **not ETA errors**; no model forecasts or production adapters are evaluated.

| Scenario | Speed MAE before | Speed MAE after | Change [95% interval] | Decisions repaired | Repairs that worsen speed error |
|---|---:|---:|---:|---:|---:|
| combined_over | 2.6326 | 2.3673 | -0.2653 [-0.3256, -0.2082] | 12.49% | 0.00% |
| combined_under | 2.6326 | 2.3668 | -0.2659 [-0.3260, -0.2090] | 12.61% | 0.00% |
| location | 0.0000 | 0.0101 | +0.0101 [+0.0060, +0.0151] | 1.54% | 100.00% |
| original | 0.0000 | 0.0006 | +0.0006 [+0.0000, +0.0018] | 0.08% | 100.00% |
| speed_over | 2.6326 | 2.3313 | -0.3014 [-0.3632, -0.2374] | 13.11% | 0.00% |
| speed_under | 2.6326 | 2.3313 | -0.3014 [-0.3632, -0.2374] | 13.11% | 0.00% |

Intervals use 1,000 paired vessel-cluster bootstrap draws with fixed seed 20261022.
They describe the sampled approaches conditional on these single-seed scenarios;
they do not establish generalization across attack settings or populations.
An unchanged error is omitted from both helped and harmed counts.

## Alerts and review burden

An approach is flagged if a flag is present at any evaluated clock. Speed flags
are current repair decisions; location flags latch for the supplied session.
Therefore their approach rates do not represent equally persistent detectors.
The columns below are observed alert rates, not fault-specific classification
accuracy. A speed fault can activate the location consistency check and vice versa.

| Scenario | Approaches with speed flag | Approaches with location flag | Either flag | Speed review: decisions | Location review: decisions |
|---|---:|---:|---:|---:|---:|
| combined_over | 75.00% | 100.00% | 100.00% | 87.22% | 99.96% |
| combined_under | 75.89% | 100.00% | 100.00% | 87.22% | 99.96% |
| location | 19.64% | 100.00% | 100.00% | 87.22% | 99.96% |
| original | 0.89% | 18.75% | 18.75% | 86.89% | 18.36% |
| speed_over | 78.57% | 100.00% | 100.00% | 86.89% | 100.00% |
| speed_under | 78.57% | 100.00% | 100.00% | 86.89% | 100.00% |

The original-feed row measures alerts without any injected fault, not proven false
positives against verified physical truth. A high rate limits the detector's ability
to distinguish a new fault from existing AIS disagreement. Review includes warming
up, unsupported input and detected location drift, so review is not a missed alarm.

### Location detection incremental to original-feed alerts

| Scenario | Already flagged original approaches | Newly flagged approaches | Original flags lost |
|---|---:|---:|---:|
| location | 21 | 91 | 0 |
| combined_under | 21 | 91 | 0 |
| combined_over | 21 | 91 | 0 |

## Combination policy diagnostic

The existing modules are independent. An experiment-only rule that permits speed
repair only when the location policy recommends normal input yields:

| Scenario | Speed MAE with location veto | Decisions repaired |
|---|---:|---:|
| combined_over | 2.6326 | 0.00% |
| combined_under | 2.6326 | 0.00% |
| location | 0.0000 | 0.00% |
| original | 0.0000 | 0.00% |
| speed_over | 2.6326 | 0.00% |
| speed_under | 2.6326 | 0.00% |

This veto is not installed in production, not a fitted strategy, and not validated
as a reliable fault classifier. Its improvement or lack of coverage must be read
alongside the original-feed alert rate. Location coordinates remain uncorrected
in every scenario: this mitigation requests an independent verified position.

## Coordinated corruption counterexample

A separate synthetic 10-knot straight track is attacked with positive speed drift.
Reported positions integrate the attacked speed using the same trapezoidal motion
rule as the location detector. This deliberately coordinated construction differs
from the default independent location attack and is an observability stress example,
not a measured prevalence estimate.

After 30 minutes, speed error is 2.235 knots and location error is 1156.3 meters. Across 31 checks, the speed policy flags 0 and the location policy flags 0. Mutually consistent corrupted measurements can evade both checks. An independent trustworthy reference is needed to resolve this ambiguity.

## Interpretation and limits

These results evaluate initial drift policies, not a deployed end-to-end mitigation
system. Unsupported references are an intentional safeguard but reduce automatic
repair coverage. Source AIS itself can contain noise, maneuvers and synchronization
errors. Current location thresholds are provisional and have not been calibrated
on a separate development cohort. Do not tune them against this evaluation cohort
and then present the same results as validation. ETA improvement requires a separate
causal feature/forecast evaluation with the current frozen model artifacts.

CSV decision-level outputs and summaries are local ignored artifacts. Protocol,
validation metadata and this report are saved alongside the reproducible script.
Run from Data_Science: `python experiments/drift_mitigation/run.py`.

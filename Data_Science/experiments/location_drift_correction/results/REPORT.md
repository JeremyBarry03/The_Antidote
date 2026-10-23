# Location correction: position accuracy and legacy-v1 ETA evaluation

## Findings

- Without an extra trusted-position feed, current coordinates and ETA forecasts
  remain unchanged. One initial fix expires before the evaluated forecast clocks.
- **Conditional location-only result:** simulated trusted refreshes reduce average
  position disagreement from 1015.90 to
  93.69 meters (90.8% reduction).
  91.5% of decision-time readings receive a correction.
- Legacy Antidote C's location-attacked ETA MAE falls from 6.8406
  to 5.9065 minutes; its original-feed MAE is 5.8086.
  The paired improvement is 0.9341 minutes, with a
  conditional 95% interval [0.7142, 1.1506].
- Under combined attacks, independently rejecting navigation trust blocks all
  coordinate corrections. The incorrect-trust control yields inconsistent ETA
  changes across speed directions and systems. It is not a deployable trust policy.
- The trusted fixes and reliability decisions are simulated extra information;
  the repo does not currently provide them. Only older v1 ETA models are measured.
  These findings do not establish performance for current-v2 or autonomous recovery.

| Legacy model, location-only attack | ETA MAE before (minutes) | ETA MAE after (minutes) |
|---|---:|---:|
| A_v1 | 8.2151 | 7.4117 |
| B_v1 | 7.5215 | 6.4228 |
| C_v1 | 6.8406 | 5.9065 |


## What is actually available

The repository has no independently verified position/navigation feed. Without one,
the correction supplies no replacement coordinates. A single trusted fix at approach
start expires after five minutes; all 2,402 official forecast clocks begin at least
ten minutes into their approaches, so that case produces **zero current corrections
and zero forecast changes**. It is insufficient to support a whole-approach recovery
claim. This follows from the existing clock schedule and fixed five-minute policy.

## Conditional extra-reference simulation

To evaluate the correction when its prerequisites are supplied, an additional
SIMULATED trusted-position channel samples original AIS coordinates at the first
received report in each five-minute bin. Fixes become available at their original
measurement times. There is no interpolation from future source positions.
These fixes are evaluator-generated stand-ins, not an available deployed sensor.
Original AIS is the recovery reference, not independently verified physical truth.
Each supplied fix has zero error relative to that reference by construction; real
anchor noise and delivery delays are not simulated. This is an optimistic test.
Any gains depend on access to this extra reference channel and navigation trust.

For original-feed and location-only cases, navigation trust is stipulated because
the simulated injection leaves speed/course unchanged. For combined attacks,
`periodic_verified` stipulates independent rejection of navigation trust and
therefore blocks correction. This is an oracle reliability assumption for evaluation,
not a capability to automatically identify which sensor is faulty. The separate
`incorrect_navigation_trust` control deliberately trusts poisoned speed to expose
the consequence of a wrong trust decision. No original speed is substituted.

The previously inspected April 8–21 cohort contains 112 approaches / 110 vessels /
2,402 clocks. Location drift is 20 meters/minute, smoothly capped at 1,852 meters,
in a seeded per-vessel direction. Combined cases also apply speed drift ±0.1 knots/
minute capped at 3 knots. Default seed 42, 25% rate variation, 20-minute profile
cycle and an origin at each approach's first report are fixed. No tuning occurs.

Each repair uses only the raw report prefix and anchor available at that reading's
delivery time. No later anchor can rewrite previous corrections. The current
estimate must still be valid at the forecast clock; otherwise raw inputs remain
and the strategy's review recommendation is retained. Every original clock is
retained in error/coverage reporting. Speed, course, identities and times are unchanged.

## Position accuracy

MAE gives approaches equal weight; P95 pools decision-time distances. Values are
meters of disagreement with original AIS positions. Review includes unsupported
or expired input and is reported separately from raw forecast availability.

| Scenario | Handling | Position MAE before | Position MAE after | P95 after | Readings corrected | Review | Readings worsened |
|---|---|---:|---:|---:|---:|---:|---:|
| combined_over | incorrect_navigation_trust | 1015.90 | 228.93 | 890.40 | 91.47% | 8.49% | 0.00% |
| combined_over | periodic_verified | 1015.90 | 1015.90 | 1592.34 | 0.00% | 99.96% | 0.00% |
| combined_over | reported_only | 1015.90 | 1015.90 | 1592.34 | 0.00% | 99.96% | 0.00% |
| combined_under | incorrect_navigation_trust | 1015.90 | 230.92 | 890.40 | 91.47% | 8.49% | 0.00% |
| combined_under | periodic_verified | 1015.90 | 1015.90 | 1592.34 | 0.00% | 99.96% | 0.00% |
| combined_under | reported_only | 1015.90 | 1015.90 | 1592.34 | 0.00% | 99.96% | 0.00% |
| location | periodic_verified | 1015.90 | 93.69 | 890.40 | 91.47% | 8.49% | 0.00% |
| location | reported_only | 1015.90 | 1015.90 | 1592.34 | 0.00% | 99.96% | 0.00% |
| original | periodic_verified | 0.00 | 3.29 | 22.15 | 13.03% | 5.33% | 11.20% |
| original | reported_only | 0.00 | 0.00 | 0.00 | 0.00% | 18.36% | 0.00% |

## ETA models and compatibility

Only older **v1** frozen A (quadratic), B (XGBoost) and C (Antidote) artifacts are
available locally. Current vessel-class-v2 artifacts are absent. These results
must not be presented as current-v2 performance. The production compatibility
loader remains unchanged. This experiment separately loads the explicitly legacy
bundles after checking saved model/config/source hashes and restricting known
implementation differences to the vessel-class feature and legacy-schema recovery
modules. Every nominal A/B/C forecast and availability is then reproduced against
the archived v1 evaluation before interpreting attacked results:

| Legacy system | Baseline clocks reproduced | Maximum forecast difference (minutes) |
|---|---:|---:|
| A_v1 | 2402 | 7.1054273576e-15 |
| B_v1 | 2402 | 7.1054273576e-15 |
| C_v1 | 2402 | 1.42108547152e-14 |

The experiment adapter recomputes kinematic features using the shared extractor.
C retains incoming-feed quality features and provenance; corrected coordinates
cannot erase the original quality evidence. A corrected C view is used only when
its observation timestamp matches the raw guarded view. Otherwise the raw view
and its coverage are retained. Raw unsupported cases remain in the denominator.
Forecasts are scored even when review is recommended; no selective removal of
difficult clocks improves accuracy artificially. No calibration, acceptance or
interval-coverage claim is made, and no model is retrained.

## ETA results

MAE gives approaches equal weight. MdAE and P95 pool decision errors. All values
are minutes to the original analytical gate crossing, not verified docking.
Changes compare each case to its own attacked/no-correction forecast. Intervals
use 1,000 paired vessel-cluster bootstrap draws (seed 20261021). This single-seed,
previously inspected cohort remains exploratory; gains need fresh validation.

| Legacy system | Scenario | Handling | Raw MAE | After MAE | Change [95% interval] | MdAE | P95 | Forecast coverage |
|---|---|---|---:|---:|---:|---:|---:|---:|
| A_v1 | combined_over | incorrect_navigation_trust | 10.6087 | 10.1900 | -0.4187 [-0.9869, +0.0574] | 8.5155 | 27.4868 | 100.00% |
| A_v1 | combined_over | periodic_verified | 10.6087 | 10.6087 | +0.0000 [+0.0000, +0.0000] | 8.7810 | 29.3505 | 100.00% |
| A_v1 | combined_over | reported_only | 10.6087 | 10.6087 | +0.0000 [+0.0000, +0.0000] | 8.7810 | 29.3505 | 100.00% |
| A_v1 | combined_under | incorrect_navigation_trust | 14.1212 | 13.7478 | -0.3734 [-0.8036, +0.0329] | 10.7328 | 38.7550 | 100.00% |
| A_v1 | combined_under | periodic_verified | 14.1212 | 14.1212 | +0.0000 [+0.0000, +0.0000] | 10.7249 | 38.7426 | 100.00% |
| A_v1 | combined_under | reported_only | 14.1212 | 14.1212 | +0.0000 [+0.0000, +0.0000] | 10.7249 | 38.7426 | 100.00% |
| A_v1 | location | periodic_verified | 8.2151 | 7.4117 | -0.8034 [-1.2849, -0.4770] | 4.9946 | 23.1557 | 100.00% |
| A_v1 | location | reported_only | 8.2151 | 8.2151 | +0.0000 [+0.0000, +0.0000] | 6.1200 | 25.2452 | 100.00% |
| A_v1 | original | periodic_verified | 7.3163 | 7.3136 | -0.0027 [-0.0099, +0.0045] | 4.9137 | 23.7816 | 100.00% |
| A_v1 | original | reported_only | 7.3163 | 7.3163 | +0.0000 [+0.0000, +0.0000] | 4.9189 | 23.4772 | 100.00% |
| B_v1 | combined_over | incorrect_navigation_trust | 8.7122 | 8.8913 | +0.1791 [-0.0541, +0.4261] | 5.9752 | 27.1592 | 100.00% |
| B_v1 | combined_over | periodic_verified | 8.7122 | 8.7122 | +0.0000 [+0.0000, +0.0000] | 5.8367 | 26.5611 | 100.00% |
| B_v1 | combined_over | reported_only | 8.7122 | 8.7122 | +0.0000 [+0.0000, +0.0000] | 5.8367 | 26.5611 | 100.00% |
| B_v1 | combined_under | incorrect_navigation_trust | 15.0306 | 14.3307 | -0.6999 [-1.1035, -0.3252] | 10.4149 | 34.7263 | 100.00% |
| B_v1 | combined_under | periodic_verified | 15.0306 | 15.0306 | +0.0000 [+0.0000, +0.0000] | 11.0437 | 37.5581 | 100.00% |
| B_v1 | combined_under | reported_only | 15.0306 | 15.0306 | +0.0000 [+0.0000, +0.0000] | 11.0437 | 37.5581 | 100.00% |
| B_v1 | location | periodic_verified | 7.5215 | 6.4228 | -1.0986 [-1.3110, -0.8970] | 2.9989 | 22.8716 | 100.00% |
| B_v1 | location | reported_only | 7.5215 | 7.5215 | +0.0000 [+0.0000, +0.0000] | 4.4500 | 22.8590 | 100.00% |
| B_v1 | original | periodic_verified | 6.2838 | 6.2833 | -0.0005 [-0.0049, +0.0031] | 2.7754 | 22.5938 | 100.00% |
| B_v1 | original | reported_only | 6.2838 | 6.2838 | +0.0000 [+0.0000, +0.0000] | 2.7803 | 22.5938 | 100.00% |
| C_v1 | combined_over | incorrect_navigation_trust | 8.0062 | 8.0165 | +0.0102 [-0.2903, +0.3313] | 5.8685 | 26.0799 | 100.00% |
| C_v1 | combined_over | periodic_verified | 8.0062 | 8.0062 | +0.0000 [+0.0000, +0.0000] | 5.7078 | 26.2077 | 100.00% |
| C_v1 | combined_over | reported_only | 8.0062 | 8.0062 | +0.0000 [+0.0000, +0.0000] | 5.7078 | 26.2077 | 100.00% |
| C_v1 | combined_under | incorrect_navigation_trust | 13.3244 | 12.4078 | -0.9167 [-1.3645, -0.4782] | 9.1663 | 29.9500 | 100.00% |
| C_v1 | combined_under | periodic_verified | 13.3244 | 13.3244 | +0.0000 [+0.0000, +0.0000] | 9.9327 | 35.4954 | 100.00% |
| C_v1 | combined_under | reported_only | 13.3244 | 13.3244 | +0.0000 [+0.0000, +0.0000] | 9.9327 | 35.4954 | 100.00% |
| C_v1 | location | periodic_verified | 6.8406 | 5.9065 | -0.9341 [-1.1506, -0.7142] | 2.9642 | 22.5109 | 100.00% |
| C_v1 | location | reported_only | 6.8406 | 6.8406 | +0.0000 [+0.0000, +0.0000] | 4.2332 | 23.2623 | 100.00% |
| C_v1 | original | periodic_verified | 5.8086 | 5.8100 | +0.0014 [-0.0017, +0.0049] | 2.8696 | 22.3740 | 100.00% |
| C_v1 | original | reported_only | 5.8086 | 5.8086 | +0.0000 [+0.0000, +0.0000] | 2.8696 | 22.3041 | 100.00% |

## Limits and reproduction

Improved position agreement does not guarantee ETA improvement: saved models can
respond differently to partially corrected histories. Original AIS has existing
timing/navigation error; an alert on original data is not proof of an attack or a
physically incorrect reading. Extra anchors and oracle trust assumptions must
remain explicit. Combined coherent corruption may evade the consistency detector.
Only coordinates are repaired here; this is not a fitted fusion or a joint
speed/location fault-isolation system. No frontend/service integration changes.

Reproduce from Data_Science:
`python experiments/location_drift_correction/run.py`.
Protocol, integrity checks and this report are retained; generated CSVs stay local
and ignored. No source data, model, thresholds or shared inference code is modified.

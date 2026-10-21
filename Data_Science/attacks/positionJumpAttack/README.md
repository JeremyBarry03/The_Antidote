# PositionJumpAttack

Simulated location errors: selected AIS fixes are displaced, while unselected
fixes retain their original latitude/longitude. This creates a jump-and-return
pattern at partial prevalence. All reports remain; SOG, COG, MMSI, classification,
measurement/delivery times and original crossing references remain unchanged.

The motivating source audit found implausible 21–43 km jumps followed by returns.
It did not establish whether GPS, identity, timestamps or processing caused them.
Those severe source jump endpoints did not appear in the prepared model histories.
This attack simulates one isolated mechanism on a copied feed. Original reported
coordinates are references, not independently verified physical truth.

```python
from attacks import PositionJumpAttack, PositionJumpConfig

settings = PositionJumpConfig(
    displacement_meters=2000,
    affected_fraction=.20,
    seed=4201,
    target_mmsi="255803201",  # Optional; otherwise all supplied vessels.
    start_time="2024-04-08 06:00:00",  # Optional window; supply both bounds.
    end_time="2024-04-08 06:15:00",
)
stream = PositionJumpAttack(settings).apply(reports)
received = stream.available(decision_time)
```

## Configuration and behavior

Frozen `PositionJumpConfig` defaults: 2,000 meters, 25% of eligible reports, seed
42, all vessels, no time window, and an automatically selected bearing. A custom
`bearing_degrees` in [0,360) fixes the direction clockwise from north.

- Percentage applies to eligible reports, not approaches or vessels. It uses the
  existing identity-hash threshold, so 10%, 20%, 25%, 50%, 100% and custom fractions
  are reproducible Bernoulli selections rather than exact-count quotas.
- Selection is stable when rows are shuffled, duplicated, appended with future
  reports, or when displacement severity changes. Duplicate copies share the
  same selection and displacement. Another vessel does not alter existing draws.
- Automatic bearing is sampled once per MMSI using the existing seeded generator.
  Selected reports from that vessel share the bearing. It never depends on the
  supplied history's future duration, original arrival label, or prediction errors.
- The optional time window is half-open `[start_time,end_time)`, interpreted on
  measurement time. Outside it every fix stays original. A sufficiently narrow
  explicit window can select one report; 100% in a short window produces a burst.
  At 100% over the entire supplied feed, all eligible fixes are displaced and
  there are no correct intermediate fixes. Normal locations resume after a window.
- Spherical forward geodesics preserve the requested surface distance in meters,
  including at high latitudes and across the antimeridian. Source coordinates
  must be finite latitude [-90,90] and longitude [-180,180]. Missing, invalid and
  unavailable-sentinel positions remain unchanged and ineligible. Unparsed
  strings/bools/complex coordinate columns fail clearly; numeric nullable columns
  work. Zero distance/fraction is a no-op.
- No source files, reports' order, or original data frames are mutated. The
  common preparation helper may add missing record/delivery metadata to the copy.
- The separate audit stores eligibility, window membership, selection, original
  and reported coordinates, bearing, requested/applied displacement and actual
  change flags. `fault_applied` requires an actual change. Audit truth never enters
  model features. All scoring/model loading/file writing lives outside the attack.

The existing frozen-model feature/replay implementation files are unchanged.
Changing coordinates affects derived positions, motion fits and C's existing
guard behavior; no extra mitigation is implemented. Models may worsen, improve,
or stay unchanged. Forecast recovery can outlast a corruption window because
recent history still contains the altered fixes.

## Replay/API

The paired endpoint follows the existing attack endpoints:

```text
GET /api/attacks/position-jump?decision=<decision_id>&affected_fraction=0.2&displacement_meters=2000&seed=4201&inspect=true
```

Optional parameters: `target_mmsi`, `bearing_degrees`, `start_time`, `end_time`,
`reveal=true`. It returns `original` and `attacked` A/B/C snapshots at one unchanged
clock/reference. Outcomes stay hidden until reveal; standalone attacks are
uncalibrated and cannot invoke simulated verification. Inspection shows delivered
records only and joins known original positions after inference.

The backend catalog exposes 10%, 20%, 25%, 50%, and 100% presets at 2 km, using
the configured replay seed. `/api/replay` and `/api/timeline`
accept `position_jump_10pct`, `_20pct`, `_25pct`, `_50pct`, `_100pct`. Timelines
compute actual past/current predictions through the shared serving feature path.
Custom displacement/bearing/windows are available through Python and the paired
API. Frontend integration is deferred at the user's request; no frontend files
are changed by this implementation.

From Data_Science:

```text
python -m Optimized_Model serve --config Optimized_Model/config_vessel_class_v2.json --port 8765
```

Use the endpoints on `http://127.0.0.1:8765` for backend integration. The inspection
payload supplies original/reported positions and displacement for a future map UI.

## Frozen-model experiment

```text
python experiments/position_jump_attack/run.py
python -m pytest -q
```

Uses the same corrected frozen A/B/C artifacts, 112 April approaches and 2,402
decision times. The default compares 10/20/25/50/100% at 2 km, then 500 m / 20 km /
40 km at 25%, each with seeds 4201–4203. No retraining or recalibration. Reports
include approach-weighted MAE, pooled MdAE/P95, coverage and paired error changes.
Crossing targets/cohort membership are never recomputed from attacked fixes.

Optional timed comparison:

```text
python experiments/position_jump_attack/run.py --window-start-minutes 20 --window-duration-minutes 15 --output artifacts/position_jump_window
```

The Markdown report, protocol and validation JSON are kept in the experiment
folder. Generated CSVs remain local and ignored. These prevalence/displacement
settings are stress tests, not measured real-world error rates. The actual severe
source outliers were rare; April has been inspected previously and is not a pristine
holdout. The original analytical crossing is not a verified docking event.

Completed outputs:

- [Whole-cohort A/B/C report](../../experiments/position_jump_attack/results/REPORT.md)
- [One-vessel timed replay](../../experiments/position_jump_attack/results/WINDOW_EXAMPLE.md)
- [Timed replay ETA plot](../../artifacts/position_jump_attack/window_example.png)

The timed example is a separate single-approach replay, not a timed whole-cohort
study. It uses a 15-minute window, 2 km displacement and 100% selection inside the
window. Its ETA shifts are prediction changes, not necessarily error increases.

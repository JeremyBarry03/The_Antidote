# Mitigation strategies

Mitigations consume observable reports at a decision clock. They never receive
attack configuration, original hidden measurements, crossing targets, or an
attack modification log. Manager-facing prediction remains a single Antidote
model; development comparisons stay outside that model.

## Shared contract

`BaseMitigation` in `base_mitigation.py` is an abstract base class. Each subclass
provides `name`, JSON-safe `parameters`, and `apply(reports, decision_time)`.
Field-specific reconstruction stays in the subclass.

Reusable base behavior:

- Validate unique columns, MMSI, parsed measurement/delivery times, and clock
  compatibility. Select only already measured and delivered reports.
- Work on a private sorted copy, with a one-vessel-per-call contract. Future
  mitigations that repair only metadata do not need coordinate columns.
- Validate parsed numeric measurement fields without changing source values.
- Validate the latest received observation time independently of usable history.
- Share frozen `MitigationResult` provenance and JSON serialization. Each result
  supplies `can_predict`; subclass-specific statuses and diagnostics remain local.

No file writing, model loading, scoring or factories are part of this base.
Adapters and experiments own those responsibilities. Causal preparation applies
to the observed feed regardless of whether its gaps are natural or simulated.

`GapMitigation` is the first subclass. See [its README](gap_mitigation/README.md).
It detects per-vessel reporting silence; it does not reconstruct positions,
modify features, or retrain models. The former projection adapter and experiment
outputs have been removed.

`SensorDriftMitigation` monitors persistent signed speed/position disagreement.
After its EWMA and persistence checks pass, it returns guarded replacement speed
in a derived copy. See [the speed-drift strategy](sensor_drift_mitigation/README.md).

`LocationDriftMitigation` monitors persistent position/navigation disagreement.
It reconstructs coordinates briefly from an independent verified position when
speed/course are independently trusted; otherwise it requests verification.
Its raw-feed warning remains active through the supplied session.
See [the location-drift strategy](location_drift_mitigation/README.md).

These are separate strategies, not a classifier that can determine which of two
disagreeing sensors is correct. Their reference assumptions differ. Like the gap
strategy, they keep rules in their own modules; callers own API, ETA and review
workflow integration. Defaults require calibration before reliability claims.

The [initial drift evaluation](../experiments/drift_mitigation/results/REPORT.md)
measures separate and combined speed/location faults, original-feed alert burden,
and a coordinated-corruption counterexample. It predates the optional location
correction extension and supplies no verified anchors. It does not establish
location-correction or ETA improvement.

The [conditional location-correction study](../experiments/location_drift_correction/results/REPORT.md)
evaluates simulated periodic verified fixes and legacy-v1 ETA models. It reports
the extra reference/trust assumptions, unchanged outputs without those references,
and combined-attack controls.

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

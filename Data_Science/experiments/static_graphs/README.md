# Saved graph scenarios

The five scenario-dependent graphs use one checked-in JSON bundle, loaded once
by the browser. The selector below the graphs selects a saved joint run. It does
not combine single-attack errors or request inference. The reporting-delay
stress curve is a separate, fixed reference included in the same bundle.

Eight on/off attacks produce 256 scenarios, including the clean reference.
Every selected attack uses 25% of its actual replay control maximum: reporting
gap is 15 minutes and each other control is 25%. The replay sliders continue to
control the live map separately. Attacks in these saved evaluation graphs begin
at the existing March 15 cutover.

## Rebuild

From `Data_Science`, with the existing environment and frozen artifacts:

```sh
.venv/bin/python experiments/static_graphs/export.py --approaches 6 --workers 6
```

The default inputs are `data/hampton_roads_march_2024.csv` and the fitted A, B,
and nominal-only C artifacts under `artifacts/data_eval/optimized`. No training
occurs. Evaluation-only preparation uses the original crossing builder and
feature contract; it does not need the original training CSV. By default, six
approaches are selected by time and duration, spread across March. The same
cohort is used for every scenario; selection does not use prediction errors or
attack outcomes. The selector tooltip, accessible comparison label and saved
bundle disclose the sample.
Use `--approaches 0` for the full month. Daily summaries use the existing 15-minute
checkpoints, while convergence and 30-minute sequences use 5-minute checkpoints.

Outputs are written to `Frontend/tracking/data/scenarios.json`. Completed
scenario checkpoints are cached under `artifacts/static_graphs` so an interrupted
build can resume. Delete that cache before rebuilding after changing the
evaluation configuration. The bundle records source/model/code hashes, the
seed, selected approach IDs, period, coverage, and the scalar inference parity check.

```sh
.venv/bin/python experiments/static_graphs/export.py --verify-only
```

The export batches the existing predictors. Its feature-only adapter uses the
existing repair routines while omitting unused interface diagnostics. Before
exporting, clean, individual, and combined attack forecasts are checked against
the product's ordinary per-checkpoint inference. Unavailable forecasts remain
gaps with disclosed coverage; forecasts are never replaced with fabricated data.

Serve the updated frontend with the normal local replay server. The saved graph
bundle also works from an ordinary static HTTP server and does not need any
monthly-analysis API jobs. An initial file download is still required; changing
selections after that uses only data already in memory.

## Full-cohort checkpoint summaries

The dashboard's **Full March results** mode reads `Frontend/tracking/data/full-month.json`.
It uses all 5,382 archived five-minute decisions across 243 approaches and 219
vessels. It preserves frozen models, reference crossings and receipt-time
filtering. Additional input repairs use the current serving policy. No synthetic
performance adjustments are included in this mode.

From `Data_Science`:

```sh
python experiments/static_graphs/full_month.py --workers 4
```

The default build evaluates clean reports, the eight individual quarter-strength
faults, and the all-eight combination. Pass `--masks 0,1,65` to evaluate particular
combinations. A missing full-cohort combination is shown as unavailable; the UI
never substitutes the six-approach sample. That original sample remains in its
own data mode. The separate Simulation mode is explicitly hypothetical.

The build verifies 108 forecasts against scalar serving inference, caches the
actual checkpoint predictions under `artifacts/full_graphs/<signature>/`, and
publishes each finished scenario atomically. Repeating the command reuses verified
input/code-signature caches. Faults begin at the March 15 cutover. A matching clean
forecast is retained for each vessel and clock.

Daily errors average within approach before averaging across approaches. The
optional weekly view averages those daily means. Convergence uses disjoint
five-minute final-hour bins, averaging absolute errors within approach; a zero
minute endpoint needs an actual checkpoint at the crossing and is otherwise a
gap. Stability retains only complete seven-offset sequences on the same cohort.
Counts and exclusions are saved in the bundle and shown below the graphs. Source,
model, configuration and implementation hashes are included for reproducibility.

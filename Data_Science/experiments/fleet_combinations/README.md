# Fleet combination screen

Exploratory evaluation of the current fleet controls and additional Antidote strategies. This does not train models or alter product policy.

Start with [findings](results/representative_seed_4201/FINDINGS.md) and the [complete table](results/representative_seed_4201/REPORT.md).

From `Data_Science`, using the existing pinned `.venv`:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/fleet_combinations/run.py --workers 4
.venv/bin/python experiments/fleet_combinations/validate.py experiments/fleet_combinations/results/representative_seed_4201
```

`--clocks all` uses all original decision clocks. `--seed N` changes the fault realization. Checkpoints are isolated by protocol hashes under ignored model artifacts. The runner preserves its executed source with each result. Raw CSV predictions/audits are local ignored files; summaries, protocol and findings remain reviewable in the repository.

`plot.py <result-directory>` generates the static PNG/SVG from saved summaries only and requires optional Matplotlib. Plotting is separate from the pinned inference environment.

Scope: 39 settings (original, eight singles, 28 pairs, two stacks), one seed per run, no verified position anchors, under-reporting speed drift. Report masking is correlated between equal-severity missing-field and position-jump controls, as implemented by the current demo. The selected April period has already been examined; results are exploratory and do not establish new holdout performance.

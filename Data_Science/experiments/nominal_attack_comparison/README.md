# Frozen nominal A/B/C attack comparison

This evaluates the existing eight report-level attack families against the
2023-trained A, B and nominal-only C on March 1–31, 2024. Both speed-drift
directions give nine attacked settings, each sharing the original 5,382
decisions / 243 approaches. Faults are **Simulated disruption**. No additional
mitigation, model fitting or recalibration occurs; C retains its existing guard.

Use the existing Python 3.11 dependencies; no new packages or environment
variables are required. From this worktree's `Data_Science` directory:

```powershell
& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -u -m experiments.nominal_attack_comparison.run
```

The default uses four worker processes and attack seed 4201. Original reports
and source models are retained. Each completed case has a hashed checkpoint;
the same command resumes verified matching cases. A source, model, attack or
relevant implementation change requires a new `--output` directory. Do not run
two jobs against the same output directory. A temporary Windows sleep request
applies only during execution and is cleared on exit.

Live progress is under `artifacts/data_eval/attack_comparison/status.json` and
`progress.log`. Completed cases also have predictions, a summary, paired
uncertainty and a separate raw modification audit. The overall report is
written only when all requested cases succeed.

For a small representative execution, use a separate output directory:

```powershell
& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -u -m experiments.nominal_attack_comparison.run --output artifacts/data_eval/attack_smoke_example --limit-approaches 2 --workers 2
```

The smoke run exercised every attack family successfully, checking source
immutability, identical scheduled decisions and finite supported forecasts.
The report distinguishes error on available forecasts from coverage and
compares attacked/original MAE on matched supported records. The first pass
uses one representative severity per family rather than a severity/seed sweep.

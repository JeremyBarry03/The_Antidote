# 220-day 2023 training and March 2024 evaluation

This versioned run uses the existing A (quadratic ridge), B (ordinary XGBoost)
and C (degradation-aware XGBoost) implementations. Output is isolated under
`Data_Science/artifacts/data_eval/`; earlier models are retained.

The `data_eval` branch is checked out at
`C:\Users\jerem\Downloads\the_antidote_data_eval`. The original checkout is used
by another session. This worktree's ignored `data/` directory is a junction to
the original checkout's `data/`, so the existing March source is shared without
duplicating or modifying it.

## Source compatibility

The supplied `C:\Users\jerem\Downloads\AISVesselTracks2023.zip` was fully extracted
to `C:\Users\jerem\Downloads\AISVesselTracks2023\AISVesselTracks2023.gpkg`.
The extracted file is 15,463,698,432 bytes; ZIP CRC32 `c1df7c75` was verified.
It contains 7,596,268 MULTILINESTRING track segments with no Z/M coordinates.
Its fields include MMSI, VesselType, TrackStartTime and TrackEndTime, but omit
individual report timestamps, SOG and COG. Untimed vertices cannot reproduce
the existing observation histories or crossing brackets. See
[compatibility_report.json](compatibility_report.json).

The user approved acquiring official 2023 point data instead. Sources are the
[NOAA 2023 daily AIS broadcast-point CSV archives](https://www.coast.noaa.gov/htdata/CMSP/AISDataHandler/2023/index.html).
The downloader retains the same bounding box as the existing Hampton Roads
acquisition: longitude [-76.6, -75.8], latitude [36.7, 37.2]. It preserves
reported values, renames NOAA headers into exactly the 17 March column names,
validates each selected row's date, and retains daily hashes and provenance.
No interpolated or synthetic observations are added during acquisition.

The parser uses explicit standard CSV quoting. Structurally malformed source
rows are excluded and preserved with line numbers and reasons in daily
`*.rejects.csv` logs. Their counts and log hashes enter the source manifest and
final report. These are national source-file counts, not necessarily Hampton
Roads omissions. No fields are shifted or invented to repair malformed rows.

The current budget is **220 days total**, January 1–August 8, 2023. National ZIPs
and extracted CSVs are temporary; only regional subsets and manifests are retained. Allow
space for the regional CSVs, assembled inputs and several concurrent temporary
daily files. Check free disk space before starting another acquisition.

## Calendar

| UTC period | Purpose |
|---|---|
| January 1–June 29, 2023 (180 days) | Model fitting and fitted preprocessing |
| June 30–July 19, 2023 (20 days) | Hyperparameter selection / early stopping |
| July 20–29, 2023 (10 days) | Internal baseline test; exploratory C partition |
| July 30–August 8, 2023 (10 days) | Independent calibration |
| March 1–31, 2024 | Final A/B/C evaluation |

April 2024 data are not read by this run. Whole approaches and crossing brackets
must stay inside their calendar partition. The existing cargo/tanker cohort,
analytical gate, feature/target clocks, equal-approach weighting and candidate
grids are retained. Source dates and both configuration files are hashed.

March appeared in earlier project experiments, so it is held out from these
new fits but is not a previously unseen project dataset. Results describe
qualifying observed analytical-gate crossings, not verified berth arrivals.

C retains its established four-condition training mixture. Injected delays and
position offsets are **Simulated disruption**. The report leads with original
March observations and reports the simulations separately. Three auxiliary
fitted controls remain internal; the primary comparison is A, B and C.

## Setup and run

Use Python 3.11 and the existing `requirements-dev.txt`. No environment variables,
API keys, GPU or external model service are required. Internet is required for
NOAA downloads. Run these commands from this worktree's `Data_Science` folder:

```powershell
$python = 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe'
& $python -m pip install -r requirements-dev.txt
& $python -u -m experiments.data_eval.run --acquire --workers 8
```

This one command acquires data, prepares examples, trains models, calibrates on
original July 30–August 8 reports and evaluates A/B/C on original March reports. It
writes a persistent `artifacts/data_eval/pipeline.log` and `job_status.json`.
The process can run unattended. On Windows it requests that automatic system
sleep be suspended only while the job is active; the display may turn off.
Keep the computer powered and connected to the internet until `job_status.json`
reports `complete` or `failed`. Closing a laptop lid may still suspend it.

Acquisition resumes verified daily subsets. Transient download errors receive
bounded retries. Unexpected schemas, empty days and invalid dates fail clearly.
Do not run two acquisitions against the same output directory simultaneously.

The runner checks all 220 days, source hashes and March's columns/date range
before preparing inputs. It invokes the existing model CLIs in dependency order
and records completed stages in `artifacts/data_eval/run_manifest.json`.
Restart the same command after resolving a failure; completed stages are reused
when source/configuration/code signatures match. A changed signature requires
review rather than silently mixing artifacts from different experiments.

Preparation streams complete vessel histories through a disk-backed SQL sort
with a 512 MB SQL memory limit and an isolated temporary spill directory. Acquisition
uses 256 MB per worker. This avoids loading the entire source into pandas.
Both ISO `T` timestamps from 2023 and space-separated March timestamps are parsed
without changing their observation times. Deduplication and conflicting-key
exclusion operate on complete vessel histories, including across fetch batches.

Model paths after successful completion:

- A: `artifacts/data_eval/baselines/quadratic/model.joblib`
- B: `artifacts/data_eval/baselines/xgboost/model.joblib`
- C: `artifacts/data_eval/optimized/models/C.joblib`
- Report: `experiments/data_eval/RESULTS.md`
- Primary metrics: `artifacts/data_eval/abc_march_summary.csv`
- Detailed evaluation: `artifacts/data_eval/optimized/results/evaluation_nominal/`

The final report is generated only after training, calibration and evaluation
succeed. It reports approach-weighted MAE, forecast median/P95 absolute errors,
coverage, cohort counts and the location of per-vessel/paired uncertainty outputs.
Evaluation uses one deterministic nominal replay, without additional stress
sweeps. C's training augmentation and auxiliary fitted controls are retained.

## Verification

```powershell
& $python -m pytest tests -q
& $python -m compileall -q eta_baselines Optimized_Model experiments/data_eval
```

The source acquisition was tested on January 1, 2023: 144,473 regional reports,
matching all 17 March column names. Tests also cover preservation of original
values/CSV quoting, wrong-day rejection, verified resume, changed-file rejection
and refusing track endpoints as substitutes for report timestamps.

Validation before the full run: **556 tests passed**, including an end-to-end
A/B/C fit, separate calibration and original March evaluation on a
small test fixture. Streamed preparation also reproduced all **5,382 frozen
March examples**, labels, partition counts and source audits without model
fitting. Live acquisition verified both the apostrophe-name case (March 28)
and an extra-field source-row case (April 7), preserving the latter in its
national reject log. These checks are not performance results for the requested fit.

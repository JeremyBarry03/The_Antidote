# Existing attacks: 2023 nominal A/B/C on full March 2024

All attacked cases below are **Simulated disruption** of the original March reports. A/B/C remain frozen, with C explicitly using `C_nominal.joblib`. No additional mitigation or recalibration is applied. C retains its built-in input guard.

Each setting schedules 5382 decisions across 243 approaches. All March 1–31 records eligible for the existing gate/cohort are retained. Arrival labels and decision clocks come from the original reports, not the attack.

## First-pass results

| Setting | A MAE / MdAE | B MAE / MdAE | C MAE / MdAE | A/B/C coverage |
|---|---:|---:|---:|---:|
| original | 7.019 / 3.459 | 6.643 / 3.164 | 6.610 / 3.097 | 100.0% / 100.0% / 100.0% |
| missing_speed | 9.708 / 4.370 | 7.135 / 3.555 | 7.082 / 3.584 | 100.0% / 100.0% / 100.0% |
| missing_course | 7.235 / 3.591 | 6.978 / 3.206 | 6.717 / 3.159 | 100.0% / 100.0% / 100.0% |
| missing_vessel_class | 7.055 / 3.482 | 6.648 / 3.166 | 6.613 / 3.097 | 100.0% / 100.0% / 100.0% |
| reporting_gap_15 | 7.093 / 3.456 | 6.650 / 3.105 | 6.663 / 3.129 | 100.0% / 100.0% / 100.0% |
| speed_drift_under | 12.460 / 10.340 | 10.107 / 7.351 | 7.978 / 4.433 | 100.0% / 100.0% / 100.0% |
| speed_drift_over | 8.774 / 5.417 | 8.710 / 5.212 | 8.100 / 4.641 | 100.0% / 100.0% / 100.0% |
| sensor_noise_medium | 8.039 / 4.671 | 7.080 / 3.559 | 7.148 / 3.672 | 100.0% / 100.0% / 100.0% |
| position_jump | 8.057 / 4.879 | 7.089 / 3.902 | 8.163 / 4.859 | 100.0% / 100.0% / 100.0% |
| location_drift | 7.551 / 4.368 | 7.447 / 4.462 | 7.472 / 4.479 | 100.0% / 100.0% / 100.0% |

Errors are minutes. MAE gives each approach equal weight; MdAE and P95 describe individual available forecasts. `summary.csv` also contains P95, coverage and MAE changes against original forecasts on the same supported decisions. Unavailable forecasts remain in coverage denominators.

## Settings and limits

```json
{
  "missing_speed": {
    "affected_fraction": 0.25,
    "seed": 4201,
    "target_mmsi": null
  },
  "missing_course": {
    "affected_fraction": 0.25,
    "seed": 4201,
    "target_mmsi": null
  },
  "missing_vessel_class": {
    "affected_fraction": 0.25,
    "seed": 4201,
    "target_mmsi": null,
    "selection_unit": "report"
  },
  "reporting_gap_15": {
    "start_offset_after_first_decision_minutes": 12,
    "duration_minutes": 15
  },
  "speed_drift_under": {
    "drift_rate_knots_per_minute": -0.1,
    "rate_variation_fraction": 0.25,
    "variation_period_minutes": 20.0,
    "maximum_bias_knots": 3.0,
    "seed": 4201,
    "target_mmsi": null,
    "start_time": null
  },
  "speed_drift_over": {
    "drift_rate_knots_per_minute": 0.1,
    "rate_variation_fraction": 0.25,
    "variation_period_minutes": 20.0,
    "maximum_bias_knots": 3.0,
    "seed": 4201,
    "target_mmsi": null,
    "start_time": null
  },
  "sensor_noise_medium": {
    "sog_sigma_knots": 1.0,
    "cog_sigma_degrees": 5.0,
    "affected_fraction": 1.0,
    "seed": 4201,
    "target_mmsi": null
  },
  "position_jump": {
    "affected_fraction": 0.25,
    "seed": 4201,
    "target_mmsi": null,
    "displacement_meters": 2000.0,
    "displacement_std_meters": 200.0,
    "bearing_degrees": null,
    "start_time": null,
    "end_time": null
  },
  "location_drift": {
    "drift_rate_meters_per_minute": 20.0,
    "maximum_bias_meters": 1852.0,
    "rate_variation_fraction": 0.25,
    "variation_period_minutes": 20.0,
    "bearing_degrees": null,
    "seed": 4201,
    "target_mmsi": null,
    "start_time": null
  }
}
```

Reporting outage starts 12 minutes after each approach's first scheduled decision and lasts 15 minutes, independently of arrival time and prediction errors. Unexposed early/short approaches remain in the full-cohort scores. Raw modification logs are separate from predictor features.

One fixed attack seed (4201) and one representative setting per attack family are a first pass, not an exhaustive severity/seed study. Both speed-drift directions are included. Attack settings are reused from existing configs/presets, not tuned against March performance. No real-world fault prevalence is inferred.

The models were fitted/tuned only on 2023. C's nominal-only variant was selected after inspecting original March performance, so variant selection is post hoc. Predictions concern analytical-gate crossings, not verified docking.

## Reproduce

From this worktree's `Data_Science` directory:

```powershell
& 'C:/Users/jerem/AppData/Local/Programs/Python/Python311/python.exe' -u -m experiments.nominal_attack_comparison.run
```

Outputs, progress and hashed per-case checkpoints: `artifacts\data_eval\attack_comparison`. Models, source hashes, settings and implementation hashes are recorded in `protocol.json`. This command resumes matching verified cases.

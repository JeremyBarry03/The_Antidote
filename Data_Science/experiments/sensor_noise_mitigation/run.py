"""Exploratory replacement-versus-blending study; never edits production models.

Run from Data_Science: .venv/bin/python experiments/sensor_noise_mitigation/run.py
This explicitly uses the available v1 C bundle, not the absent vessel-class v2.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import SensorDeteriorationAttack, SensorDeteriorationConfig
from attacks.sensorDeteriorationAttack import SEVERITY_LEVELS
from eta_baselines.dataset import file_digest
from mitigation.sensor_noise_mitigation import SensorNoiseMitigation
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.features import OptimizedFeatures, RICH_COLUMNS
from Optimized_Model.model import inference_implementation
from Optimized_Model.sensor_deterioration import mitigated_noise_view
from Optimized_Model.views import view_row

SEEDS = (4201, 4202, 4203)
METHODS = ("unmitigated", "replacement", "half_blend", "development_blend")


def angle(left, right):
    return (np.asarray(left) - np.asarray(right) + 180) % 360 - 180


def settings():
    yield "original", SensorDeteriorationConfig(0, 0, seed=42)
    for severity in SEVERITY_LEVELS:
        for seed in SEEDS:
            yield severity, SensorDeteriorationConfig.from_severity(severity, seed=seed)


def references(task):
    identity, history, config = task
    history = history.sort_values("time", kind="stable").reset_index(drop=True)
    if history.time.duplicated().any():
        raise ValueError("Geometry caching requires unique observation times.")
    # Sensor values are neutral placeholders. Only positions/times and observable
    # missingness determine reference support; no hidden original values are used.
    geometry = history.copy(deep=True)
    geometry["sog"] = np.where(history.sog.notna(), 10., np.nan)
    geometry["cog"] = np.where(history.cog.notna(), 0., np.nan)
    strategy = SensorNoiseMitigation(config.baseline.gate)
    rows = []
    for index, at in enumerate(geometry.time):
        result = strategy.apply(geometry.iloc[:index + 1], at)
        rows.append(dict(reference_speed=result.estimated_speed_knots,
                         reference_course=result.estimated_course_degrees,
                         allowed=result.can_predict, position_supported=result.position_supported,
                         reference_status=result.status.value, reason="|".join(result.reasons)))
    return identity, pd.DataFrame(rows)


def repair_arrays(reports, reference, alpha_speed, alpha_course):
    speed = reports.sog.to_numpy(dtype=float)
    course = reports.cog.to_numpy(dtype=float)
    speed_delta = reference.reference_speed.to_numpy(dtype=float) - speed
    course_delta = angle(reference.reference_course, course)
    speed_flag = reference.allowed.to_numpy() & (np.abs(speed_delta) > 2.)
    course_flag = reference.allowed.to_numpy() & (np.abs(course_delta) > 15.)
    fixed_speed, fixed_course = speed.copy(), course.copy()
    fixed_speed[speed_flag] += alpha_speed * speed_delta[speed_flag]
    fixed_course[course_flag] = (course[course_flag] + alpha_course * course_delta[course_flag]) % 360
    return fixed_speed, fixed_course, speed_flag, course_flag


def fit_blend(cases, reference_map):
    # Minimize approach-weighted squared sensor deviation from the original AIS
    # reference on March development data only. This is not ETA optimization or
    # an adaptive Kalman filter, and it assumes no known attack severity at use.
    sums = {field: np.zeros(2) for field in ("speed", "course")}
    counts = dict(speed=0, course=0)
    for identity, history, _ in cases:
        ref = reference_map[identity]
        for _, attack_config in settings():
            reports = SensorDeteriorationAttack(attack_config).apply(history).reports
            _, _, speed_flag, course_flag = repair_arrays(reports, ref, 1., 1.)
            data = {
                "speed": (reports.sog.to_numpy(), history.sog.to_numpy(), ref.reference_speed.to_numpy(), speed_flag),
                "course": (reports.cog.to_numpy(), history.cog.to_numpy(), ref.reference_course.to_numpy(), course_flag),
            }
            for field, (observed, original, estimate, flag) in data.items():
                delta = estimate - observed if field == "speed" else angle(estimate, observed)
                target = original - observed if field == "speed" else angle(original, observed)
                valid = flag & np.isfinite(delta) & np.isfinite(target)
                # Each approach has equal weight across all its reports; seeds
                # and scenarios are predeclared and equally represented.
                weight = 1. / len(history)
                sums[field] += weight * np.array([np.sum(delta[valid] * target[valid]), np.sum(delta[valid] ** 2)])
                counts[field] += int(valid.sum())
    alphas = {field: float(np.clip(values[0] / values[1], 0, 1)) if values[1] else 0.
              for field, values in sums.items()}
    return dict(alpha_speed=alphas["speed"], alpha_course=alphas["course"],
                flagged_development_observations=counts, development_approaches=len(cases),
                interpretation="Fraction of the difference moved toward the position estimate, fixed before April scoring")


def evaluate_case(task):
    identity, history, decisions, reference, config, blend = task
    extractor = OptimizedFeatures(config.baseline, config.guard)
    strategy = SensorNoiseMitigation(config.baseline.gate)
    feature_rows, sensor_rows, validations = [], [], []
    for severity, attack_config in settings():
        stream = SensorDeteriorationAttack(attack_config).apply(history)
        reports = stream.reports.reset_index(drop=True)
        derived, flags = {}, None
        for method, a_speed, a_course in (
            ("unmitigated", 0., 0.), ("replacement", 1., 1.),
            ("half_blend", .5, .5),
            ("development_blend", blend["alpha_speed"], blend["alpha_course"]),
        ):
            speed, course, sf, cf = repair_arrays(reports, reference, a_speed, a_course)
            derived[method] = reports.assign(sog=speed, cog=course)
            flags = (sf, cf)
            speed_error = speed - history.sog.to_numpy()
            course_error = angle(course, history.cog.to_numpy())
            for field, errors in (("speed", speed_error), ("course", course_error)):
                valid = np.isfinite(errors)
                sensor_rows.append(dict(approach_id=identity, mmsi=str(history.mmsi.iloc[0]),
                    severity=severity, seed=attack_config.seed, method=method, field=field,
                    count=int(valid.sum()), mse=float(np.mean(errors[valid] ** 2)),
                    mae=float(np.mean(np.abs(errors[valid]))),
                    allowed_share=float(reference.allowed.mean()),
                    flagged_share=float((sf | cf).mean())))
        # Every row reconstructed using only its own received prefix. Confirm the
        # cached geometry agrees with the actual strategy at the strongest noise.
        if severity == "extreme" and attack_config.seed == SEEDS[0]:
            actual, _ = strategy.reconstruct_reports(reports, reports.time.max())
            if not np.allclose(actual[["sog", "cog"]], derived["replacement"][["sog", "cog"]], equal_nan=True):
                raise ValueError(f"Causal reconstruction mismatch in {identity}.")
            validations.append(dict(approach_id=identity, check="full_history_reconstruction", passed=True))
        for decision_index, (_, decision) in enumerate(decisions.iterrows()):
            mask = reports.time.le(decision.decision_time) & reports.delivered_time.le(decision.decision_time)
            available = reports.loc[mask]
            base = view_row(available, decision, extractor)
            latest_index = int(np.flatnonzero(mask)[-1])
            current_allowed = bool(reference.allowed.iloc[latest_index]) and (
                decision.decision_time - reports.time.iloc[latest_index]).total_seconds() <= 300
            window_start = available.time.max() - pd.Timedelta(minutes=extractor.baseline.features.history_minutes)
            in_window = mask & reports.time.ge(window_start)
            repaired_count = int(((flags[0] | flags[1]) & in_window).sum())
            method_rows = {}
            for method in METHODS:
                row = {**decision.to_dict(), **base, "method": method, "severity": severity,
                       "seed": attack_config.seed, "mitigation_supported": current_allowed,
                       "repaired_report_count": 0, "mitigation_applied": False}
                if method != "unmitigated" and current_allowed and base["supported"]:
                    corrected, _ = extractor.snapshot(derived[method].loc[mask], decision.decision_time, guarded=True)
                    if not corrected.empty and corrected.iloc[0].observation_time == base["observation_time"]:
                        for column in RICH_COLUMNS:
                            row[column] = corrected.iloc[0][column]
                        row.update(repaired_report_count=repaired_count, mitigation_applied=repaired_count > 0)
                method_rows[method] = row
                feature_rows.append(row)
            if severity == "high" and attack_config.seed == SEEDS[0] and decision_index == len(decisions) - 1:
                exact, meta = mitigated_noise_view(available, decision, extractor, strategy)
                actual = method_rows["replacement"]
                columns = [*RICH_COLUMNS, "observation_time", "supported"]
                for column in columns:
                    left, right = exact[column], actual[column]
                    equal = (pd.isna(left) and pd.isna(right)) or left == right
                    if not equal and isinstance(left, (int, float, np.number)):
                        equal = np.isclose(left, right, equal_nan=True)
                    if not equal:
                        raise ValueError(f"Serving adapter mismatch {identity}: {column}: {left} vs {right}")
                if meta["applied"] != actual["mitigation_applied"]:
                    raise ValueError("Serving intervention count mismatch.")
                validations.append(dict(approach_id=identity, check="serving_adapter", passed=True))
    return pd.DataFrame(feature_rows), pd.DataFrame(sensor_rows), validations


def summarize(predictions):
    rows = []
    for (severity, method), group in predictions.groupby(["severity", "method"], sort=False):
        valid = group.loc[group.available].copy()
        valid["ae"] = valid.error_minutes.abs()
        per = valid.groupby("approach_id").ae.mean()
        rows.append(dict(severity=severity, method=method, scheduled=len(group), available=len(valid),
            coverage=len(valid) / len(group), approaches=group.approach_id.nunique(),
            mae_minutes=per.mean(), mdae_minutes=valid.ae.median(), p95_minutes=valid.ae.quantile(.95),
            mse_minutes_squared=float((valid.error_minutes ** 2).mean()),
            mitigation_supported_share=float(group.mitigation_supported.mean()),
            intervention_share=float(group.mitigation_applied.mean())))
    return pd.DataFrame(rows)


def uncertainty(predictions):
    pairs = predictions.pivot(index=["severity", "approach_id", "mmsi", "decision_id", "seed"],
                              columns="method", values="error_minutes").reset_index()
    rows = []
    for severity, group in pairs.groupby("severity", sort=False):
        comparisons = [(method, "unmitigated") for method in METHODS[1:]]
        comparisons += [("half_blend", "replacement"), ("development_blend", "replacement")]
        for method, reference_method in comparisons:
            paired = group.dropna(subset=[reference_method, method]).copy()
            paired["delta"] = paired[method].abs() - paired[reference_method].abs()
            per = paired.groupby(["mmsi", "approach_id"]).delta.mean().reset_index()
            clusters = [g.delta.to_numpy() for _, g in per.groupby("mmsi")]
            rng = np.random.default_rng(20261022)
            draws = [np.concatenate([clusters[i] for i in rng.integers(len(clusters), size=len(clusters))]).mean()
                     for _ in range(2000)]
            low, high = np.quantile(draws, [.025, .975])
            rows.append(dict(severity=severity, method=method, reference_method=reference_method, delta_mae_minutes=per.delta.mean(),
                             low95=low, high95=high, approach_win_share=float(per.delta.lt(0).mean())))
    return pd.DataFrame(rows)


def render_report(summary, sensor, intervals, protocol):
    labels = {"original": "No added noise", "low": "Low", "medium": "Medium", "high": "High", "extreme": "Extreme"}
    order = list(labels)
    table = summary.pivot(index="severity", columns="method", values="mae_minutes")
    lines = ["# Sensor noise mitigation: replacement versus blending", "",
        "**Exploratory frozen v1 C model. These are not vessel-class v2 demo results.**", "",
        "The current v2 bundles are absent locally. The available v1 bundle hash was verified, and all 2,402 nominal predictions were reproduced against the saved v1 evaluation before reporting. No model was retrained, no review policy recalibrated, and no production strategy changed.", "",
        "## ETA accuracy", "",
        "MAE in minutes to the analytical crossing, with equal approach weights. Lower is better. Every method has the same scheduled decisions; unsupported mitigation leaves the existing forecast inputs unchanged.", "",
        "| Noise | No additional mitigation | Current replacement | 50/50 blend | Development blend |",
        "|---|---:|---:|---:|---:|"]
    for severity in order:
        row = table.loc[severity]
        lines.append(f"| {labels[severity]} | " + " | ".join(f"{row[method]:.4f}" for method in METHODS) + " |")
    lines += ["", "## Coverage and tail errors", "",
        "Output coverage is separate from permission to reconstruct. Declining a repair does not remove that forecast from accuracy metrics.", "",
        "| Noise | Method | Output coverage | Mitigation supported | Intervention share | Median error (min) | P95 error (min) | MSE (min²) |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for severity in order:
        for row in summary.loc[summary.severity.eq(severity)].itertuples():
            lines.append(f"| {labels[severity]} | {row.method} | {row.coverage:.2%} | {row.mitigation_supported_share:.2%} | {row.intervention_share:.2%} | {row.mdae_minutes:.4f} | {row.p95_minutes:.4f} | {row.mse_minutes_squared:.4f} |")
    lines += ["", "## Paired uncertainty", "",
        "Differences are method MAE minus reference MAE, in minutes. Negative favors the method. Intervals use 2,000 paired vessel-cluster bootstrap draws across 110 vessels; they describe this selected cohort, not universal reliability.", "",
        "| Noise | Method | Reference | MAE difference | 95% interval | Approach win share |",
        "|---|---|---|---:|---:|---:|"]
    for severity in order:
        for row in intervals.loc[intervals.severity.eq(severity)].itertuples():
            lines.append(f"| {labels[severity]} | {row.method} | {row.reference_method} | {row.delta_mae_minutes:+.4f} | [{row.low95:+.4f}, {row.high95:+.4f}] | {row.approach_win_share:.2%} |")
    lines += ["", "## Recovery of injected sensor corruption", "",
        "RMSE versus original AIS readings. These readings are evaluator references, not verified physical truth. Equal approach weights; speed is knots, course is shortest-arc degrees. All reports remain in this score, including ones that could not be repaired.", "",
        "| Noise | Field | No additional mitigation | Current replacement | 50/50 blend | Development blend |",
        "|---|---|---:|---:|---:|---:|"]
    for severity in order:
        for field in ("speed", "course"):
            data = sensor.loc[sensor.severity.eq(severity) & sensor.field.eq(field)].set_index("method")
            lines.append(f"| {labels[severity]} | {field} | " + " | ".join(f"{data.loc[method, 'rmse']:.4f}" for method in METHODS) + " |")
    blend = protocol["development_blend"]
    lines += ["", "## Design and interpretation", "",
        f"- March 20–24 development: {blend['development_approaches']} approaches. The fitted correction moves {blend['alpha_speed']:.4%} of a flagged speed discrepancy and {blend['alpha_course']:.4%} of a flagged course discrepancy toward the position estimate. These fixed fractions are frozen before April scoring; they are not an adaptive uncertainty model or a Kalman filter.",
        f"- April 8–21: {protocol['approaches']} approaches, {protocol['vessels']} vessels, {protocol['decisions']:,} decision clocks and {protocol['reports']:,} source reports. April has previously been inspected, so this is a follow-up analysis rather than a new protected holdout.",
        "- Both navigation fields receive independent Gaussian noise on 100% of eligible reports. Low sigma: 0.5 kn / 2°; medium: 1 kn / 5°; high: 2 kn / 10°; extreme: 4 kn / 20°. Three paired attack seeds per severity; clean input is evaluated once.",
        "- Every alternative changes only flagged fields after the same geometry checks. This is a comparison of the action taken after detection, not a comparison of new detectors or blending every observation. Small errors beneath the existing thresholds remain untouched.",
        "- Only already received position prefixes support reconstruction. Speed/course reference values and arrival labels are excluded from prediction inputs. Course blends follow the shortest compass arc.",
        "- Current C quality features continue to describe the raw received stream. Only its derived motion inputs are changed, matching the production adapter.",
        f"- Validation: {protocol['validation']['production_adapter_checks']} checks compare cached reconstruction or model features with the actual mitigation/serving code. Maximum nominal prediction difference: {protocol['validation']['max_prediction_difference_minutes']:.3g} minutes. Source and model hashes unchanged.",
        "- The clock and target represent an analytical gate crossing, not berth docking. Positions are unchanged by this attack and delivery is simulated as immediate. Coherent position errors, maneuvers and other attacks require separate evaluation.",
        "- A reduction in sensor-reference error does not establish an equal reduction in ETA error. Original reference readings are not a guarantee of physical accuracy, and a clean-input intervention is an intervention without injected noise, not proof of a false alarm in real operation.", "",
        "## Research", "",
        "[Duran-Martin et al. (ICML 2024)](https://arxiv.org/html/2405.05646v2) describe uncertainty-weighted Kalman updates and both smooth downweighting and threshold rejection for outliers. [Cole and Schamberg (2021)](https://arxiv.org/abs/2111.13254) evaluate dynamic AIS vessel-state filtering in simulation and field tests. [Wang et al.](https://arxiv.org/abs/2011.13353) study outliers with correlated measurements. These support the candidate mechanisms, not an accuracy claim for this implementation.", "",
        "Reproduce from Data_Science: `.venv/bin/python experiments/sensor_noise_mitigation/run.py --workers 4`. The script preserves source data and model bundles. See protocol.json, eta_summary.csv, sensor_summary.csv, paired_intervals.csv and predictions.csv for details."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    started = time.perf_counter()
    output = HERE / "results"
    output.mkdir(parents=True, exist_ok=True)
    config = OptimizedConfig.load(SCIENCE / "Optimized_Model/config.json")
    dataset = load_replay(config)
    model_path = config.output_directory / "models/C.joblib"
    manifest = json.loads(model_path.with_name("C_manifest.json").read_text())
    if manifest["model_sha256"] != file_digest(model_path):
        raise ValueError("Available v1 bundle does not match its saved hash.")
    current_implementation = inference_implementation()
    implementation_changes = {name: dict(trained=digest, current=current_implementation.get(name))
                              for name, digest in manifest["inference_implementation"].items()
                              if digest != current_implementation.get(name)}
    allowed_legacy_changes = {"eta_baselines/features.py", "eta_baselines/prediction.py"}
    if set(implementation_changes) - allowed_legacy_changes:
        raise ValueError("Legacy experiment requires a new compatibility review for other inference changes.")
    protected = {str(path): file_digest(path) for path in [model_path, config.baseline.input_csv, config.later_csv]}
    eval_decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    dev_decisions = dataset.partition("validation").sort_values(["approach_id", "decision_time"])
    make_cases = lambda frame: [(identity, dataset.histories[identity].sort_values("time", kind="stable").reset_index(drop=True), group)
                               for identity, group in frame.groupby("approach_id", sort=False)]
    dev_cases, eval_cases = make_cases(dev_decisions), make_cases(eval_decisions)
    if set(dev_decisions.approach_id) & set(eval_decisions.approach_id):
        raise ValueError("Development/evaluation approaches overlap.")
    cache_path = output / "position_references.joblib"
    reference_signature = {"replay_hash": file_digest(config.output_directory / "replay_dataset.joblib"),
                           "strategy_hash": file_digest(SCIENCE / "mitigation/sensor_noise_mitigation/sensor_noise_mitigation.py")}
    if cache_path.exists() and joblib.load(cache_path)[0] == reference_signature:
        reference_map = joblib.load(cache_path)[1]
    else:
        reference_map = {}
        tasks = [(identity, history, config) for identity, history, _ in dev_cases + eval_cases]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for index, (identity, frame) in enumerate(pool.map(references, tasks)):
                reference_map[identity] = frame
                if (index + 1) % 20 == 0:
                    print(f"Position reference: {index + 1}/{len(tasks)} approaches", flush=True)
        joblib.dump((reference_signature, reference_map), cache_path)
    blend = fit_blend(dev_cases, reference_map)
    (output / "blend_settings.json").write_text(json.dumps(blend, indent=2))
    print("Development blend fixed:", blend, flush=True)
    tasks = [(identity, history, decisions, reference_map[identity], config, blend)
             for identity, history, decisions in eval_cases]
    views, sensor, checks = [], [], []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, (features, readings, validation) in enumerate(pool.map(evaluate_case, tasks)):
            views.append(features)
            sensor.append(readings)
            checks.extend(validation)
            if (index + 1) % 8 == 0:
                print(f"ETA features: {index + 1}/{len(tasks)} approaches; {time.perf_counter() - started:.0f}s", flush=True)
    views = pd.concat(views, ignore_index=True)
    predictor = joblib.load(model_path)
    views["available"] = views.supported
    views["error_minutes"] = np.nan
    supported = views.supported.to_numpy(dtype=bool)
    forecasts = predictor.predict(views.loc[supported])
    views.loc[supported, "error_minutes"] = forecasts.error_minutes.to_numpy()
    # Verify all 2,402 nominal forecasts against the historical v1 run before
    # reporting. This is a deliberate legacy experiment, not compatibility bypass
    # in the demo service or a claim about the missing v2 model.
    saved = pd.read_csv(config.output_directory / "results/evaluation_primary/predictions.csv")
    saved = saved.loc[saved.system.eq("C") & saved.scenario.eq("nominal")].drop_duplicates("decision_id")
    nominal = views.loc[views.severity.eq("original") & views.method.eq("unmitigated")]
    matched = nominal.merge(saved[["decision_id", "error_minutes"]], on="decision_id", suffixes=("", "_saved"), validate="one_to_one")
    max_delta = float(np.max(np.abs(matched.error_minutes - matched.error_minutes_saved)))
    if len(matched) != len(eval_decisions) or max_delta > 1e-5:
        raise ValueError(f"Legacy baseline not reproduced: {len(matched)} rows; max difference {max_delta}")
    columns = ["approach_id", "mmsi", "decision_id", "decision_time", "arrival_time", "method", "severity", "seed",
               "available", "error_minutes", "mitigation_supported", "mitigation_applied", "repaired_report_count"]
    predictions = views[columns]
    predictions.to_csv(output / "predictions.csv", index=False)
    summarize(predictions).to_csv(output / "eta_summary.csv", index=False)
    intervals = uncertainty(predictions)
    intervals.to_csv(output / "paired_intervals.csv", index=False)
    sensor = pd.concat(sensor, ignore_index=True)
    sensor.to_csv(output / "sensor_by_approach.csv", index=False)
    sensor_summary = sensor.groupby(["severity", "method", "field"], sort=False).agg(
        mse=("mse", "mean"), mae=("mae", "mean"), allowed_share=("allowed_share", "mean"),
        flagged_share=("flagged_share", "mean")) .reset_index()
    sensor_summary["rmse"] = np.sqrt(sensor_summary.mse)
    sensor_summary.to_csv(output / "sensor_summary.csv", index=False)
    pd.DataFrame(checks).to_csv(output / "adapter_validation.csv", index=False)
    if any(file_digest(Path(path)) != digest for path, digest in protected.items()):
        raise ValueError("Protected source or model changed.")
    protocol = dict(status="exploratory_legacy_v1", current_v2_artifacts_available=False,
        model_version="march_gate_v1 C", model_hash=file_digest(model_path),
        source_and_model_hashes=protected, legacy_implementation_changes=implementation_changes,
        approaches=len(eval_cases), vessels=int(eval_decisions.mmsi.nunique()), decisions=len(eval_decisions),
        reports=sum(len(history) for _, history, _ in eval_cases), seeds=SEEDS,
        severity_sigmas=dict(SEVERITY_LEVELS), affected_fraction=1.,
        mitigation_config=asdict(SensorNoiseMitigation(config.baseline.gate).config),
        methods=list(METHODS), blending_scope="Flagged fields only, preserving all existing geometry checks and decision gates",
        development_blend=blend, eta_mae="Approach-weighted mean absolute error; seeds averaged within approaches",
        sensor_errors="Deviation from uncorrupted AIS reference, approach weighted; not independent physical truth",
        course_blend="Interpolate along shortest compass arc; never arithmetic-average compass headings",
        geometry_cache="Only causal position prefixes and observable validity; no original navigation values",
        validation=dict(all_legacy_nominal_predictions_reproduced=True, max_prediction_difference_minutes=max_delta,
                        production_adapter_checks=len(checks), protected_hashes_unchanged=True),
        model_training="None", calibration="None", limits=[
            "v1 results cannot be attributed to current vessel-class v2 model",
            "April has been inspected previously; this is not a fresh protected holdout",
            "Gate crossing reference, not docking; perfect event-time delivery is assumed",
            "Fixed development blend is not an uncertainty-adaptive or Kalman filter",
            "No source/model/production mitigation changes"], elapsed_seconds=time.perf_counter() - started)
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    (output / "REPORT.md").write_text(render_report(summarize(predictions), sensor_summary, intervals, protocol))
    print(json.dumps(protocol["validation"], indent=2), flush=True)
    print(summarize(predictions).to_string(index=False), flush=True)
    print(f"Finished in {time.perf_counter() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()

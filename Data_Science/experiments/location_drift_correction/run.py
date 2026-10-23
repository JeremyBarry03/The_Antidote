"""Conditional anchored location recovery and explicitly legacy-v1 ETA replay."""

from concurrent.futures import ProcessPoolExecutor, as_completed
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

from attacks import LocationDriftAttack, SensorDriftAttack, SensorDriftConfig
from attacks.positionJumpAttack.position_jump_attack import _distance
from eta_baselines.dataset import file_digest
from experiments.missing_speed_attack.run import metrics, paired_interval
from mitigation import LocationDriftMitigation, PositionAnchor
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay
from Optimized_Model.features import OptimizedFeatures, QUALITY_COLUMNS, RICH_COLUMNS
from Optimized_Model.model import inference_implementation

SCENARIOS = {"original": (0., False), "location": (0., True),
             "combined_under": (-.1, True), "combined_over": (.1, True)}


def anchors_from_reference(source):
    """Simulated extra trusted channel; explicitly unavailable in the actual product."""
    bins = ((source.time-source.time.iloc[0]) / pd.Timedelta(minutes=5)).astype(int)
    selected = source.loc[~bins.duplicated()]
    return [PositionAnchor(mmsi=str(row.mmsi), time=row.time, longitude=float(row.longitude),
                           latitude=float(row.latitude),
                           source="SIMULATED trusted fix from original AIS reference")
            for row in selected.itertuples()]


def available_anchor(anchors, measured, clock):
    candidates = [anchor for anchor in anchors if anchor.time <= measured and anchor.received_time <= clock]
    return candidates[-1] if candidates else None


def derive_incrementally(reports, anchors, strategy, maximum_clock):
    """Keep each repair fixed at delivery; never apply a later anchor retroactively."""
    derived = reports.loc[reports.time.le(maximum_clock)].copy(deep=True).reset_index(drop=True)
    for index, row in enumerate(derived.copy(deep=True).itertuples()):
        # Always inspect the raw prefix; corrections cannot become detector evidence.
        raw = reports.iloc[:index+1]
        anchor = available_anchor(anchors, row.time, row.delivered_time)
        result = strategy.apply(raw, row.delivered_time, anchor=anchor, navigation_trusted=True)
        if result.correction_applied:
            derived.at[index, "longitude"], derived.at[index, "latitude"] = result.longitude, result.latitude
    unchanged = [column for column in derived if column not in ("longitude", "latitude")]
    pd.testing.assert_frame_equal(derived[unchanged], reports.iloc[:len(derived)][unchanged])
    return derived


def error_meters(reference, longitude, latitude):
    return float(_distance(np.array([reference.latitude]), np.array([reference.longitude]),
                           np.array([latitude]), np.array([longitude]))[0])


def replay_case(task):
    identity, source, decisions, baseline, guard = task
    source = source.sort_values("time", kind="stable").reset_index(drop=True)
    reference = source.set_index("time")
    anchors = anchors_from_reference(source)
    strategy = LocationDriftMitigation(baseline.gate)
    extractor = OptimizedFeatures(baseline, guard)
    # Every official decision is at least ten minutes into its approach. Thus a
    # single initial fix has expired before any evaluated forecast.
    if not ((decisions.decision_time-source.time.iloc[0]) >
            pd.Timedelta(minutes=strategy.config.maximum_projection_minutes)).all():
        raise ValueError("Initial-anchor no-repair proof requires the existing decision schedule.")
    feature_rows, sensor_rows = [], []
    for scenario, (rate, location_fault) in SCENARIOS.items():
        reports = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=rate)).apply(source).reports
        if location_fault:
            reports = LocationDriftAttack().apply(reports).reports
        untouched = [column for column in source if column not in ("longitude", "latitude", "sog")]
        pd.testing.assert_frame_equal(reports[untouched], source[untouched])
        derived = derive_incrementally(reports, anchors, strategy, decisions.decision_time.max())
        modes = ["reported_only", "periodic_verified"]
        if scenario.startswith("combined"):
            modes.append("incorrect_navigation_trust")
        for decision in decisions.itertuples():
            clock = decision.decision_time
            available = reports.loc[reports.time.le(clock) & reports.delivered_time.le(clock)]
            last = available.iloc[-1]
            nominal = reference.loc[last.time]
            anchor = available_anchor(anchors, last.time, clock)
            original_frames = {view: extractor.snapshot(available, clock, guarded=view == "guarded")[0]
                               for view in ("raw", "guarded")}
            raw_diagnostics = strategy.apply(available, clock)
            projected = strategy.apply(available, clock, anchor=anchor, navigation_trusted=True)
            changed_frames = None
            if projected.correction_applied:
                received_derived = derived.loc[derived.time.le(clock) & derived.delivered_time.le(clock)]
                np.testing.assert_allclose(received_derived[["longitude", "latitude"]].iloc[-1],
                                           [projected.longitude, projected.latitude], atol=1e-10, rtol=0)
                changed_frames = {view: extractor.snapshot(received_derived, clock, guarded=view == "guarded")[0]
                                  for view in ("raw", "guarded")}
            for mode in modes:
                nav_trusted = mode == "incorrect_navigation_trust" or (
                    mode == "periodic_verified" and not scenario.startswith("combined"))
                current = projected if nav_trusted else raw_diagnostics
                if mode == "periodic_verified" and not nav_trusted:
                    # This is stipulated independent rejection of navigation trust,
                    # not an automatic fault-isolation capability of the detector.
                    current = strategy.apply(available, clock, anchor=anchor, navigation_trusted=False)
                used = nav_trusted and current.correction_applied
                sensor_rows.append(dict(approach_id=identity, mmsi=str(decision.mmsi),
                    decision_id=decision.decision_id, scenario=scenario, mode=mode,
                    decision_time=clock, observation_time=last.time,
                    correction_available=used, review_required=current.requires_review,
                    drift_flag=current.drift_detected, reasons=";".join(current.reasons),
                    anchor_time=anchor.time if mode != "reported_only" else pd.NaT,
                    anchor_age_minutes=float((clock-anchor.time)/pd.Timedelta(minutes=1)) if anchor else np.nan,
                    raw_position_error_meters=error_meters(nominal, last.longitude, last.latitude),
                    position_error_meters=error_meters(nominal,
                        current.longitude if used else last.longitude,
                        current.latitude if used else last.latitude)))
                for view, original_frame in original_frames.items():
                    changed = changed_frames[view] if used else None
                    applied = (changed is not None and not original_frame.empty and not changed.empty
                               and original_frame.observation_time.iloc[0] == changed.observation_time.iloc[0])
                    row = original_frame.iloc[0].to_dict() if not original_frame.empty else {}
                    if applied:
                        # Keep incoming-feed quality/provenance. Repair only the
                        # kinematic features; an estimate must not erase raw faults.
                        row.update({column: changed.iloc[0][column] for column in RICH_COLUMNS})
                        np.testing.assert_allclose([row[k] for k in QUALITY_COLUMNS],
                            original_frame.iloc[0][list(QUALITY_COLUMNS)].astype(float), equal_nan=True)
                    row.update(decision._asdict())
                    row.update(scenario=scenario, mode=mode, input_view=view,
                               supported=not original_frame.empty, adapter_applied=applied)
                    feature_rows.append(row)
    return feature_rows, sensor_rows


def load_legacy_models(config):
    paths = {"A_v1": config.frozen_baseline_model("quadratic"),
             "B_v1": config.frozen_baseline_model("xgboost"),
             "C_v1": config.output_directory/"models/C.joblib"}
    manifest = json.loads(paths["C_v1"].with_name("C_manifest.json").read_text())
    if manifest["config"] != config.snapshot() or file_digest(paths["C_v1"]) != manifest["model_sha256"]:
        raise ValueError("Legacy C model/config integrity failed.")
    now = inference_implementation()
    differences = [key for key, value in manifest["inference_implementation"].items() if now.get(key) != value]
    allowed = {"eta_baselines/features.py", "eta_baselines/prediction.py"}
    if set(differences)-allowed:
        raise ValueError(f"Unexpected legacy implementation mismatch: {differences}")
    return {name: joblib.load(path) for name, path in paths.items()}, paths, differences


def predict(features, models):
    outputs = []
    for name, predictor in models.items():
        view = "guarded" if name == "C_v1" else "raw"
        for (scenario, mode), group in features.loc[features.input_view.eq(view)].groupby(["scenario", "mode"]):
            group = group.sort_values("decision_id").copy()
            columns = ["approach_id", "mmsi", "decision_id", "decision_time", "arrival_time", "adapter_applied"]
            result = group[columns].copy()
            result["error_minutes"] = np.nan
            result["available"] = group.supported.to_numpy()
            supported = group.supported
            if supported.any():
                scored = predictor.predict(group.loc[supported])
                result.loc[supported, "error_minutes"] = scored.error_minutes.to_numpy()
            result["system"], result["scenario"], result["mode"] = name, scenario, mode
            outputs.append(result)
    return pd.concat(outputs, ignore_index=True)


def verify_original(predictions, config):
    previous = pd.read_csv(config.output_directory/"results/evaluation_primary/predictions.csv")
    rows = []
    for system, current in predictions.loc[predictions.scenario.eq("original") &
                                            predictions["mode"].eq("reported_only")].groupby("system"):
        saved = previous.loc[previous.system.eq(system.removesuffix("_v1")) & previous.scenario.eq("nominal")]
        saved = saved.drop_duplicates("decision_id").set_index("decision_id").reindex(current.decision_id)
        if not np.array_equal(current.available, saved.available):
            raise ValueError(f"{system} baseline availability changed.")
        np.testing.assert_allclose(current.error_minutes, saved.error_minutes, atol=1e-6, rtol=0, equal_nan=True)
        rows.append(dict(system=system, decisions=len(current),
                         maximum_absolute_forecast_difference_minutes=float(np.nanmax(
                             np.abs(current.error_minutes.to_numpy()-saved.error_minutes.to_numpy())))))
    return rows


def summarize(predictions, sensors):
    baseline = predictions.loc[predictions["mode"].eq("reported_only")].set_index(["system", "scenario", "decision_id"])
    eta_rows = []
    for (system, scenario, mode), group in predictions.groupby(["system", "scenario", "mode"]):
        keys = pd.MultiIndex.from_arrays([[system]*len(group), [scenario]*len(group), group.decision_id])
        group = group.copy()
        group["original_error_minutes"] = baseline.reindex(keys).error_minutes.to_numpy()
        group["absolute_error_change"] = group.error_minutes.abs()-group.original_error_minutes.abs()
        row = dict(system=system, scenario=scenario, mode=mode, **metrics(group))
        row["raw_mae_minutes"] = metrics(group, "original_error_minutes")["mae_minutes"]
        row["mae_change_minutes"] = row["mae_minutes"]-row["raw_mae_minutes"]
        row["mae_change_ci_low"], row["mae_change_ci_high"] = paired_interval(group)
        row["changed_forecast_fraction"] = float(group.absolute_error_change.abs().gt(1e-7).mean())
        row["adapter_applied_fraction"] = float(group.adapter_applied.mean())
        eta_rows.append(row)
    sensor_rows = []
    for (scenario, mode), group in sensors.groupby(["scenario", "mode"]):
        row = dict(scenario=scenario, mode=mode, decisions=len(group), approaches=group.approach_id.nunique(),
                   corrected_fraction=float(group.correction_available.mean()), review_fraction=float(group.review_required.mean()))
        for column in ("raw_position_error_meters", "position_error_meters"):
            row[column+"_approach_mean"] = float(group.groupby("approach_id")[column].mean().mean())
        row["position_p95_meters"] = float(group.position_error_meters.quantile(.95))
        row["harmed_fraction"] = float((group.position_error_meters > group.raw_position_error_meters+1e-6).mean())
        sensor_rows.append(row)
    return pd.DataFrame(eta_rows), pd.DataFrame(sensor_rows)


def render(eta, sensors, original_check):
    position = sensors.loc[sensors.scenario.eq("location") & sensors["mode"].eq("periodic_verified")].iloc[0]
    location_eta = eta.loc[eta.scenario.eq("location") & eta["mode"].eq("periodic_verified")]
    antidote = location_eta.loc[location_eta.system.eq("C_v1")].iloc[0]
    nominal = eta.loc[eta.system.eq("C_v1") & eta.scenario.eq("original") &
                      eta["mode"].eq("reported_only")].iloc[0]
    gain = 1-position.position_error_meters_approach_mean/position.raw_position_error_meters_approach_mean
    report = f"""# Location correction: position accuracy and legacy-v1 ETA evaluation

## Findings

- Without an extra trusted-position feed, current coordinates and ETA forecasts
  remain unchanged. One initial fix expires before the evaluated forecast clocks.
- **Conditional location-only result:** simulated trusted refreshes reduce average
  position disagreement from {position.raw_position_error_meters_approach_mean:.2f} to
  {position.position_error_meters_approach_mean:.2f} meters ({gain:.1%} reduction).
  {position.corrected_fraction:.1%} of decision-time readings receive a correction.
- Legacy Antidote C's location-attacked ETA MAE falls from {antidote.raw_mae_minutes:.4f}
  to {antidote.mae_minutes:.4f} minutes; its original-feed MAE is {nominal.mae_minutes:.4f}.
  The paired improvement is {-antidote.mae_change_minutes:.4f} minutes, with a
  conditional 95% interval [{-antidote.mae_change_ci_high:.4f}, {-antidote.mae_change_ci_low:.4f}].
- Under combined attacks, independently rejecting navigation trust blocks all
  coordinate corrections. The incorrect-trust control yields inconsistent ETA
  changes across speed directions and systems. It is not a deployable trust policy.
- The trusted fixes and reliability decisions are simulated extra information;
  the repo does not currently provide them. Only older v1 ETA models are measured.
  These findings do not establish performance for current-v2 or autonomous recovery.

| Legacy model, location-only attack | ETA MAE before (minutes) | ETA MAE after (minutes) |
|---|---:|---:|
"""
    for row in location_eta.itertuples():
        report += f"| {row.system} | {row.raw_mae_minutes:.4f} | {row.mae_minutes:.4f} |\n"
    report += """

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
"""
    for row in sensors.itertuples():
        report += (f"| {row.scenario} | {row.mode} | {row.raw_position_error_meters_approach_mean:.2f} | "
            f"{row.position_error_meters_approach_mean:.2f} | {row.position_p95_meters:.2f} | "
            f"{row.corrected_fraction:.2%} | {row.review_fraction:.2%} | {row.harmed_fraction:.2%} |\n")
    report += """
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
"""
    for row in original_check:
        report += f"| {row['system']} | {row['decisions']} | {row['maximum_absolute_forecast_difference_minutes']:.12g} |\n"
    report += """
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
"""
    for row in eta.itertuples():
        report += (f"| {row.system} | {row.scenario} | {row.mode} | {row.raw_mae_minutes:.4f} | "
            f"{row.mae_minutes:.4f} | {row.mae_change_minutes:+.4f} "
            f"[{row.mae_change_ci_low:+.4f}, {row.mae_change_ci_high:+.4f}] | {row.mdae_minutes:.4f} | "
            f"{row.p95_error_minutes:.4f} | {row.coverage:.2%} |\n")
    report += """
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
"""
    return report


def main():
    started = time.perf_counter()
    output = HERE/"results"
    output.mkdir(exist_ok=True)
    config = OptimizedConfig.load(SCIENCE/"Optimized_Model/config.json")
    dataset = load_replay(config)
    decisions = dataset.partition("evaluation").sort_values(["approach_id", "decision_time"])
    if len(decisions) != 2402 or decisions.approach_id.nunique() != 112:
        raise ValueError("Unexpected evaluation cohort.")
    models, paths, differences = load_legacy_models(config)
    protected = {str(path): file_digest(path) for path in paths.values()}
    protected.update({str(SCIENCE/path): file_digest(SCIENCE/path) for path in (
        "mitigation/location_drift_mitigation/location_drift_mitigation.py",
        "mitigation/base_mitigation.py", "mitigation/_drift_helpers.py",
        "attacks/locationDriftAttack/location_drift_attack.py",
        "attacks/sensorDriftAttack/sensor_drift_attack.py", "attacks/drift_profile.py")})
    protected.update({str(SCIENCE/path): digest for path, digest in inference_implementation().items()})
    protocol = dict(scenarios=SCENARIOS, profile_seed=42, position_channel="SIMULATED oracle original AIS fixes",
        anchor_schedule="First received report in each five-minute bin, relative to approach start",
        navigation_trust="Stipulated independent trust in original/location-only; rejection in combined",
        incorrect_trust_control="Deliberately trust attacked speed in combined cases",
        current_product_reference_channel_available=False, current_v2_models_available=False,
        models={name: str(path) for name, path in paths.items()}, legacy_implementation_differences=differences,
        protected_hashes=protected, source_hashes=dataset.manifest["sources"],
        policy=LocationDriftMitigation(config.baseline.gate).parameters,
        eta_adapter="Repair RICH_COLUMNS only, retain raw quality and matched observation anchors",
        evaluation="Exploratory, previously inspected April 8–21; no fitting or threshold changes")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2, default=str)+"\n")
    tasks = [(identity, dataset.histories[identity], group, config.baseline, config.guard)
             for identity, group in decisions.groupby("approach_id", sort=False)]
    features, sensors = [], []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(replay_case, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            case_features, case_sensors = future.result()
            features.extend(case_features)
            sensors.extend(case_sensors)
            if i % 14 == 0:
                print(f"Replayed {i}/{len(tasks)} approaches with causal periodic anchors", flush=True)
    feature_frame, sensor_frame = pd.DataFrame(features), pd.DataFrame(sensors)
    predictions = predict(feature_frame, models)
    baseline_check = verify_original(predictions, config)
    print("All original A/B/C v1 forecasts reproduced against archived predictions.", flush=True)
    for group in (predictions.groupby(["system", "scenario", "mode"]), sensor_frame.groupby(["scenario", "mode"])):
        if not group.size().eq(len(decisions)).all():
            raise ValueError("Evaluation clocks were lost.")
    if predictions.duplicated(["system", "scenario", "mode", "decision_id"]).any():
        raise ValueError("Duplicate forecast clocks.")
    eta_summary, sensor_summary = summarize(predictions, sensor_frame)
    predictions.to_csv(output/"predictions.csv", index=False)
    sensor_frame.to_csv(output/"sensor_decisions.csv", index=False)
    eta_summary.to_csv(output/"eta_summary.csv", index=False)
    sensor_summary.to_csv(output/"position_summary.csv", index=False)
    if any(file_digest(Path(path)) != digest for path, digest in protected.items()):
        raise ValueError("Protected model, policy or inference code changed during evaluation.")
    if any(file_digest(Path(path)) != digest for path, digest in dataset.manifest["sources"].items()):
        raise ValueError("A source CSV changed during evaluation.")
    validation = dict(approaches=112, vessels=110, clocks_per_configuration=2402,
        forecast_rows=len(predictions), sensor_rows=len(sensor_frame), all_clocks_retained=True,
        legacy_baseline_forecasts_reproduced=baseline_check, protected_hashes_unchanged=True,
        source_hashes_unchanged=True, raw_quality_features_preserved=True,
        unchanged_report_fields_verified=True, causal_delivery_prefix_and_anchor_schedule=True,
        initial_single_anchor_expired_before_all_clocks=True, no_model_or_threshold_fitting=True,
        elapsed_seconds=time.perf_counter()-started)
    (output/"validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    (output/"REPORT.md").write_text(render(eta_summary, sensor_summary, baseline_check))
    print(sensor_summary.to_string(index=False), flush=True)
    print(eta_summary[['system', 'scenario', 'mode', 'mae_minutes', 'raw_mae_minutes', 'mae_change_minutes',
                       'mae_change_ci_low', 'mae_change_ci_high', 'coverage']].to_string(index=False), flush=True)
    print(f"Saved results in {validation['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

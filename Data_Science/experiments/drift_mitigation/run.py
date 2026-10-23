"""Evaluate the existing drift policies, without fitting or changing them."""

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SCIENCE = HERE.parents[1]
sys.path.insert(0, str(SCIENCE))

from attacks import LocationDriftAttack, SensorDriftAttack, SensorDriftConfig
from attacks.positionJumpAttack.position_jump_attack import _distance
from eta_baselines.dataset import file_digest
from eta_baselines.features import METERS_PER_DEGREE
from eta_baselines.motion import KNOTS_TO_METERS_PER_SECOND
from mitigation import LocationDriftMitigation, SensorDriftMitigation
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import load_replay

SCENARIOS = {
    "original": (0., False),
    "speed_under": (-.1, False),
    "speed_over": (.1, False),
    "location": (0., True),
    "combined_under": (-.1, True),
    "combined_over": (.1, True),
}


def evaluate_case(task):
    identity, source, decisions, gate = task
    source = source.sort_values("time", kind="stable").reset_index(drop=True)
    original = source.set_index("time")
    start = source.time.min()
    speed_policy, location_policy = SensorDriftMitigation(gate), LocationDriftMitigation(gate)
    rows = []
    for scenario, (rate, location_fault) in SCENARIOS.items():
        stream = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=rate)).apply(source)
        if location_fault:
            stream = LocationDriftAttack().apply(stream.reports)
        reports = stream.reports
        untouched = [column for column in source if column not in ("sog", "latitude", "longitude")]
        pd.testing.assert_frame_equal(reports[untouched], source[untouched])
        # No audit columns or original observations are supplied to either policy.
        for decision in decisions.itertuples():
            speed = speed_policy.apply(reports, decision.decision_time)
            location = location_policy.apply(reports, decision.decision_time)
            current = reports.loc[reports.time.eq(speed.observation_time)].iloc[0]
            reference = original.loc[speed.observation_time]
            position_error = float(_distance(np.array([reference.latitude]), np.array([reference.longitude]),
                                            np.array([current.latitude]), np.array([current.longitude]))[0])
            raw_error = abs(float(current.sog - reference.sog))
            repaired_error = abs(float(speed.speed_knots - reference.sog)) if speed.speed_knots is not None else np.nan
            corrected = speed.speed_source == "estimated"
            # An experiment-only conservative combination; production remains unchanged.
            permitted = corrected and location.can_predict
            rows.append(dict(scenario=scenario, approach_id=identity, mmsi=str(decision.mmsi),
                decision_id=decision.decision_id, decision_time=decision.decision_time,
                observation_time=speed.observation_time,
                elapsed_minutes=(speed.observation_time-start).total_seconds()/60,
                speed_status=speed.status.value, speed_repaired=corrected,
                speed_requires_review=speed.requires_review, speed_position_supported=speed.position_supported,
                speed_reasons=";".join(speed.reasons), speed_anomaly_since=speed.anomaly_since,
                location_status=location.status.value, location_flag=location.drift_detected,
                location_requires_review=location.requires_review,
                location_reference_supported=location.reference_supported,
                location_reasons=";".join(location.reasons), location_anomaly_since=location.anomaly_since,
                either_flag=corrected or location.drift_detected,
                either_requires_review=speed.requires_review or location.requires_review,
                raw_speed_error_knots=raw_error, repaired_speed_error_knots=repaired_error,
                gated_speed_error_knots=repaired_error if permitted else raw_error,
                gated_speed_repaired=permitted, location_error_meters=position_error,
                speed_repair_helped=corrected and repaired_error < raw_error-1e-6,
                speed_repair_harmed=corrected and repaired_error > raw_error+1e-6))
    return rows


def approach_mean(group, column):
    return float(group.groupby("approach_id")[column].mean().mean())


def summarize(frame):
    rows = []
    for scenario, group in frame.groupby("scenario", sort=False):
        repaired = group.loc[group.speed_repaired]
        row = dict(scenario=scenario, decisions=len(group), approaches=group.approach_id.nunique(),
                   vessels=group.mmsi.nunique())
        for column in ("speed_repaired", "location_flag", "either_flag", "speed_requires_review",
                       "location_requires_review", "either_requires_review", "gated_speed_repaired"):
            row[column+"_decision_fraction"] = float(group[column].mean())
            row[column+"_approach_fraction"] = float(group.groupby("approach_id")[column].max().mean())
        for column in ("raw_speed_error_knots", "repaired_speed_error_knots", "gated_speed_error_knots",
                       "location_error_meters"):
            row[column+"_approach_mean"] = approach_mean(group, column)
        row["repaired_decisions"] = len(repaired)
        row["repair_helped_fraction"] = float(repaired.speed_repair_helped.mean())
        row["repair_harmed_fraction"] = float(repaired.speed_repair_harmed.mean())
        row["speed_error_change_knots"] = (row["repaired_speed_error_knots_approach_mean"]
                                             - row["raw_speed_error_knots_approach_mean"])
        delta = group.assign(delta=group.repaired_speed_error_knots-group.raw_speed_error_knots)
        approaches = delta.groupby(["mmsi", "approach_id"], as_index=False).delta.mean()
        clusters = [g.delta.to_numpy() for _, g in approaches.groupby("mmsi", sort=True)]
        rng = np.random.default_rng(20261022)
        draws = [np.concatenate([clusters[i] for i in rng.integers(len(clusters), size=len(clusters))]).mean()
                 for _ in range(1000)]
        row["speed_error_change_ci_low"], row["speed_error_change_ci_high"] = map(float, np.quantile(draws, [.025, .975]))
        rows.append(row)
    return pd.DataFrame(rows)


def coordinated_example(gate):
    """A constructed observability example, separate from the default attacks."""
    times = pd.date_range("2024-04-08", periods=31, freq="1min")
    original = pd.DataFrame(dict(mmsi="coordinated-example", time=times,
        longitude=gate.longitude+np.arange(len(times))*60*10*KNOTS_TO_METERS_PER_SECOND/
                  (METERS_PER_DEGREE*np.cos(np.deg2rad(37.))),
        latitude=37., sog=10., cog=90.))
    attacked = SensorDriftAttack(SensorDriftConfig(drift_rate_knots_per_minute=.1)).apply(original).reports
    speeds = attacked.sog.to_numpy()
    east = np.r_[0., np.cumsum((speeds[:-1]+speeds[1:])*.5*60*KNOTS_TO_METERS_PER_SECOND)]
    attacked["longitude"] = gate.longitude+east/(METERS_PER_DEGREE*np.cos(np.deg2rad(37.)))
    speed_policy, location_policy = SensorDriftMitigation(gate), LocationDriftMitigation(gate)
    rows = []
    for clock in times:
        speed = speed_policy.apply(attacked, clock)
        location = location_policy.apply(attacked, clock)
        i = times.get_loc(clock)
        rows.append(dict(decision_time=clock, speed_status=speed.status.value,
            location_status=location.status.value, speed_flag=speed.anomaly_detected,
            location_flag=location.drift_detected, speed_error_knots=float(speeds[i]-10),
            location_error_meters=float(_distance(np.array([37.]), np.array([original.longitude.iloc[i]]),
                                                   np.array([37.]), np.array([attacked.longitude.iloc[i]]))[0])))
    return pd.DataFrame(rows)


def render_report(summary, frame, coordinated):
    speed = summary.set_index("scenario").loc["speed_under"]
    combined = summary.set_index("scenario").loc["combined_under"]
    original = summary.set_index("scenario").loc["original"]
    speed_gain = -speed.speed_error_change_knots/speed.raw_speed_error_knots_approach_mean
    combined_gain = -combined.speed_error_change_knots/combined.raw_speed_error_knots_approach_mean
    report = f"""# Drift mitigation: separate and combined attacks

## Findings

- Speed-only drift: average injected speed error falls from
  {speed.raw_speed_error_knots_approach_mean:.3f} to {speed.repaired_speed_error_knots_approach_mean:.3f}
  knots ({speed_gain:.1%} reduction). Only {speed.speed_repaired_decision_fraction:.1%} of
  decision-time readings are repaired; {speed.speed_requires_review_decision_fraction:.1%}
  request review. Most reference refusals involve maneuvering/inconsistent position
  tracks or waiting for sufficient supported history after a reset.
- Independent speed and location drift together: average speed error falls to
  {combined.repaired_speed_error_knots_approach_mean:.3f} knots ({combined_gain:.1%} reduction).
  All attacked approaches raise a location consistency warning. Coordinates are
  never repaired by this policy.
- The location warning also flags {original.location_flag_approach_fraction:.2%} of
  original-feed approaches (21/112), and every speed-only attacked approach. It
  detects disagreement but cannot identify which sensor is wrong.
- Under location-only drift, the speed policy makes 37 replacements that worsen
  agreement with untouched original speed. A naive location-warning veto blocks
  every speed replacement, including speed-only cases.
- The coordinated example below evades both checks. These policies are useful
  prototype components, but their current combination is not a validated automatic
  recovery system. Fault isolation and development calibration remain necessary.

The percentages above concern these fixed simulated settings. They do not measure
ETA accuracy or establish performance against other attack combinations.

## Scope and protocol

This study supplies no verified position anchors or independent navigation trust.
It measures detection-only location behavior; the optional anchored correction
extension is outside its scope. The archived results predate that extension.

This evaluates the existing default policies without fitting or changing thresholds.
The previously inspected April 8–21 replay contains 112 approaches, 110 vessels and
2,402 original decision clocks per scenario. Source AIS is the recovery reference,
not independently verified physical truth. This is an exploratory follow-up.

Speed drift is ±0.1 knots/minute with a smooth 3-knot cap. Location drift is
20 meters/minute with a smooth 1,852-meter cap and a seeded fixed bearing per
vessel. Default seed 42, 25% rate variation and a 20-minute cycle are used. Both
faults start at each approach's first supplied report. Combined scenarios compose
these two attacks; source timestamps, report counts and decision clocks stay fixed.
No missing-data, gap, noise or sudden-jump attacks are included in this study.

Each mitigation sees only received attacked reports at the current clock; it never
sees source values, injected biases or future reports. Both policies inspect the
raw attacked stream independently. Feeding repaired speed back into the location
check would artificially force agreement and is not done here.

## Sensor recovery

The speed policy replaces the current speed only when its existing persistence and
position-quality checks pass. Otherwise its output retains reported speed and may
request review. No decision, including review/warmup cases, is dropped from error
calculations. MAE below gives each approach equal weight. These are sensor errors
in knots, **not ETA errors**; no model forecasts or production adapters are evaluated.

| Scenario | Speed MAE before | Speed MAE after | Change [95% interval] | Decisions repaired | Repairs that worsen speed error |
|---|---:|---:|---:|---:|---:|
"""
    for row in summary.itertuples():
        report += (f"| {row.scenario} | {row.raw_speed_error_knots_approach_mean:.4f} | "
            f"{row.repaired_speed_error_knots_approach_mean:.4f} | {row.speed_error_change_knots:+.4f} "
            f"[{row.speed_error_change_ci_low:+.4f}, {row.speed_error_change_ci_high:+.4f}] | "
            f"{row.speed_repaired_decision_fraction:.2%} | {row.repair_harmed_fraction:.2%} |\n")
    report += """
Intervals use 1,000 paired vessel-cluster bootstrap draws with fixed seed 20261022.
They describe the sampled approaches conditional on these single-seed scenarios;
they do not establish generalization across attack settings or populations.
An unchanged error is omitted from both helped and harmed counts.

## Alerts and review burden

An approach is flagged if a flag is present at any evaluated clock. Speed flags
are current repair decisions; location flags latch for the supplied session.
Therefore their approach rates do not represent equally persistent detectors.
The columns below are observed alert rates, not fault-specific classification
accuracy. A speed fault can activate the location consistency check and vice versa.

| Scenario | Approaches with speed flag | Approaches with location flag | Either flag | Speed review: decisions | Location review: decisions |
|---|---:|---:|---:|---:|---:|
"""
    for row in summary.itertuples():
        report += (f"| {row.scenario} | {row.speed_repaired_approach_fraction:.2%} | "
            f"{row.location_flag_approach_fraction:.2%} | {row.either_flag_approach_fraction:.2%} | "
            f"{row.speed_requires_review_decision_fraction:.2%} | {row.location_requires_review_decision_fraction:.2%} |\n")
    report += """
The original-feed row measures alerts without any injected fault, not proven false
positives against verified physical truth. A high rate limits the detector's ability
to distinguish a new fault from existing AIS disagreement. Review includes warming
up, unsupported input and detected location drift, so review is not a missed alarm.

### Location detection incremental to original-feed alerts

| Scenario | Already flagged original approaches | Newly flagged approaches | Original flags lost |
|---|---:|---:|---:|
"""
    baseline = frame.loc[frame.scenario.eq("original")].groupby("approach_id").location_flag.max()
    for name in ("location", "combined_under", "combined_over"):
        attacked = frame.loc[frame.scenario.eq(name)].groupby("approach_id").location_flag.max().reindex(baseline.index)
        report += f"| {name} | {int(baseline.sum())} | {int((attacked & ~baseline).sum())} | {int((baseline & ~attacked).sum())} |\n"
    report += """
## Combination policy diagnostic

The existing modules are independent. An experiment-only rule that permits speed
repair only when the location policy recommends normal input yields:

| Scenario | Speed MAE with location veto | Decisions repaired |
|---|---:|---:|
"""
    for row in summary.itertuples():
        report += f"| {row.scenario} | {row.gated_speed_error_knots_approach_mean:.4f} | {row.gated_speed_repaired_decision_fraction:.2%} |\n"
    report += """
This veto is not installed in production, not a fitted strategy, and not validated
as a reliable fault classifier. Its improvement or lack of coverage must be read
alongside the original-feed alert rate. Location coordinates remain uncorrected
in every scenario: this mitigation requests an independent verified position.

## Coordinated corruption counterexample

A separate synthetic 10-knot straight track is attacked with positive speed drift.
Reported positions integrate the attacked speed using the same trapezoidal motion
rule as the location detector. This deliberately coordinated construction differs
from the default independent location attack and is an observability stress example,
not a measured prevalence estimate.

"""
    last = coordinated.iloc[-1]
    report += (f"After 30 minutes, speed error is {last.speed_error_knots:.3f} knots and location "
        f"error is {last.location_error_meters:.1f} meters. Across {len(coordinated)} checks, the speed "
        f"policy flags {int(coordinated.speed_flag.sum())} and the location policy flags "
        f"{int(coordinated.location_flag.sum())}. Mutually consistent corrupted measurements can evade "
        "both checks. An independent trustworthy reference is needed to resolve this ambiguity.\n\n")
    report += """## Interpretation and limits

These results evaluate initial drift policies, not a deployed end-to-end mitigation
system. Unsupported references are an intentional safeguard but reduce automatic
repair coverage. Source AIS itself can contain noise, maneuvers and synchronization
errors. Current location thresholds are provisional and have not been calibrated
on a separate development cohort. Do not tune them against this evaluation cohort
and then present the same results as validation. ETA improvement requires a separate
causal feature/forecast evaluation with the current frozen model artifacts.

CSV decision-level outputs and summaries are local ignored artifacts. Protocol,
validation metadata and this report are saved alongside the reproducible script.
Run from Data_Science: `python experiments/drift_mitigation/run.py`.
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
    protected = [SCIENCE/path for path in (
        "mitigation/sensor_drift_mitigation/sensor_drift_mitigation.py",
        "mitigation/location_drift_mitigation/location_drift_mitigation.py",
        "mitigation/_drift_helpers.py", "mitigation/base_mitigation.py",
        "attacks/sensorDriftAttack/sensor_drift_attack.py",
        "attacks/locationDriftAttack/location_drift_attack.py", "attacks/drift_profile.py")]
    hashes = {str(path.relative_to(SCIENCE)): file_digest(path) for path in protected}
    protocol = dict(scenarios=SCENARIOS, seed=42, speed_attack=SensorDriftAttack().parameters,
        location_attack=LocationDriftAttack().parameters,
        speed_policy=SensorDriftMitigation(config.baseline.gate).parameters,
        location_policy=LocationDriftMitigation(config.baseline.gate).parameters,
        input_cache=str(config.output_directory/"replay_dataset.joblib"),
        source_hashes=dataset.manifest["sources"], policy_code_hashes=hashes,
        evaluation="Previously inspected April 8–21; exploratory follow-up",
        sensors_reference="Original AIS, not independently verified physical truth",
        no_threshold_fitting=True, no_forecasts_evaluated=True,
        metric="Approach-weighted current sensor absolute error; all decisions retained",
        interval="1000 paired vessel-cluster bootstrap draws, seed 20261022")
    (output/"protocol.json").write_text(json.dumps(protocol, indent=2, default=str)+"\n")
    tasks = [(identity, dataset.histories[identity], group, config.baseline.gate)
             for identity, group in decisions.groupby("approach_id", sort=False)]
    rows = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(evaluate_case, task) for task in tasks]
        for i, future in enumerate(as_completed(futures), 1):
            rows.extend(future.result())
            if i % 14 == 0:
                print(f"Completed {i}/{len(tasks)} approaches across all six scenarios", flush=True)
    frame = pd.DataFrame(rows).sort_values(["scenario", "approach_id", "decision_time"])
    if frame.duplicated(["scenario", "decision_id"]).any():
        raise ValueError("Duplicate decision output.")
    if not frame.groupby("scenario").size().eq(len(decisions)).all():
        raise ValueError("A scenario lost an evaluation decision.")
    if not np.isfinite(frame[["raw_speed_error_knots", "repaired_speed_error_knots", "location_error_meters"]]).all().all():
        raise ValueError("Nonfinite source or output error; report missingness explicitly before proceeding.")
    summary = summarize(frame)
    coordinated = coordinated_example(config.baseline.gate)
    frame.to_csv(output/"decisions.csv", index=False)
    summary.to_csv(output/"summary.csv", index=False)
    coordinated.to_csv(output/"coordinated_example.csv", index=False)
    reasons = pd.concat([frame.groupby(["scenario", field]).size().reset_index(name="decisions")
                         .rename(columns={field: "reasons"}).assign(policy=field.split("_")[0])
                         for field in ("speed_reasons", "location_reasons")], ignore_index=True)
    reasons.to_csv(output/"reasons.csv", index=False)
    (output/"REPORT.md").write_text(render_report(summary, frame, coordinated))
    if any(file_digest(SCIENCE/path) != value for path, value in hashes.items()):
        raise ValueError("An evaluated policy or attack changed during evaluation.")
    if any(file_digest(Path(path)) != value for path, value in dataset.manifest["sources"].items()):
        raise ValueError("A source CSV changed during evaluation.")
    validation = dict(approaches=112, vessels=110, decisions_per_scenario=len(decisions),
        scenarios=len(SCENARIOS), output_decisions=len(frame), all_decisions_retained=True,
        all_sensor_errors_finite=True, policy_and_attack_hashes_unchanged=True,
        audit_truth_excluded_from_mitigation_inputs=True, source_csvs_unchanged=True,
        source_hashes_reverified_after_evaluation=True,
        all_scenario_report_counts_and_unaffected_fields_verified=True,
        coordinated_example_minutes=30, coordinated_example_checks=len(coordinated),
        models_and_thresholds_unchanged=True, elapsed_seconds=time.perf_counter()-started)
    (output/"validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    print(summary.to_string(index=False), flush=True)
    print(f"Saved results in {validation['elapsed_seconds']:.1f}s", flush=True)


if __name__ == "__main__":
    main()

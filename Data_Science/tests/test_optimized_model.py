"""Deterministic checks for replay integrity, guard behavior and learned contracts."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyRegressor

from eta_baselines.fitting import fit_imputer, training_weights
from eta_baselines.features import FEATURE_COLUMNS, LEGACY_FEATURE_COLUMNS, VESSEL_CLASS_COLUMNS
from eta_baselines.motion import circular_summary
from eta_baselines.prediction import EtaPredictor
from Optimized_Model.calibration import apply_review, fit_calibration, review_metrics
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import ReplayDataset, _freeze_baselines
from Optimized_Model.evaluation import PredictionSystem
from Optimized_Model.features import OPTIMIZED_COLUMNS, OptimizedFeatures
from Optimized_Model.quality import InputGuard
from Optimized_Model.presentation import EvaluationEvidence, feed_counts, inspect_feed
from Optimized_Model.replay import Condition, Scenario, create_stream
from Optimized_Model.service import DemoService
from Optimized_Model.views import ReplayTask, _replay_approach, view_row
from attacks import MissingCourseConfig, MissingSpeedConfig, ReportingGapAttack, ReportingGapConfig


@pytest.fixture
def optimized_config(tmp_path: Path) -> OptimizedConfig:
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "observations.csv"
    source.write_text("mmsi,time\n", encoding="utf-8")
    baseline = json.loads((root / "config.json").read_text())
    baseline["input_csv"] = str(source)
    baseline["output_directory"] = str(tmp_path / "baseline")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    # Hash-only placeholder files isolate calibration tests from real saved models.
    for name in ("quadratic", "xgboost"):
        directory = tmp_path / "frozen_baselines" / name
        directory.mkdir(parents=True)
        (directory / "model.joblib").write_bytes(b"unit-test artifact")
    contents = json.loads((root / "Optimized_Model/config.json").read_text())
    contents.update({"baseline_config": str(baseline_path), "output_directory": str(tmp_path),
                     "later_csv": str(tmp_path / "later.csv")})
    config_path = tmp_path / "optimized.json"
    config_path.write_text(json.dumps(contents), encoding="utf-8")
    config = OptimizedConfig.load(config_path)
    return replace(config, review=replace(config.review, minimum_calibration_approaches=2))


@pytest.fixture
def vessel_reports() -> pd.DataFrame:
    count = 25
    return pd.DataFrame({"mmsi": "123456789", "time": pd.date_range("2024-03-05 12:00", periods=count, freq="min"),
                         "longitude": -76.15 - np.arange(count) * .001,
                         "latitude": 37.0, "sog": 3.0, "cog": 270.0, "vessel_type": 70})


def test_delayed_reports_do_not_arrive_early_and_preserve_values(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    scenario = Scenario("delay", Condition.STALE, delay_minutes=5)
    stream = create_stream(vessel_reports, scenario, 42, optimized_config.baseline.gate)
    available = stream.available(pd.Timestamp("2024-03-05 12:10"))
    assert available["time"].max() == pd.Timestamp("2024-03-05 12:05")
    pd.testing.assert_series_equal(stream.reports["longitude"].reset_index(drop=True), vessel_reports["longitude"])
    assert not stream.modification_log["fault_applied"].any()


def test_quality_only_preserves_timing_and_hides_truth(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    scenario = Scenario("bias", Condition.QUALITY, offset_nautical_miles=.5, affected_fraction=1)
    stream = create_stream(vessel_reports, scenario, 42, optimized_config.baseline.gate)
    pd.testing.assert_series_equal(stream.reports["time"].reset_index(drop=True), vessel_reports["time"])
    assert (stream.reports["delivered_time"] == stream.reports["time"]).all()
    assert not {"fault_applied", "scenario", "east_offset_meters"} & set(stream.reports)
    assert stream.modification_log["fault_applied"].all()


def test_future_records_cannot_change_corruption_or_earlier_features(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    scenario = Scenario("combined", Condition.COMBINED, 5, .5, .5)
    time = pd.Timestamp("2024-03-05 12:15")
    short = create_stream(vessel_reports.iloc[:16], scenario, 42, optimized_config.baseline.gate)
    full = create_stream(vessel_reports, scenario, 42, optimized_config.baseline.gate)
    pd.testing.assert_frame_equal(short.available(time), full.available(time))
    builder = OptimizedFeatures(optimized_config.baseline, optimized_config.guard)
    first, _ = builder.snapshot(short.reports, time, guarded=True)
    second, _ = builder.snapshot(full.reports, time, guarded=True)
    pd.testing.assert_frame_equal(first, second)


def test_robust_bins_bound_nonidentical_repetition_weight(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    original = vessel_reports.iloc[:10].copy()
    repeated = original.iloc[[3]].copy()
    repeated["longitude"] += .000001
    repeated = pd.concat([repeated] * 20, ignore_index=True)
    guard = InputGuard(optimized_config.baseline.gate, optimized_config.guard)
    result = guard.apply(pd.concat([original, repeated], ignore_index=True))
    assert len(result.reports) == 10
    assert result.reports["time"].dt.floor("min").is_unique
    assert result.removed_count > 0


def test_implausible_jump_is_screened_and_normal_turn_is_retained(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    reports = vessel_reports.iloc[:4].copy()
    reports.loc[1, "longitude"] += 1
    reports.loc[2:, "cog"] = 180
    guard = InputGuard(optimized_config.baseline.gate, optimized_config.guard)
    result = guard.apply(reports)
    assert reports["time"].iloc[1] not in set(result.reports["time"])
    assert reports["time"].iloc[2] in set(result.reports["time"])
    assert "implausible_position_jump" in result.reasons


def test_circular_features_handle_wraparound() -> None:
    direction, dispersion = circular_summary(np.array([359., 1.]))
    assert min(direction, 360 - direction) < 1e-10
    assert dispersion < .001


def test_augmented_weights_keep_approaches_and_decisions_equal() -> None:
    rows = []
    for approach, count in (("a", 2), ("b", 4)):
        for decision in range(count):
            for condition in ("nominal", "stale"):
                for _ in range(3 if condition == "stale" else 1):
                    rows.append({"approach_id": approach, "decision_id": f"{approach}{decision}", "condition": condition})
    frame = pd.DataFrame(rows)
    frame["weight"] = training_weights(frame)
    totals = frame.groupby("approach_id")["weight"].sum()
    assert totals.loc["a"] == pytest.approx(totals.loc["b"])
    condition_totals = frame.groupby(["approach_id", "decision_id", "condition"])["weight"].sum()
    assert condition_totals.loc[("a", "a0", "nominal")] == pytest.approx(condition_totals.loc[("a", "a0", "stale")])


def test_decision_clock_model_does_not_subtract_age_twice() -> None:
    snapshots = pd.DataFrame({"custom_feature": [1.0], "observation_time": [pd.Timestamp("2024-03-05 11:50")],
                              "decision_time": [pd.Timestamp("2024-03-05 12:00")]})
    imputer = fit_imputer(snapshots, ("custom_feature",))
    regressor = DummyRegressor(strategy="constant", constant=30).fit([[1]], [30])
    predictor = EtaPredictor("C", imputer, regressor, ("custom_feature",), "decision")
    result = predictor.predict(snapshots).iloc[0]
    assert result["predicted_arrival_time"] == pd.Timestamp("2024-03-05 12:30")
    assert result["predicted_observation_duration_minutes"] == 40


def calibration_examples() -> pd.DataFrame:
    return pd.DataFrame({"split": "calibration", "system": "C", "approach_id": ["a", "a", "b", "b"],
                         "decision_time": pd.Timestamp("2024-04-02"), "available": True,
                         "error_minutes": [1., 2., 3., 4.], "report_age_minutes": 2.,
                         "predicted_remaining_minutes": 15.})


def test_calibration_requires_independent_partition(optimized_config: OptimizedConfig) -> None:
    frame = calibration_examples()
    frame["split"] = "evaluation"
    with pytest.raises(ValueError, match="separate calibration"):
        fit_calibration(frame, optimized_config)


def test_calibration_uses_approaches_and_review_is_outcome_independent(optimized_config: OptimizedConfig) -> None:
    frame = calibration_examples()
    artifact = fit_calibration(frame, optimized_config)
    assert artifact["bands"]["C"]["pooled"]["approaches"] == 2
    assert artifact["bands"]["C"]["pooled"]["half_width_minutes"] == 4
    original = apply_review(frame, artifact, optimized_config)
    frame["error_minutes"] = 9999
    changed = apply_review(frame, artifact, optimized_config)
    pd.testing.assert_series_equal(original["accepted"], changed["accepted"])


def test_missing_calibration_cannot_create_false_confidence(optimized_config: OptimizedConfig) -> None:
    frame = calibration_examples()
    artifact = {"bands": {}}
    reviewed = apply_review(frame, artifact, optimized_config)
    assert not reviewed["accepted"].any()
    assert reviewed["interval_half_width_minutes"].isna().all()
    metrics = review_metrics(reviewed, 5)
    assert metrics["scheduled"] == metrics["accepted"] + metrics["deferred_or_unavailable"]
    assert metrics["useful_output_rate"] == 0


def test_views_expose_only_declared_features_and_true_retained_age(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    reports = vessel_reports.iloc[:10].copy()
    decision = pd.Series({"decision_time": pd.Timestamp("2024-03-05 12:15")})
    row = view_row(reports, decision, OptimizedFeatures(optimized_config.baseline, optimized_config.guard))
    assert set(OPTIMIZED_COLUMNS) <= set(row)
    assert row["latest_received_age_minutes"] == 6
    assert row["latest_usable_age_minutes"] == 6
    assert "fault_applied" not in row


@pytest.fixture
def demo_service(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> DemoService:
    decision = pd.DataFrame({"approach_id": ["voyage"], "mmsi": ["123456789"], "decision_id": ["decision"],
                             "decision_time": [pd.Timestamp("2024-03-05 12:15")], "split": ["exploratory"],
                             "arrival_time": [pd.Timestamp("2024-03-05 12:45")],
                             "crossing_before": [pd.Timestamp("2024-03-05 12:44")],
                             "crossing_after": [pd.Timestamp("2024-03-05 12:46")]})
    imputer = fit_imputer(pd.DataFrame({"east_meters": [1.]}), ("east_meters",))
    regressor = DummyRegressor(strategy="constant", constant=20).fit([[1.]], [20.])
    systems = [PredictionSystem(name, EtaPredictor(name, imputer, regressor, ("east_meters",), "decision"),
                                "guarded" if name == "C" else "raw") for name in ("A", "B", "C")]
    return DemoService(optimized_config, ReplayDataset(decision, {"voyage": vessel_reports}, {}), systems,
                       OptimizedFeatures(optimized_config.baseline, optimized_config.guard), None)


def test_demo_hides_outcomes_until_reveal_and_verification_stays_causal(demo_service: DemoService) -> None:
    hidden = demo_service.snapshot("decision", "stale_15", reveal=False, verify=False)
    assert hidden["reference_arrival"] is None
    assert all("error_minutes" not in card for card in hidden["cards"])
    assert all(not card["accepted"] for card in hidden["cards"])
    revealed = demo_service.snapshot("decision", "stale_15", reveal=True, verify=False)
    assert revealed["reference_arrival"] == "2024-03-05T12:45:00"
    assert all("error_minutes" in card for card in revealed["cards"])
    verified = demo_service.snapshot("decision", "stale_15", reveal=False, verify=True)
    assert verified["verified_observation_time"] == "2024-03-05T12:15:00"
    assert verified["human_assisted"]
    demo_service.record_verification("decision", "stale_15", 3.5)
    assert '"human_review_seconds": 3.5' in (demo_service.config.output_directory / "human_verification.jsonl").read_text()


def test_full_outage_stays_unsupported(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    stream = create_stream(vessel_reports, Scenario("outage", Condition.STALE, delay_minutes=1440),
                           42, optimized_config.baseline.gate)
    result, diagnostics = OptimizedFeatures(optimized_config.baseline, optimized_config.guard).snapshot(
        stream.available(pd.Timestamp("2024-03-05 12:15")), pd.Timestamp("2024-03-05 12:15"), guarded=True,
    )
    assert result.empty
    assert diagnostics.reasons == ("no_reports",)


def test_source_volume_audit_covers_each_delivered_copy(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    scenario = Scenario("volume", Condition.QUALITY, affected_fraction=.5, offset_nautical_miles=.5,
                        repetition=3, total_repetition=2, repetition_jitter_meters=.1)
    stream = create_stream(vessel_reports, scenario, 42, optimized_config.baseline.gate)
    assert set(stream.reports["record_id"]) == set(stream.modification_log["record_id"])
    assert stream.modification_log["record_id"].is_unique


def test_saved_legacy_predictor_keeps_observation_anchor(demo_service: DemoService) -> None:
    predictor = demo_service.systems[0].predictor
    del predictor.__dict__["feature_columns"]
    del predictor.__dict__["target_clock"]
    # Recover the original schema from fitted preprocessing, not current defaults.
    snapshots = pd.DataFrame({column: [1.] for column in LEGACY_FEATURE_COLUMNS})
    snapshots["observation_time"] = pd.Timestamp("2024-03-05 12:00")
    snapshots["decision_time"] = pd.Timestamp("2024-03-05 12:10")
    predictor.imputer = fit_imputer(snapshots, LEGACY_FEATURE_COLUMNS)
    predictor.regressor = DummyRegressor(strategy="constant", constant=20).fit([[1.] * len(LEGACY_FEATURE_COLUMNS)], [20.])
    result = predictor.predict(snapshots).iloc[0]
    assert result["predicted_arrival_time"] == pd.Timestamp("2024-03-05 12:20")
    assert result["predicted_remaining_minutes"] == 10


@pytest.mark.parametrize("guarded", [False, True])
def test_optimized_features_keep_unknown_class_distinct(optimized_config, vessel_reports, guarded):
    extractor = OptimizedFeatures(optimized_config.baseline, optimized_config.guard)
    decision = vessel_reports.time.iloc[-1]
    cargo, _ = extractor.snapshot(vessel_reports, decision, guarded=guarded)
    missing = vessel_reports.assign(vessel_type=np.nan)
    unknown, _ = extractor.snapshot(missing, decision, guarded=guarded)
    assert tuple(cargo.iloc[0][list(VESSEL_CLASS_COLUMNS)]) == (1., 0., 0.)
    assert tuple(unknown.iloc[0][list(VESSEL_CLASS_COLUMNS)]) == (0., 0., 1.)
    assert cargo.observation_time.iloc[0] == unknown.observation_time.iloc[0]
    other = [column for column in cargo if column not in VESSEL_CLASS_COLUMNS]
    pd.testing.assert_frame_equal(cargo[other], unknown[other])


def test_prediction_rejects_missing_or_future_timestamp(demo_service: DemoService) -> None:
    predictor = demo_service.systems[0].predictor
    snapshots = pd.DataFrame({"east_meters": [1.], "observation_time": [pd.NaT],
                              "decision_time": [pd.Timestamp("2024-03-05 12:00")]})
    with pytest.raises(ValueError, match="must be present"):
        predictor.predict(snapshots)
    snapshots["observation_time"] = pd.Timestamp("2024-03-05 12:01")
    with pytest.raises(ValueError, match="later than decision"):
        predictor.predict(snapshots)


def test_reserved_drift_uses_past_route_direction(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    scenario = Scenario("drift", Condition.QUALITY, offset_nautical_miles=1, affected_fraction=1, drift=True)
    short = create_stream(vessel_reports.iloc[:16], scenario, 4201, optimized_config.baseline.gate)
    full = create_stream(vessel_reports, scenario, 4201, optimized_config.baseline.gate)
    pd.testing.assert_frame_equal(short.reports, full.reports.iloc[:16])
    assert (full.modification_log["east_offset_meters"].iloc[1:] < 0).all()
    assert (full.modification_log["north_offset_meters"] == 0).all()


def test_volume_cache_preserves_features_and_separate_audit(demo_service: DemoService) -> None:
    scenarios = [Scenario("reference"), Scenario("repeated", total_repetition=5)]
    decisions = demo_service.dataset.decisions
    rows, audit, prevalence = _replay_approach(ReplayTask(
        demo_service.config.baseline, demo_service.config.guard, decisions,
        demo_service.dataset.histories["voyage"], scenarios, 42, False,
    ))
    for feature in OPTIMIZED_COLUMNS:
        assert rows[0][feature] == pytest.approx(rows[1][feature], nan_ok=True)
    assert len(audit.loc[audit["scenario"] == "repeated"]) == 5 * len(audit.loc[audit["scenario"] == "reference"])
    assert prevalence[1]["received_reports_before_deduplication"] == 5 * prevalence[0]["received_reports_before_deduplication"]


def test_stationary_drift_fallback_requires_separate_fault_seeds(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    stationary = vessel_reports.iloc[:4].copy()
    stationary["longitude"] = stationary["longitude"].iloc[0]
    scenario = Scenario("drift", Condition.QUALITY, offset_nautical_miles=1, affected_fraction=1, drift=True)
    first = create_stream(stationary, scenario, 4201, optimized_config.baseline.gate)
    second = create_stream(stationary, scenario, 4202, optimized_config.baseline.gate)
    assert not first.reports["longitude"].equals(second.reports["longitude"])


def test_missing_reported_motion_remains_missing_while_positions_support_velocity(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    reports = vessel_reports.iloc[:10].copy()
    reports[["sog", "cog"]] = np.nan
    snapshot, _ = OptimizedFeatures(optimized_config.baseline, optimized_config.guard).snapshot(
        reports, pd.Timestamp("2024-03-05 12:15"), guarded=True,
    )
    row = snapshot.iloc[0]
    assert np.isnan(row["speed_knots"])
    assert row["missing_speed_fraction"] == row["missing_course_fraction"] == 1
    assert np.isfinite(row["history_east_velocity_mps"])
    assert row["velocity_unavailable"] == 0


def test_long_gap_does_not_fabricate_a_supported_velocity(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    reports = vessel_reports.iloc[[0, 1, 10]].copy()
    snapshot, _ = OptimizedFeatures(optimized_config.baseline, optimized_config.guard).snapshot(
        reports, pd.Timestamp("2024-03-05 12:10"), guarded=True,
    )
    row = snapshot.iloc[0]
    assert np.isnan(row["history_east_velocity_mps"])
    assert row["velocity_unavailable"] == 1
    assert row["maximum_gap_seconds"] == 540


def test_rejecting_latest_report_preserves_older_usable_timestamp(optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame) -> None:
    reports = vessel_reports.iloc[:10].copy()
    reports.loc[reports.index[-1], "longitude"] += 1
    row = view_row(reports, pd.Series({"decision_time": pd.Timestamp("2024-03-05 12:15")}),
                   OptimizedFeatures(optimized_config.baseline, optimized_config.guard))
    assert row["raw_observation_time"] == pd.Timestamp("2024-03-05 12:09")
    assert row["observation_time"] == pd.Timestamp("2024-03-05 12:08")
    assert row["latest_received_age_minutes"] == 6
    assert row["latest_usable_age_minutes"] == 7


def test_frozen_baselines_survive_upstream_retraining(optimized_config: OptimizedConfig) -> None:
    config = replace(optimized_config, output_directory=optimized_config.output_directory / "new_run")
    for name in ("quadratic", "xgboost"):
        source = config.baseline.output_directory / name / "model.joblib"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(f"original {name}".encode())
    expected = _freeze_baselines(config, None)
    for name in expected:
        (config.baseline.output_directory / name / "model.joblib").write_bytes(b"retrained")
    assert _freeze_baselines(config, expected) == expected
    assert config.frozen_baseline_model("quadratic").read_bytes() == b"original quadratic"


def test_changed_run_local_snapshot_is_rejected(optimized_config: OptimizedConfig) -> None:
    expected = _freeze_baselines(optimized_config, None)
    optimized_config.frozen_baseline_model("quadratic").write_bytes(b"changed snapshot")
    with pytest.raises(ValueError, match="Frozen baseline quadratic changed"):
        _freeze_baselines(optimized_config, expected)


def test_inspector_does_not_change_forecasts_or_expose_future_reports(demo_service: DemoService) -> None:
    plain = demo_service.snapshot("decision", "combined_15_0.5nm_25pct", reveal=False, verify=False)
    inspected = demo_service.snapshot("decision", "combined_15_0.5nm_25pct", reveal=False, verify=False, inspect=True)
    assert plain["inspection"] is None
    assert plain["cards"] == inspected["cards"]
    assert inspected["inspection"]["audience_only"]
    for report in inspected["inspection"]["records"]:
        assert pd.Timestamp(report["time"]) <= pd.Timestamp(inspected["decision_time"])
        assert pd.Timestamp(report["delivered_time"]) <= pd.Timestamp(inspected["decision_time"])
    assert inspected["reference_arrival"] is None
    assert all("error_minutes" not in card for card in inspected["cards"])


def test_inspector_recovers_original_coordinates_and_counts_every_copy(
    optimized_config: OptimizedConfig, vessel_reports: pd.DataFrame,
) -> None:
    scenario = Scenario("all_bad", Condition.QUALITY, offset_nautical_miles=.5,
                        affected_fraction=1, repetition=3, repetition_jitter_meters=.1)
    stream = create_stream(vessel_reports, scenario, 4201, optimized_config.baseline.gate)
    available = stream.available(vessel_reports["time"].iloc[15])
    inspection = inspect_feed(stream, available, optimized_config.baseline.gate, 30)
    counts = feed_counts(available, 30, 60)
    assert counts["received_in_window"] == 48
    assert inspection["affected_in_window"] == 48
    assert counts["unique_in_window"] == 48
    assert counts["occupied_bins"] == 16
    for report in inspection["records"]:
        original = vessel_reports.loc[vessel_reports["time"].eq(report["time"])].iloc[0]
        assert report["original_longitude"] == pytest.approx(original["longitude"], abs=1e-12)
        assert report["original_latitude"] == pytest.approx(original["latitude"], abs=1e-12)
        assert report["offset_meters"] == pytest.approx(926, abs=.3)


def test_demo_exposes_existing_volume_presets_and_preserves_shared_duplicate_treatment(demo_service: DemoService) -> None:
    choices = demo_service.catalog()["scenario_options"]
    assert {row["affected_fraction"] for row in choices if row["group"] == "prevalence"} == {.1, .25, .5}
    original = demo_service.snapshot("decision", "reference_volume_1", reveal=False, verify=False)
    repeated = demo_service.snapshot("decision", "reference_volume_5", reveal=False, verify=False, inspect=True)
    assert original["cards"] == repeated["cards"]
    assert repeated["feed_counts"]["received_in_window"] == 5 * original["feed_counts"]["received_in_window"]
    assert repeated["feed_counts"]["unique_in_window"] == original["feed_counts"]["unique_in_window"]
    assert repeated["inspection"]["affected_in_window"] == 0


def test_saved_timeline_hides_future_decisions_outcomes_and_other_seeds(tmp_path: Path) -> None:
    directory = tmp_path / "results" / "evaluation_primary"
    directory.mkdir(parents=True)
    rows = []
    for seed in (4201, 4202):
        for minute in (10, 20):
            rows.append({"approach_id": "voyage", "decision_id": str(minute),
                         "decision_time": f"2024-04-08 12:{minute}:00", "system": "C",
                         "scenario": "nominal", "seed": seed, "available": True,
                         "predicted_arrival_time": "2024-04-08 12:30:00", "error_minutes": -5})
    pd.DataFrame(rows).to_csv(directory / "predictions.csv", index=False)
    evidence = EvaluationEvidence(tmp_path, 4201)
    hidden = evidence.timeline("voyage", "nominal", pd.Timestamp("2024-04-08 12:15"), reveal=False)
    assert len(hidden["points"]) == 1
    assert hidden["points"][0]["decision_id"] == "10"
    assert "error_minutes" not in hidden["points"][0]
    revealed = evidence.timeline("voyage", "nominal", pd.Timestamp("2024-04-08 12:15"), reveal=True)
    assert revealed["points"][0]["error_minutes"] == -5


def test_unknown_scenario_is_rejected_before_timeline_file_reads(demo_service: DemoService) -> None:
    with pytest.raises(ValueError, match="Unknown predeclared"):
        demo_service.timeline("decision", "invented_attack", reveal=False)


def test_failure_examples_use_c_and_the_live_seed_instead_of_all_model_extremes(tmp_path: Path) -> None:
    directory = tmp_path / "results" / "evaluation_primary"
    directory.mkdir(parents=True)
    base = {"approach_id": "voyage", "decision_id": "decision", "decision_time": "2024-04-08 12:10",
            "system": "C", "scenario": "nominal", "seed": 4201, "available": True,
            "predicted_arrival_time": "2024-04-08 12:30", "error_minutes": 30}
    pd.DataFrame([base, {**base, "system": "A", "error_minutes": 1000},
                  {**base, "seed": 4202, "error_minutes": 900}]).to_csv(directory / "predictions.csv", index=False)
    examples = EvaluationEvidence(tmp_path, 4201).failure_examples()
    assert len(examples) == 1
    assert examples[0]["seed"] == 4201
    assert examples[0]["error_minutes"] == 30


def test_empty_delayed_stream_has_honest_zero_inspection_counts(demo_service: DemoService) -> None:
    demo_service.dataset.decisions.loc[:, "decision_time"] = pd.Timestamp("2024-03-05 12:01")
    snapshot = demo_service.snapshot("decision", "stale_15", reveal=False, verify=False, inspect=True)
    assert snapshot["feed_counts"]["received_in_window"] == 0
    assert snapshot["inspection"]["records"] == []
    assert snapshot["inspection"]["actual_affected_share"] is None
    assert all(not card["available"] for card in snapshot["cards"])


def test_reporting_gap_pairs_same_reference_and_hides_future_audit(demo_service: DemoService) -> None:
    config = ReportingGapConfig(pd.Timestamp("2024-03-05 12:10"), pd.Timestamp("2024-03-05 12:20"))
    result = demo_service.reporting_gap_snapshot("decision", config, reveal=True, inspect=True)
    original, attacked = result["original"], result["attacked"]
    assert original["reference_arrival"] == attacked["reference_arrival"]
    assert original["decision_time"] == attacked["decision_time"]
    assert len(attacked["cards"]) == 3
    assert attacked["received_history"][-1]["time"] == "2024-03-05T12:09:00"
    assert attacked["attack"]["withheld_reports_so_far"] == 6
    assert all(row["time"] <= attacked["decision_time"] for row in attacked["attack"]["inspection"]["records"])
    assert all(card["review_reason"] == "attack_not_calibrated_requires_review" for card in attacked["cards"])
    assert attacked["inspection"] is None
    assert "attack" not in original


def test_reporting_gap_full_outage_has_no_forecasts_and_reveal_is_optional(demo_service: DemoService) -> None:
    config = ReportingGapConfig(pd.Timestamp("2024-03-05 11:00"), pd.Timestamp("2024-03-05 13:00"))
    result = demo_service.reporting_gap_snapshot("decision", config)
    assert result["attacked"]["reference_arrival"] is None
    assert result["attacked"]["attack"]["inspection"] is None
    assert all(not card["available"] and "error_minutes" not in card for card in result["attacked"]["cards"])


def test_reporting_gap_does_not_silently_combine_other_experiments(demo_service: DemoService) -> None:
    attack = ReportingGapAttack(ReportingGapConfig(pd.Timestamp("2024-03-05 12:10"), pd.Timestamp("2024-03-05 12:20")))
    with pytest.raises(ValueError, match="Standalone"):
        demo_service.snapshot("decision", "stale_15", reveal=False, verify=False, attack=attack)
    with pytest.raises(ValueError, match="Standalone"):
        demo_service.snapshot("decision", "nominal", reveal=False, verify=True, attack=attack)


def test_missing_speed_replay_preserves_positions_and_handles_all_missing_speed(demo_service: DemoService) -> None:
    pair = demo_service.missing_speed_snapshot('decision', MissingSpeedConfig(1), reveal=True, inspect=True)
    original, attacked = pair['original'], pair['attacked']
    assert original['reference_arrival'] == attacked['reference_arrival']
    assert original['feed_counts']['received_total'] == attacked['feed_counts']['received_total']
    assert attacked['attack']['withheld_reports_so_far'] == 0
    assert attacked['attack']['injected_missing_speed_reports_so_far'] == len(attacked['received_history'])
    assert all(row['sog'] is None for row in attacked['received_history'])
    assert all(card['available'] for card in attacked['cards'])
    assert all(row['time'] <= attacked['decision_time'] for row in attacked['attack']['inspection']['records'])
    assert all(row['action'] == 'speed_removed' for row in attacked['attack']['inspection']['records'])


def test_missing_course_replay_uses_missing_angles_without_dropping_reports(demo_service: DemoService) -> None:
    pair = demo_service.missing_course_snapshot('decision', MissingCourseConfig(1), reveal=True, inspect=True)
    original, attacked = pair['original'], pair['attacked']
    assert original['reference_arrival'] == attacked['reference_arrival']
    for before, after in zip(original['received_history'], attacked['received_history']):
        assert after['cog'] is None
        assert {k: v for k, v in before.items() if k != 'cog'} == {k: v for k, v in after.items() if k != 'cog'}
    assert all(card['available'] for card in attacked['cards'])
    assert attacked['attack']['withheld_reports_so_far'] == 0
    assert attacked['attack']['injected_missing_speed_reports_so_far'] == 0
    assert attacked['attack']['injected_missing_course_reports_so_far'] == len(attacked['received_history'])
    assert all(row['time'] <= attacked['decision_time'] for row in attacked['attack']['inspection']['records'])
    assert all(row['action'] == 'course_removed' for row in attacked['attack']['inspection']['records'])


def test_missing_vessel_class_retains_reports_and_calculates_eta(demo_service: DemoService) -> None:
    from attacks import MissingVesselClassConfig

    pair = demo_service.missing_vessel_class_snapshot('decision', MissingVesselClassConfig(1), reveal=True, inspect=True)
    original, attacked = pair['original'], pair['attacked']
    assert original['reference_arrival'] == attacked['reference_arrival']
    assert original['decision_time'] == attacked['decision_time']
    assert original['feed_counts'] == attacked['feed_counts']
    assert all(card['available'] and card['error_minutes'] is not None for card in attacked['cards'])
    for before, after in zip(original['received_history'], attacked['received_history']):
        assert after['vessel_type'] is None
        assert {key: value for key, value in before.items() if key != 'vessel_type'} == {
            key: value for key, value in after.items() if key != 'vessel_type'}
    assert 'classification_filter' not in attacked['attack']
    assert attacked['attack']['injected_missing_vessel_class_reports_so_far'] == original['feed_counts']['received_total']
    assert all(row['time'] <= attacked['decision_time'] for row in attacked['attack']['inspection']['records'])
    assert all(row['action'] == 'vessel_class_removed' for row in attacked['attack']['inspection']['records'])
    hidden = demo_service.missing_vessel_class_snapshot('decision', MissingVesselClassConfig(1))['attacked']
    assert hidden['reference_arrival'] is None and hidden['attack']['inspection'] is None
    assert all('error_minutes' not in card for card in hidden['cards'])


def test_missing_vessel_class_zero_mask_matches_nominal_and_audit_cannot_change_cards(demo_service: DemoService) -> None:
    from attacks import MissingVesselClassConfig

    pair = demo_service.missing_vessel_class_snapshot('decision', MissingVesselClassConfig(0), reveal=True, inspect=True)
    assert pair['original']['received_history'] == pair['attacked']['received_history']
    assert [card['predicted_arrival_time'] for card in pair['original']['cards']] == [card['predicted_arrival_time'] for card in pair['attacked']['cards']]
    plain = demo_service.missing_vessel_class_snapshot('decision', MissingVesselClassConfig(.5), reveal=True)['attacked']
    inspected = demo_service.missing_vessel_class_snapshot('decision', MissingVesselClassConfig(.5), reveal=True, inspect=True)['attacked']
    assert plain['cards'] == inspected['cards']
    assert inspected['attack']['injected_missing_vessel_class_reports_so_far'] > 0


def test_fleet_keeps_delivery_cutoff_and_retrospective_truth_outside_inference(demo_service, monkeypatch):
    from Optimized_Model.fleet import FleetReplay, epoch
    monkeypatch.setattr(FleetReplay, "_archive_metadata", lambda _: ({}, {"voyage": [-76.3, 37.]}))
    fleet = FleetReplay(demo_service)
    clock = epoch(pd.Timestamp("2024-03-05 12:15"))
    frame = fleet.frame(clock, delay=5, fraction=.25)
    ship = frame["ships"][0]
    assert all(report["delivered"] <= clock and report["time"] <= clock - 300 for report in ship["reports"])
    predictions = ship["predictions"]
    # Changing evaluator-only injection truth cannot change any forecast.
    for stream in fleet.streams.values():
        stream.modification_log["fault_applied"] = False
    fleet.frames.clear()
    assert fleet.frame(clock, delay=5, fraction=.25)["ships"][0]["predictions"] == predictions
    history = fleet.history(clock, delay=5, fraction=.25)
    assert all(sample["time"] <= clock for sample in history["samples"])
    fading = fleet.frame(epoch(pd.Timestamp("2024-03-05 12:47")))["ships"][0]
    assert fading["arrived"] and fading["fade"] == .75
    assert not fleet.frame(epoch(pd.Timestamp("2024-03-05 12:54")))["ships"]


def test_fleet_rejects_unbounded_or_nonfinite_controls():
    from Optimized_Model.fleet import FleetReplay
    for controls in [(float("nan"), 0, .5), (61, 0, .5), (0, 1.1, .5), (0, .25, 3)]:
        with pytest.raises(ValueError):
            FleetReplay.scenario(*controls)


def test_legacy_schema_migration_does_not_accept_unreviewed_inference_edits():
    from Optimized_Model.evaluation import compatible_inference, LEGACY_SCHEMA_MIGRATION
    saved = {path: pair[0] for path, pair in LEGACY_SCHEMA_MIGRATION.items()}
    current = {path: pair[1] for path, pair in LEGACY_SCHEMA_MIGRATION.items()}
    assert compatible_inference(saved, current, list(LEGACY_FEATURE_COLUMNS))
    assert not compatible_inference(saved, current, list(FEATURE_COLUMNS))
    current["eta_baselines/features.py"] = "unreviewed-change"
    assert not compatible_inference(saved, current, list(LEGACY_FEATURE_COLUMNS))

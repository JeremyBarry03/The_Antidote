"""Dashboard contract, causal comparisons and existing-server integration."""

import json
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression

from eta_baselines.fitting import fit_imputer
from eta_baselines.prediction import EtaPredictor
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.dataset import ReplayDataset
from Optimized_Model.evaluation import PredictionSystem
from Optimized_Model.features import OptimizedFeatures
from Optimized_Model.fleet import ATTACK_CONTROLS, FleetService, poisoning_settings, unix_seconds
from Optimized_Model.fleet_analysis import FleetAnalysis
from Optimized_Model.service import DemoService, _json_value


@pytest.fixture
def fleet() -> FleetService:
    config = OptimizedConfig.load(Path(__file__).resolve().parents[1] / "Optimized_Model/config_vessel_class_v2.json")
    times = pd.date_range("2024-04-09 12:00", periods=40, freq="min")
    history = pd.DataFrame({"mmsi": "123456789", "time": times, "longitude": -76.20 - np.arange(40) * .002,
                            "latitude": 37., "sog": 10 + np.arange(40) / 10, "cog": 270., "vessel_type": 70.})
    decisions = pd.DataFrame({"approach_id": ["voyage"], "mmsi": ["123456789"],
        "decision_id": ["first"], "decision_time": [times[15]], "arrival_time": [times[-1] + pd.Timedelta(minutes=1)],
        "crossing_before": [times[-1]], "crossing_after": [times[-1] + pd.Timedelta(minutes=2)], "split": ["evaluation"]})
    training = pd.DataFrame({"speed_knots": [0., 10., 20.]})
    imputer = fit_imputer(training, ("speed_knots",))
    regressor = LinearRegression().fit(training.to_numpy(), [60., 40., 20.])
    systems = [PredictionSystem(name, EtaPredictor(name, imputer, regressor, ("speed_knots",), "decision"),
                                "guarded" if name == "C" else "raw") for name in ("A", "B", "C")]
    return FleetService(config, ReplayDataset(decisions, {"voyage": history}, {}), systems,
                        OptimizedFeatures(config.baseline, config.guard))


def test_catalog_and_clean_frame_use_current_clock_and_null_attacked_arm(fleet):
    catalog = fleet.catalog()
    frame = fleet.frame(catalog["initial_time"] + 30, {})
    ship = frame["ships"][0]
    assert catalog["start"] < catalog["initial_time"] < catalog["end"]
    assert len(catalog["attack_controls"]) == 8
    assert ship["prediction_time"] == frame["time"]
    assert ship["poisoned_predictions"] is None and not frame["poisoning_active"]
    assert set(ship["predictions"]) == {"A", "B", "C"}
    assert ship["crossing_position"] is None and not ship["arrived"]
    assert all(report["time"] <= frame["time"] and report["delivered"] <= frame["time"] for report in ship["reports"])
    assert len({r["record_id"] for r in ship["reports"]}) == len(ship["reports"])
    json.dumps(_json_value(frame), allow_nan=False)


def test_dashboard_evaluation_window_is_complete_and_rejects_outside_clocks(fleet):
    dashboard = FleetService(fleet.config, fleet.dataset, fleet.systems, fleet.extractor, evaluation_only=True)
    catalog = dashboard.catalog()
    assert catalog["start"] == unix_seconds(pd.Timestamp(fleet.config.evaluation_start))
    assert catalog["end"] == unix_seconds(pd.Timestamp(fleet.config.evaluation_end) - pd.Timedelta(minutes=1))
    with pytest.raises(ValueError):
        dashboard.frame(catalog["start"] - 1, {})
    with pytest.raises(ValueError):
        dashboard.frame(catalog["end"] + 60, {})


def test_dashboard_never_falls_back_to_exploratory_records(fleet):
    fleet.dataset.decisions["split"] = "exploratory"
    with pytest.raises(ValueError, match="evaluation set"):
        FleetService(fleet.config, fleet.dataset, fleet.systems, fleet.extractor, evaluation_only=True)


@pytest.mark.parametrize("control", [control["id"] for control in ATTACK_CONTROLS])
def test_every_control_runs_all_models_without_mutating_source(fleet, control):
    source = fleet.dataset.histories["voyage"].copy(deep=True)
    time = fleet.catalog()["initial_time"]
    clean = fleet.frame(time, {})["ships"][0]
    attacked = fleet.frame(time, {control: 60 if control == "reporting_gap" else 100})["ships"][0]
    assert attacked["nominal_predictions"] == clean["predictions"]
    assert attacked["nominal_predictions"] is not attacked["poisoned_predictions"]
    assert set(attacked["poisoned_predictions"]) == {"A", "B", "C"}
    assert attacked["comparison_inputs"]["withheld_reports"] + attacked["comparison_inputs"]["modified_reports"] > 0
    pd.testing.assert_frame_equal(fleet.dataset.histories["voyage"], source)
    json.dumps(_json_value(attacked), allow_nan=False)


def test_clean_and_attacked_predictions_are_independently_computed(fleet):
    ship = fleet.frame(fleet.catalog()["initial_time"], {"missing_speed": 100})["ships"][0]
    assert ship["nominal_predictions"]["B"]["eta"] != ship["poisoned_predictions"]["B"]["eta"]
    for model in ("A", "B", "C"):
        predicted = ship["predictions"][model]
        assert predicted["error"] == pytest.approx((predicted["eta"] - ship["arrival"]) / 60)


def test_composed_attacks_keep_display_audit_out_of_inference(fleet, monkeypatch):
    from Optimized_Model import fleet as module
    original = module.view_row
    captured = []

    def capture(reports, decision, extractor):
        captured.append(reports.copy())
        return original(reports, decision, extractor)

    monkeypatch.setattr(module, "view_row", capture)
    time = fleet.catalog()["initial_time"]
    settings = {control["id"]: 60 if control["id"] == "reporting_gap" else 100 for control in ATTACK_CONTROLS}
    first = _json_value(fleet.frame(time, settings))
    assert first == _json_value(fleet.frame(time, settings))
    for reports in captured:
        assert not {"poisoned_fields", "original_values", "attack_names", "fault_applied", "arrival_time"} & set(reports)
    ship = first["ships"][0]
    assert ship["reports"] and ship["audit_events"]
    assert {"speed", "course", "vessel_type", "longitude", "latitude"} <= set(ship["reports"][-1]["poisoned_fields"])
    assert all(event["speed"] is None and event["longitude"] is None for event in ship["audit_events"])


def test_gap_warning_uses_observed_cadence_and_clears_when_reporting_resumes(fleet):
    time = fleet.catalog()["initial_time"]
    gap = fleet.frame(time, {"reporting_gap": 10})["ships"][0]
    assert "reporting_gap" in gap["diagnostics"]["reasons"]
    resumed = fleet.frame(time + 6 * 60, {"reporting_gap": 10})["ships"][0]
    assert "reporting_gap" not in resumed["diagnostics"]["reasons"]
    assert resumed["audit_events"]  # Past audit remains separate from current warning.


def test_future_reports_cannot_change_past_frames(fleet):
    time = fleet.catalog()["initial_time"]
    settings = {"sensor_drift": 50, "position_jump": 50, "missing_speed": 50}
    before = _json_value(fleet.frame(time, settings))
    fleet.dataset.histories["voyage"].loc[lambda frame: frame.time > pd.Timestamp(time, unit="s"), "sog"] = 50.
    fleet._stream.cache_clear()
    assert _json_value(fleet.frame(time, settings)) == before


def test_arrival_uses_original_reference_position_and_expires(fleet, monkeypatch):
    from Optimized_Model import fleet as module
    history = fleet.dataset.histories["voyage"]
    after = history.tail(1).copy()
    after["time"] += pd.Timedelta(minutes=2)
    after["longitude"] = -76.322
    after["latitude"] = 37.002
    monkeypatch.setattr(module, "load_observations", lambda source: (pd.concat([history, after]), {}))
    arrival = unix_seconds(fleet.approaches.iloc[0].arrival_time)
    clean = fleet.frame(arrival, {})["ships"][0]
    attacked = fleet.frame(arrival, {"position_jump": 100})["ships"][0]
    assert clean["arrived"] and clean["crossing_position"] == pytest.approx([-76.3, 37.001])
    assert attacked["crossing_position"] == clean["crossing_position"]
    assert not fleet.frame(fleet.catalog()["end"], {})["ships"]


@pytest.mark.parametrize("payload", [[], None, {"unknown": 1}, {"missing_speed": True},
                                    {"missing_speed": "5"}, {"missing_speed": -1},
                                    {"reporting_gap": 61}, {"position_jump": float("nan")}])
def test_rejects_invalid_poisoning_settings(payload):
    with pytest.raises(ValueError):
        poisoning_settings(payload)


@pytest.mark.parametrize("time", [float("nan"), float("inf"), -1, True])
def test_rejects_invalid_clocks(fleet, time):
    with pytest.raises(ValueError):
        fleet.frame(time, {})


def test_server_serves_dashboard_assets_and_both_api_contracts(fleet, monkeypatch):
    from http.server import HTTPServer
    from Optimized_Model import service
    ready = Queue()

    def create_server(address, handler):
        server = HTTPServer((address[0], 0), handler)
        ready.put(server)
        return server

    demo = DemoService(fleet.config, fleet.dataset, fleet.systems, fleet.extractor, None)
    monkeypatch.setattr(service, "HTTPServer", create_server)
    monkeypatch.setattr(DemoService, "load", classmethod(lambda cls, config, **kwargs: demo))
    worker = Thread(target=service.serve, args=(fleet.config, 8765), daemon=True)
    worker.start()
    server = ready.get(timeout=5)
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(root, timeout=5) as response:
            assert response.url.endswith("/tracking/") and b"app.mjs" in response.read()
        for path, content_type in (("/tracking/app.mjs", "text/javascript"),
                                   ("/tracking/mitigations.mjs", "text/javascript"),
                                   ("/tracking/style.css", "text/css"),
                                   ("/tracking/assets/geist-mono-variable.ttf", "font/ttf"),
                                   ("/eta_replay.html", "text/html")):
            with urlopen(root + path, timeout=5) as response:
                assert response.headers.get_content_type() == content_type
        for path in ("/api/fleet/catalog", "/api/catalog", "/api/config"):
            with urlopen(root + path, timeout=5) as response:
                assert isinstance(json.load(response), dict)
        query = urlencode({"time": fleet.catalog()["initial_time"], "poisoning": '{"missing_speed":100}'})
        with urlopen(root + "/api/fleet/frame?" + query, timeout=5) as response:
            assert json.load(response)["ships"][0]["poisoned_predictions"]["C"]["available"]
        options = urlencode({"time": fleet.catalog()["initial_time"], "mitigate": "false", "drift_direction": "over"})
        with urlopen(root + "/api/fleet/frame?" + options, timeout=5) as response:
            assert not json.load(response)["ships"][0]["mitigation"]["enabled"]
        def wait_for_analysis(path, params):
            with urlopen(root + path + "?" + urlencode(params), timeout=5) as response:
                state = json.load(response)
            for _ in range(100):
                if state["status"] in ("ready", "error"):
                    break
                with urlopen(root + path + "?" + urlencode({"job": state["job_id"]}), timeout=5) as response:
                    state = json.load(response)
                sleep(.02)
            assert state["status"] == "ready", state
            return state
        assert wait_for_analysis("/api/fleet/monthly", {"poisoning": "{}"})["days"]
        assert len(wait_for_analysis("/api/fleet/stress", {})["samples"]) == 5
        for path in ("/api/fleet/frame?time=NaN", "/api/fleet/frame?time=1&poisoning=[]",
                     "/api/fleet/frame?time=1&mitigate=yes", "/api/fleet/frame?time=1&trusted_fixes=1"):
            with pytest.raises(HTTPError) as error:
                urlopen(root + path, timeout=5)
            assert error.value.code == 400 and "error" in json.load(error.value)
        with pytest.raises(HTTPError) as error:
            urlopen(root + "/tracking/../.env", timeout=5)
        assert error.value.code == 404
    finally:
        server.shutdown()
        worker.join(timeout=5)


def test_monthly_analysis_and_delay_stress_match_configured_period_and_cohort(fleet):
    analysis = FleetAnalysis(fleet)
    monthly = analysis.monthly({})
    stress = analysis.stress()

    assert monthly["status"] == "ready"
    assert monthly["period_label"] == fleet.catalog()["evaluation_label"]
    assert monthly["days"] and set(monthly["days"][0]["models"]) == {"A", "B", "C"}
    assert len(stress["samples"]) == 5
    assert stress["period_label"] == monthly["period_label"]
    assert len({sample["matched_decisions"] for sample in stress["samples"]}) == 1


def test_month_analysis_attack_leaves_pre_cutover_reports_unchanged(fleet):
    cutover = fleet.dataset.histories["voyage"].time.iloc[20]
    settings = (0., 0., 0., 0., 0., 0., 100., 0.)
    nominal, changed, _ = fleet._stream("voyage", settings, attack_start=cutover)

    before_nominal = nominal.loc[nominal.time.lt(cutover)].reset_index(drop=True)
    before_changed = changed.loc[changed.time.lt(cutover)].reset_index(drop=True)
    assert before_changed.equals(before_nominal)


def test_month_analysis_gap_applies_to_approaches_after_global_cutover(fleet):
    first = fleet.dataset.histories['voyage'].time.iloc[0]
    settings = poisoning_settings({'reporting_gap': 15})
    nominal, changed, names = fleet._stream('voyage', settings, attack_start=first-pd.Timedelta(days=1))
    assert len(names) == 15
    assert len(changed) == len(nominal)-15
    assert not changed.time.between(first+pd.Timedelta(minutes=10), first+pd.Timedelta(minutes=24)).any()


def test_month_analysis_active_attack_summary_uses_compatible_utc_clocks(fleet):
    analysis = FleetAnalysis(fleet)
    analysis.cutover = pd.Timestamp('2024-04-09', tz='UTC')
    result = analysis.monthly({'reporting_gap': 15})
    assert result['status'] == 'ready'
    assert result['affected_reports'] == 15

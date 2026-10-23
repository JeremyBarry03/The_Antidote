"""HTTP smoke tests use shipped models and original replay observations."""
import json
from threading import RLock, Event
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.analysis import Analysis, AnalysisJobs
from Optimized_Model.dataset import ReplayDataset
from Optimized_Model.fleet import FleetService, poisoning_settings
from server import create_app, load_fleet


@pytest.fixture(scope="module")
def real_fleet():
    return load_fleet()


@pytest.fixture(scope="module")
def small_fleet(real_fleet):
    # A documented reduced cohort for fast tests, never a serving default.
    chosen = []
    for boundary in (pd.Timestamp("2024-03-01"), pd.Timestamp("2024-03-15")):
        eligible = real_fleet.approaches.loc[real_fleet.approaches.decision_time.ge(boundary)]
        for identity, row in eligible.iterrows():
            if row.arrival_time - row.decision_time > pd.Timedelta(minutes=31):
                chosen.append(identity)
                break
    decisions = real_fleet.dataset.decisions.loc[real_fleet.dataset.decisions.approach_id.isin(chosen)]
    decisions = decisions.sort_values("decision_time").drop_duplicates("approach_id")
    dataset = ReplayDataset(decisions, {k: real_fleet.dataset.histories[k] for k in chosen}, real_fleet.dataset.manifest)
    return FleetService(real_fleet.config, dataset, real_fleet.systems, real_fleet.extractor, evaluation_only=True)


def test_http_real_predictions_controls_causality_and_validation(real_fleet):
    with TestClient(create_app(lambda: real_fleet)) as client:
        assert client.get("/health").json() == {"status": "ok", "models_loaded": True}
        catalog = client.get("/api/fleet/catalog").json()
        clock = catalog["initial_time"] + 60
        baseline = client.get("/api/fleet/frame", params={"time": clock}).json()
        assert baseline["ships"]
        assert all(baseline["ships"][0]["predictions"][m]["available"] for m in ("A", "B", "C"))
        for control in catalog["attack_controls"]:
            reply = client.get("/api/fleet/frame", params={"time": clock, "poisoning": json.dumps({control['id']: control['maximum']})})
            assert reply.status_code == 200, reply.text
            frame = reply.json()
            for ship in frame["ships"]:
                assert ship["nominal_predictions"] == next(s for s in baseline["ships"] if s["id"] == ship["id"])["predictions"]
                assert ship["poisoned_predictions"] is not None
                assert all(r["time"] <= clock and r["delivered"] <= clock for r in ship["reports"])
                assert ship["diagnostics"]["state"] in ("ok", "review")
        assert client.get("/api/fleet/frame", params={"time": "NaN"}).status_code == 400
        assert client.get("/api/fleet/frame", params={"time": clock, "poisoning": "[]"}).status_code == 400
        assert client.get("/api/fleet/frame", params={"time": clock, "mitigate": "yes"}).status_code == 400
        assert client.get("/api/fleet/monthly?job=expired").status_code == 400
        assert client.get("/api/fleet/monthly?poisoning=broken").status_code == 400
        assert client.get("/not-found").json() == {"error": "Not Found"}


def test_missing_bundle_and_public_token(monkeypatch):
    def unavailable():
        raise FileNotFoundError("missing artifact")
    monkeypatch.setenv("MAPBOX_PUBLIC_TOKEN", "sk.do-not-expose")
    with TestClient(create_app(unavailable)) as client:
        assert client.get("/health").status_code == 503
        assert client.get("/api/fleet/catalog").status_code == 503
        assert client.get("/api/config").json()["mapbox_public_token"] is None


def test_async_analysis_six_chart_contract_on_real_reduced_cohort(small_fleet):
    with TestClient(create_app(lambda: small_fleet)) as client:
        params = {"poisoning": json.dumps({"missing_speed": 100}), "client": "smoke"}
        started = client.get("/api/fleet/monthly", params=params)
        assert started.status_code == 202
        job = started.json()["job_id"]
        assert client.get("/api/fleet/monthly", params=params).json()["job_id"] == job
        deadline = time.monotonic() + 180
        progress = 0
        while time.monotonic() < deadline:
            result = client.get("/api/fleet/monthly", params={"job": job}).json()
            assert result["completed"] >= progress
            progress = result["completed"]
            if result["status"] in ("ready", "error"):
                break
            time.sleep(.1)
        assert result["status"] == "ready", result
        assert result["completed"] == result["total"] == 64
        assert len(result["days"]) == 31
        assert len(result["sequence"]["samples"]) == 31
        assert len(result["convergence"]["samples"]) == 12
        assert len(result["insights"]["stability"]["samples"]) == 7
        assert set(result["insights"]["impact"]["models"]) == {"A", "B", "C"}
        for day in result["days"]:
            if day["day"] < result["cutover"]:
                for model in ("A", "B", "C"):
                    assert day["models"][model]["mae"] == day["models"][model]["clean_mae"]
        started = client.get("/api/fleet/stress")
        assert started.status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            stress = client.get("/api/fleet/stress").json()
            if stress["status"] in ("ready", "error"):
                break
            time.sleep(.1)
        assert stress["status"] == "ready", stress
        assert [s["minute"] for s in stress["samples"]] == [0, 2, 5, 10, 15]
        assert len({s["matched_decisions"] for s in stress["samples"]}) == 1
        json.dumps(stress, allow_nan=False)


def test_analysis_cutover_preserves_old_reports(small_fleet):
    analysis = Analysis(small_fleet, RLock(), lambda *_: None, Event())
    for identity in small_fleet.approaches.index:
        clean, scenario, count = analysis.streams(identity, poisoning_settings({"position_jump": 100}))
        pd.testing.assert_frame_equal(clean.loc[clean.time.lt(analysis.cutover)].reset_index(drop=True),
                                      scenario.loc[scenario.time.lt(analysis.cutover)].reset_index(drop=True))


def test_failed_jobs_are_retryable_and_queue_bounded(small_fleet, monkeypatch):
    def broken(self, payload):
        raise RuntimeError("test failure")
    monkeypatch.setattr(Analysis, "monthly", broken)
    jobs = AnalysisJobs(small_fleet, RLock(), capacity=1)
    try:
        first = jobs.monthly({}, "test")
        deadline = time.monotonic() + 5
        while jobs.poll(first["job_id"])["status"] != "error" and time.monotonic() < deadline:
            time.sleep(.01)
        assert jobs.poll(first["job_id"])["status"] == "error"
        assert jobs.monthly({}, "test")["job_id"] != first["job_id"]
    finally:
        jobs.close()

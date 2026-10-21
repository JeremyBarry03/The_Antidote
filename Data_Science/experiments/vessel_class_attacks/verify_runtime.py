"""Check the corrected saved A/B/C models through the actual class-attack API."""

import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import numpy as np
import pandas as pd

SCIENCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCIENCE))

from attacks import MissingVesselClassAttack, MissingVesselClassConfig
from eta_baselines.dataset import file_digest
from eta_baselines.features import VESSEL_CLASS_COLUMNS
from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.service import DemoService


def get_json(url: str) -> dict:
    with urlopen(url, timeout=30) as response:
        return json.load(response)


def main() -> None:
    config_path = SCIENCE/"Optimized_Model/config_vessel_class_v2.json"
    config = OptimizedConfig.load(config_path)
    service = DemoService.load(config)
    systems = [system for system in service.systems if system.name in ("A", "B", "C")]
    assert len(systems) == 3
    assert all(set(VESSEL_CLASS_COLUMNS) <= set(system.predictor.feature_columns) for system in systems)
    service_path = SCIENCE/"Optimized_Model/service.py"
    service_hash = file_digest(service_path)
    cases = {}
    for identity, group in service.dataset.partition("evaluation").groupby("approach_id", sort=False):
        decision = group.sort_values("decision_time").iloc[len(group)//2]
        history = service.dataset.histories[identity]
        available = history.loc[history.time <= decision.decision_time]
        label = "tanker" if 80 <= available.vessel_type.iloc[-1] <= 89 else "cargo"
        cases.setdefault(label, (decision, history))
        if len(cases) == 2:
            break
    assert set(cases) == {"cargo", "tanker"}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    output = Path(__file__).resolve().parent/"results_vessel_class_v2"
    log_path = config.output_directory/"runtime_validation_server.log"
    requests = forecasts = unknown_checks = 0
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "Optimized_Model", "serve", "--config", str(config_path), "--port", str(port)],
            cwd=SCIENCE, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic()+45
            while True:
                try:
                    get_json(base+"/api/catalog")
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError(f"Validation server did not start. See {log_path}")
                    time.sleep(.2)
            for decision, history in cases.values():
                for unit in ("report", "vessel"):
                    for fraction in (0., .1, .25, .5, 1.):
                        attack = MissingVesselClassAttack(MissingVesselClassConfig(fraction, 4201, selection_unit=unit))
                        query = urlencode(dict(decision=decision.decision_id, affected_fraction=fraction,
                            seed=4201, selection_unit=unit, reveal="true", inspect="true"))
                        payload = get_json(f"{base}/api/attacks/missing-vessel-class?{query}")
                        requests += 1
                        original, attacked = payload["original"], payload["attacked"]
                        assert original["feed_counts"] == attacked["feed_counts"]
                        assert original["decision_time"] == attacked["decision_time"]
                        assert "classification_filter" not in attacked["attack"]
                        received = attack.apply(history).available(decision.decision_time)
                        assert attacked["feed_counts"]["received_total"] == len(received)
                        cards = {card["system"]: card for card in attacked["cards"]}
                        assert set(cards) == {"A", "B", "C"}
                        for system in systems:
                            inputs, _ = service.extractor.snapshot(received, decision.decision_time,
                                guarded=system.input_view == "guarded")
                            prediction = system.predictor.predict(inputs).iloc[0]
                            api = cards[system.name]
                            assert api["predicted_arrival_time"] is not None
                            np.testing.assert_allclose(api["predicted_remaining_minutes"],
                                prediction.predicted_remaining_minutes, rtol=0, atol=1e-7)
                            difference = abs(pd.Timestamp(api["predicted_arrival_time"])-prediction.predicted_arrival_time)
                            assert difference <= pd.Timedelta(microseconds=1)
                            forecasts += 1
                            if fraction == 1.:
                                vector = system.predictor.imputer.transform(inputs[list(system.predictor.feature_columns)])[0]
                                positions = [system.predictor.feature_columns.index(column) for column in VESSEL_CLASS_COLUMNS]
                                np.testing.assert_array_equal(vector[positions], [0., 0., 1.])
                                unknown_checks += 1
                        if fraction == 1.:
                            assert all(row["vessel_type"] is None for row in attacked["received_history"])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    assert service_hash == file_digest(service_path)
    result = dict(configuration=str(config_path), systems=[system.name for system in systems],
        paired_http_requests=requests, attacked_forecasts_matched=forecasts,
        post_imputation_unknown_checks=unknown_checks, fractions=[0., .1, .25, .5, 1.],
        selection_units=["report", "vessel"], original_class_cohorts=list(cases),
        every_received_report_retained=True, clocks_preserved=True, no_class_filter=True,
        full_removal_raw_class_is_null=True, all_saved_models_load_with_current_inference=True,
        service_code_unchanged=True, validation_server_stopped=process.poll() is not None,
        calibration="New runtime is uncalibrated; historical review envelopes are not reused")
    (output/"api_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

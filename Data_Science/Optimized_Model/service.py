"""Local replay API; verified updates are explicit, logged human-assisted actions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd

from .calibration import apply_review, load_calibration
from .configuration import OptimizedConfig
from .dataset import ReplayDataset, load_replay
from .evaluation import PredictionSystem, load_systems, predict_systems
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from .replay import create_stream
from .scenarios import primary_scenarios
from .views import view_row

logger = logging.getLogger(__name__)


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


@dataclass
class DemoService:
    config: OptimizedConfig
    dataset: ReplayDataset
    systems: list[PredictionSystem]
    extractor: OptimizedFeatures
    calibration: dict[str, object] | None

    @classmethod
    def load(cls, config: OptimizedConfig) -> "DemoService":
        calibration = load_calibration(config) if (config.output_directory / "calibration.json").exists() else None
        return cls(config, load_replay(config), load_systems(config),
                   OptimizedFeatures(config.baseline, config.guard), calibration)

    def catalog(self) -> dict[str, object]:
        split = "evaluation" if len(self.dataset.partition("evaluation")) else "exploratory"
        decisions = self.dataset.partition(split)
        approaches = []
        for identity, group in decisions.groupby("approach_id", sort=False):
            approaches.append({"id": identity, "decisions": [
                {"id": row.decision_id, "time": row.decision_time.isoformat()}
                for row in group.itertuples()
            ]})
        return {"approaches": approaches, "scenarios": [scenario.name for scenario in primary_scenarios()],
                "split": split, "calibrated": self.calibration is not None,
                "gate": {"longitude": self.config.baseline.gate.longitude,
                         "south": self.config.baseline.gate.south_latitude,
                         "north": self.config.baseline.gate.north_latitude}}

    def snapshot(self, decision_id: str, scenario_name: str, *, reveal: bool, verify: bool) -> dict[str, object]:
        selected = self.dataset.decisions.loc[self.dataset.decisions["decision_id"] == decision_id]
        if len(selected) != 1:
            raise ValueError("Unknown or ambiguous replay decision.")
        decision = selected.iloc[0]
        choices = {scenario.name: scenario for scenario in primary_scenarios()}
        if scenario_name not in choices:
            raise ValueError("Unknown predeclared replay scenario.")
        reports = self.dataset.histories[decision["approach_id"]]
        stream = create_stream(reports, choices[scenario_name], 1042, self.config.baseline.gate)
        available = stream.available(decision["decision_time"])
        verified_time = None
        if verify:
            verified = reports.loc[reports["time"] <= decision["decision_time"]].tail(1).copy()
            if verified.empty:
                raise ValueError("No historical update exists before this decision.")
            verified_time = verified["time"].iloc[0]
            available = available.loc[available["time"] != verified_time]
            verified["delivered_time"] = decision["decision_time"]
            verified["record_id"] = "simulated-verified-update"
            available = pd.concat([available, verified], ignore_index=True)
        row = decision.to_dict()
        row.update(view_row(available, decision, self.extractor))
        row.update({"scenario": scenario_name, "condition": choices[scenario_name].condition.value, "seed": 1042})
        frame = pd.DataFrame([row])
        for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
            if column not in frame:
                frame[column] = np.nan
        for column in ("observation_time", "raw_observation_time"):
            if column not in frame:
                frame[column] = pd.NaT
        predictions = predict_systems(frame, [system for system in self.systems if system.name in ("A", "B", "C")])
        if self.calibration is not None:
            predictions = apply_review(predictions, self.calibration, self.config)
        cards = []
        for prediction in predictions.to_dict(orient="records"):
            fields = ("system", "available", "predicted_arrival_time", "predicted_remaining_minutes",
                      "report_age_minutes", "interval_half_width_minutes", "calibration_approaches",
                      "review_reason", "accepted", "reasons", "guard_received_count", "guard_removed_count")
            card = {key: prediction.get(key) for key in fields}
            if self.calibration is None:
                card["review_reason"] = "not_calibrated_requires_review"
                card["accepted"] = False
            if reveal:
                card["error_minutes"] = prediction["error_minutes"]
            cards.append(card)
        result = {
            "decision_time": decision["decision_time"], "cards": cards,
            "received_history": available[["time", "longitude", "latitude", "sog"]].tail(150).to_dict(orient="records"),
            "human_assisted": verify, "verified_observation_time": verified_time,
            "reference_arrival": decision["arrival_time"] if reveal else None,
            "reference_bracket": [decision["crossing_before"], decision["crossing_after"]] if reveal else None,
        }
        return _json_value(result)

    def record_verification(self, decision_id: str, scenario_name: str, review_seconds: float) -> None:
        if not np.isfinite(review_seconds) or not 0 <= review_seconds <= 86400:
            raise ValueError("Review duration must be finite and between zero and one day.")
        entry = {"entered_at": datetime.now(timezone.utc).isoformat(), "decision_id": decision_id,
                 "scenario": scenario_name, "source": "simulated historical verification",
                 "human_review_seconds": review_seconds, "human_assisted": True}
        path = self.config.output_directory / "human_verification.jsonl"
        with path.open("a", encoding="utf-8") as destination:
            destination.write(json.dumps(entry) + "\n")

    def metrics(self) -> dict[str, object]:
        directory = self.config.output_directory / "results" / "evaluation_primary"
        summary = directory / "condition_summary.csv"
        if not summary.exists():
            return {"available": False, "message": "Protected evaluation has not been completed."}
        result = {"available": True, "status": json.loads((directory / "status.json").read_text()),
                  "summary": pd.read_csv(summary).to_dict(orient="records"),
                  "paired_comparisons": pd.read_csv(directory / "paired_uncertainty.csv").to_dict(orient="records")}
        review = directory / "review_summary.csv"
        result["review"] = pd.read_csv(review).to_dict(orient="records") if review.exists() else []
        return _json_value(result)


def serve(config: OptimizedConfig, port: int) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Choose a local port between 1024 and 65535.")
    service = DemoService.load(config)
    page = Path(__file__).resolve().parents[2] / "Frontend" / "eta_replay.html"

    class ReplayRequest(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: object) -> None:
            body = json.dumps(_json_value(payload), allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            request = urlparse(self.path)
            try:
                if request.path == "/":
                    body = page.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif request.path == "/api/catalog":
                    self._send(200, service.catalog())
                elif request.path == "/api/metrics":
                    self._send(200, service.metrics())
                elif request.path == "/api/replay":
                    query = parse_qs(request.query)
                    self._send(200, service.snapshot(query.get("decision", [""])[0],
                        query.get("scenario", ["nominal"])[0],
                        reveal=query.get("reveal", ["false"])[0] == "true", verify=False))
                else:
                    self._send(404, {"error": "Unknown route."})
            except (ValueError, KeyError) as error:
                self._send(400, {"error": str(error)})

        def do_POST(self) -> None:
            if self.path != "/api/verify":
                self._send(404, {"error": "Unknown route."})
                return
            # The service binds loopback and accepts only its own browser origin.
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
            if origin not in allowed:
                self._send(403, {"error": "Verification requires the local replay page."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    raise ValueError("Invalid verification request length.")
                payload = json.loads(self.rfile.read(length))
                result = service.snapshot(payload["decision"], payload["scenario"], reveal=False, verify=True)
                service.record_verification(payload["decision"], payload["scenario"], float(payload["review_seconds"]))
                self._send(200, result)
            except (ValueError, KeyError, TypeError) as error:
                self._send(400, {"error": str(error)})

        def log_message(self, message: str, *args: object) -> None:
            logger.info(message, *args)

    logger.info("Replay available at http://127.0.0.1:%s (Ctrl+C to stop)", port)
    with HTTPServer(("127.0.0.1", port), ReplayRequest) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logger.info("Replay stopped")

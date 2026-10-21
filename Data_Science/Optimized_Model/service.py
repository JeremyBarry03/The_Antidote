"""Local replay API; verified updates are explicit, logged human-assisted actions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
from dotenv import dotenv_values

from attacks import (BaseAttack, MissingCourseAttack, MissingCourseConfig,
                     MissingSpeedAttack, MissingSpeedConfig, MissingVesselClassAttack, MissingVesselClassConfig,
                     ReportingGapAttack, ReportingGapConfig, SensorDeteriorationAttack, SensorDeteriorationConfig,
                     PositionJumpAttack, PositionJumpConfig)

from .calibration import apply_review, load_calibration
from .configuration import OptimizedConfig
from .dataset import ReplayDataset, load_replay
from .evaluation import PredictionSystem, load_systems, predict_systems
from .features import OPTIMIZED_COLUMNS, RICH_COLUMNS, OptimizedFeatures
from .presentation import EvaluationEvidence, VISIBLE_REPORT_LIMIT, demo_scenarios, feed_counts, inspect_feed, scenario_options
from .replay import create_stream
from .scenarios import primary_scenarios
from .sensor_deterioration import deterioration_options, deterioration_presets, inspect_deterioration
from .position_jump import position_jump_options, position_jump_presets, inspect_position_jump
from .views import view_row

logger = logging.getLogger(__name__)
FRONTEND_DIRECTORY = Path(__file__).resolve().parents[2] / "Frontend"
MAPBOX_ENV_FILE = FRONTEND_DIRECTORY.parent / ".env"
MAPBOX_TOKEN_KEYS = ("MAPBOX_PUBLIC_TOKEN", "MAPBOX_TOKEN")
ASSET_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def load_mapbox_public_token(env_file: Path) -> str | None:
    """Read local configuration without changing the process environment.

    Explicit environment settings take precedence over the repository's .env.
    Secret tokens are never exposed by the browser configuration endpoint.
    """
    local_settings = dotenv_values(env_file, interpolate=False, encoding="utf-8-sig") if env_file.is_file() else {}
    for source in (os.environ, local_settings):
        for key in MAPBOX_TOKEN_KEYS:
            value = source.get(key)
            if value and value.strip():
                token = value.strip()
                return token if token.startswith("pk.") else None
    return None


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
    _evidence: EvaluationEvidence | None = field(default=None, init=False, repr=False)

    @classmethod
    def load(cls, config: OptimizedConfig) -> "DemoService":
        calibration = load_calibration(config) if (config.output_directory / "calibration.json").exists() else None
        return cls(config, load_replay(config), load_systems(config),
                   OptimizedFeatures(config.baseline, config.guard), calibration)

    def catalog(self) -> dict[str, object]:
        split = "evaluation" if len(self.dataset.partition("evaluation")) else "exploratory"
        decisions = self.dataset.partition(split).sort_values(["decision_time", "approach_id"])
        approaches = []
        for identity, group in decisions.groupby("approach_id", sort=False):
            approaches.append({"id": identity, "mmsi": str(group["mmsi"].iloc[0]), "decisions": [
                {"id": row.decision_id, "time": row.decision_time.isoformat()}
                for row in group.itertuples()
            ]})
        return {"approaches": approaches, "scenarios": [scenario.name for scenario in primary_scenarios()],
                "scenario_options": [*scenario_options(), *deterioration_options(self.config.evaluation_seeds[0]),
                                     *position_jump_options(self.config.evaluation_seeds[0])],
                "replay_seed": self.config.evaluation_seeds[0],
                "split": split, "calibrated": self.calibration is not None,
                "gate": {"longitude": self.config.baseline.gate.longitude,
                         "south": self.config.baseline.gate.south_latitude,
                         "north": self.config.baseline.gate.north_latitude}}

    def _decision(self, decision_id: str) -> pd.Series:
        selected = self.dataset.decisions.loc[self.dataset.decisions["decision_id"] == decision_id]
        if len(selected) != 1:
            raise ValueError("Unknown or ambiguous replay decision.")
        return selected.iloc[0]

    def _evaluation_evidence(self) -> EvaluationEvidence:
        if self._evidence is None:
            self._evidence = EvaluationEvidence(self.config.output_directory, self.config.evaluation_seeds[0])
        return self._evidence

    def timeline(self, decision_id: str, scenario_name: str, *, reveal: bool) -> dict[str, object]:
        decision = self._decision(decision_id)
        presets = deterioration_presets(self.config.evaluation_seeds[0])
        if scenario_name in presets:
            return self._attack_timeline(decision, SensorDeteriorationAttack(presets[scenario_name]), scenario_name,
                                         reveal, "Live historical replay with simulated Gaussian noise")
        jumps = position_jump_presets(self.config.evaluation_seeds[0])
        if scenario_name in jumps:
            return self._attack_timeline(decision, PositionJumpAttack(jumps[scenario_name]), scenario_name,
                                         reveal, "Live historical replay with simulated position jumps")
        if scenario_name not in demo_scenarios():
            raise ValueError("Unknown predeclared replay scenario.")
        return _json_value(self._evaluation_evidence().timeline(decision["approach_id"], scenario_name,
                                                              decision["decision_time"], reveal=reveal))

    def _attack_timeline(self, decision: pd.Series, attack: BaseAttack, scenario_name: str,
                         reveal: bool, source: str) -> dict[str, object]:
        stream = attack.apply(self.dataset.histories[decision.approach_id])
        past = self.dataset.decisions.loc[
            self.dataset.decisions.approach_id.eq(decision.approach_id)
            & self.dataset.decisions.decision_time.le(decision.decision_time)].sort_values("decision_time")
        rows = []
        for _, previous in past.iterrows():
            row = previous.to_dict()
            row.update(view_row(stream.available(previous.decision_time), previous, self.extractor))
            row.update(scenario=scenario_name, condition=attack.condition.value, seed=attack.parameters["seed"])
            rows.append(row)
        frame = pd.DataFrame(rows)
        for column in (*OPTIMIZED_COLUMNS, *(f"raw_{c}" for c in RICH_COLUMNS)):
            if column not in frame:
                frame[column] = np.nan
        for column in ("observation_time", "raw_observation_time"):
            if column not in frame:
                frame[column] = pd.NaT
        predictions = predict_systems(frame, [s for s in self.systems if s.name in ("A", "B", "C")])
        columns = ["decision_id", "decision_time", "system", "available", "predicted_arrival_time"]
        if reveal:
            columns.append("error_minutes")
        return _json_value({"available": True, "seed": attack.parameters["seed"], "source": source,
                            "points": predictions[columns].to_dict(orient="records")})

    def snapshot(self, decision_id: str, scenario_name: str, *, reveal: bool, verify: bool,
                 inspect: bool = False, attack: BaseAttack | None = None) -> dict[str, object]:
        jumps = position_jump_presets(self.config.evaluation_seeds[0])
        if scenario_name in jumps:
            if verify or attack is not None:
                raise ValueError("Position jump presets require unattended replay without another attack.")
            result = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False, inspect=inspect,
                                   attack=PositionJumpAttack(jumps[scenario_name]))
            result["scenario"] = scenario_name
            return result
        presets = deterioration_presets(self.config.evaluation_seeds[0])
        if scenario_name in presets:
            if verify or attack is not None:
                raise ValueError("Sensor deterioration presets require unattended replay without another attack.")
            result = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False, inspect=inspect,
                                   attack=SensorDeteriorationAttack(presets[scenario_name]))
            result["scenario"] = scenario_name
            return result
        decision = self._decision(decision_id)
        choices = demo_scenarios()
        if scenario_name not in choices:
            raise ValueError("Unknown predeclared replay scenario.")
        if attack is not None and (scenario_name != "nominal" or verify):
            raise ValueError("Standalone attacks require nominal reports and unattended replay.")
        reports = self.dataset.histories[decision["approach_id"]]
        seed = self.config.evaluation_seeds[0]
        stream = create_stream(reports, choices[scenario_name], seed, self.config.baseline.gate)
        if attack is not None:
            stream = attack.apply(stream.reports)
            seed = attack.parameters.get("seed", seed)
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
        row.update({"scenario": scenario_name, "condition": choices[scenario_name].condition.value, "seed": seed})
        if attack is not None:
            row.update({"scenario": attack.name, "condition": attack.condition.value})
        frame = pd.DataFrame([row])
        for column in (*OPTIMIZED_COLUMNS, *(f"raw_{column}" for column in RICH_COLUMNS)):
            if column not in frame:
                frame[column] = np.nan
        for column in ("observation_time", "raw_observation_time"):
            if column not in frame:
                frame[column] = pd.NaT
        predictions = predict_systems(frame, [system for system in self.systems if system.name in ("A", "B", "C")])
        if self.calibration is not None and attack is None:
            predictions = apply_review(predictions, self.calibration, self.config)
        cards = []
        for prediction in predictions.to_dict(orient="records"):
            fields = ("system", "available", "predicted_arrival_time", "predicted_remaining_minutes",
                      "report_age_minutes", "interval_half_width_minutes", "calibration_approaches",
                      "review_reason", "accepted", "reasons", "guard_received_count", "guard_removed_count")
            card = {key: prediction.get(key) for key in fields}
            if self.calibration is None or attack is not None:
                card["review_reason"] = ("attack_not_calibrated_requires_review" if attack is not None
                                         else "not_calibrated_requires_review")
                card["accepted"] = False
            if reveal:
                card["error_minutes"] = prediction["error_minutes"]
            cards.append(card)
        result = {
            "decision_id": decision_id, "scenario": attack.name if attack is not None else scenario_name, "seed": seed,
            "decision_time": decision["decision_time"], "cards": cards,
            "received_history": available[["record_id", "time", "delivered_time", "longitude", "latitude", "sog", "cog", "vessel_type"]]
                .tail(VISIBLE_REPORT_LIMIT).to_dict(orient="records"),
            "feed_counts": feed_counts(available, self.config.baseline.features.history_minutes,
                                       self.config.guard.bin_seconds),
            "observable_diagnostics": {key: row.get(key) for key in (
                "latest_received_age_minutes", "latest_usable_age_minutes", "maximum_bin_spread_meters",
                "velocity_disagreement_mps", "maximum_gap_seconds", "occupied_minute_bins",
                "guard_received_count", "guard_removed_count", "reasons")},
            "inspection": inspect_feed(stream, available, self.config.baseline.gate,
                                       self.config.baseline.features.history_minutes) if inspect and attack is None else None,
            "human_assisted": verify, "verified_observation_time": verified_time,
            "reference_arrival": decision["arrival_time"] if reveal else None,
            "reference_bracket": [decision["crossing_before"], decision["crossing_after"]] if reveal else None,
        }
        if attack is not None:
            # Audit truth is added only after inference, never to the feature frame.
            if isinstance(attack, SensorDeteriorationAttack) and inspect:
                result["inspection"] = inspect_deterioration(
                    stream, available, self.config.baseline.features.history_minutes)
            if isinstance(attack, PositionJumpAttack) and inspect:
                result["inspection"] = inspect_position_jump(
                    stream, available, self.config.baseline.features.history_minutes)
            known = stream.modification_log.loc[(stream.modification_log["time"] <= decision["decision_time"])
                & (stream.modification_log["delivered_time"] <= decision["decision_time"])]
            affected = known.loc[known["fault_applied"]]
            result["attack"] = {"name": attack.name, "parameters": attack.parameters,
                                "withheld_reports_so_far": int(known["action"].eq("dropped").sum()),
                                "injected_missing_speed_reports_so_far": int(known["action"].eq("speed_removed").sum()),
                                "injected_missing_course_reports_so_far": int(known["action"].eq("course_removed").sum()),
                                "injected_missing_vessel_class_reports_so_far": int(known["action"].eq("vessel_class_removed").sum()),
                                "inspection": {"audience_only": True,
                                               "records": affected.tail(VISIBLE_REPORT_LIMIT).to_dict(orient="records"),
                                               "truncated": len(affected) > VISIBLE_REPORT_LIMIT} if inspect else None}
        return _json_value(result)

    def position_jump_snapshot(
        self, decision_id: str, config: PositionJumpConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Same decision and reference crossing; position measurements differ."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=PositionJumpAttack(config))
        return {"original": original, "attacked": attacked}

    def sensor_deterioration_snapshot(
        self, decision_id: str, config: SensorDeteriorationConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Pair original and corrupted feeds at identical clocks and references."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=SensorDeteriorationAttack(config))
        return {"original": original, "attacked": attacked}

    def reporting_gap_snapshot(
        self, decision_id: str, config: ReportingGapConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Paired frontend response: identical decision/reference, different feeds."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=ReportingGapAttack(config))
        return {"original": original, "attacked": attacked}

    def missing_speed_snapshot(
        self, decision_id: str, config: MissingSpeedConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Same-clock comparison using current imputation, never zero-filled speed."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=MissingSpeedAttack(config))
        return {"original": original, "attacked": attacked}

    def missing_course_snapshot(
        self, decision_id: str, config: MissingCourseConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Same-clock course masking using current imputation, not a northward default."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=MissingCourseAttack(config))
        return {"original": original, "attacked": attacked}

    def missing_vessel_class_snapshot(
        self, decision_id: str, config: MissingVesselClassConfig, *, reveal: bool = False, inspect: bool = False,
    ) -> dict[str, object]:
        """Same-clock class masking while retaining every position/speed report."""
        original = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False)
        attacked = self.snapshot(decision_id, "nominal", reveal=reveal, verify=False,
                                 inspect=inspect, attack=MissingVesselClassAttack(config))
        return {"original": original, "attacked": attacked}

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
        if review.exists():
            policies = pd.DataFrame(result["review"])
            selected = policies.loc[policies["system"].eq("C") & policies["policy"].eq("calibrated")
                                    & policies["tolerance_minutes"].eq(self.config.review.maximum_half_width_minutes)]
            result["review_policy"] = {"tolerance_minutes": self.config.review.maximum_half_width_minutes,
                                       "scheduled": int(selected["scheduled"].sum()),
                                       "accepted": int(selected["accepted"].sum())}
        volume = self.config.output_directory / "results" / "evaluation_volume" / "condition_summary.csv"
        result["volume_summary"] = pd.read_csv(volume).to_dict(orient="records") if volume.exists() else []
        result["failures"] = self._evaluation_evidence().failure_examples()
        return _json_value(result)


def serve(config: OptimizedConfig, port: int) -> None:
    if not 1024 <= port <= 65535:
        raise ValueError("Choose a local port between 1024 and 65535.")
    mapbox_token = load_mapbox_public_token(MAPBOX_ENV_FILE)
    service = DemoService.load(config)
    page = FRONTEND_DIRECTORY / "eta_replay.html"
    assets = {f"/replay/{path.name}": path for path in (FRONTEND_DIRECTORY / "replay").iterdir()
              if path.is_file() and path.suffix in ASSET_TYPES}

    class ReplayRequest(BaseHTTPRequestHandler):
        def _send_bytes(self, status: int, body: bytes, content_type: str, cache_control: str) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", cache_control)
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("Replay browser cancelled the response")

        def _send(self, status: int, payload: object) -> None:
            body = json.dumps(_json_value(payload), allow_nan=False).encode()
            self._send_bytes(status, body, "application/json", "no-store")

        def do_GET(self) -> None:
            request = urlparse(self.path)
            try:
                if request.path == "/":
                    self._send_bytes(200, page.read_bytes(), "text/html; charset=utf-8", "no-cache")
                elif request.path in assets:
                    path = assets[request.path]
                    self._send_bytes(200, path.read_bytes(), ASSET_TYPES[path.suffix], "no-cache")
                elif request.path == "/api/config":
                    self._send(200, {"mapbox_public_token": mapbox_token})
                elif request.path == "/api/catalog":
                    self._send(200, service.catalog())
                elif request.path == "/api/metrics":
                    self._send(200, service.metrics())
                elif request.path == "/api/attacks/position-jump":
                    query = parse_qs(request.query)
                    bearing = query.get("bearing_degrees", [None])[0]
                    config = PositionJumpConfig(
                        displacement_meters=float(query.get("displacement_meters", ["2000"])[0]),
                        affected_fraction=float(query.get("affected_fraction", ["0.25"])[0]),
                        seed=int(query.get("seed", ["42"])[0]), target_mmsi=query.get("target_mmsi", [None])[0],
                        bearing_degrees=float(bearing) if bearing is not None else None,
                        start_time=query.get("start_time", [None])[0], end_time=query.get("end_time", [None])[0])
                    self._send(200, service.position_jump_snapshot(query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true"))
                elif request.path == "/api/attacks/sensor-deterioration":
                    query = parse_qs(request.query)
                    defaults = SensorDeteriorationConfig.from_severity(query.get("severity", ["medium"])[0])
                    config = SensorDeteriorationConfig(
                        sog_sigma_knots=float(query.get("sog_sigma_knots", [str(defaults.sog_sigma_knots)])[0]),
                        cog_sigma_degrees=float(query.get("cog_sigma_degrees", [str(defaults.cog_sigma_degrees)])[0]),
                        affected_fraction=float(query.get("affected_fraction", ["1"])[0]),
                        seed=int(query.get("seed", ["42"])[0]), target_mmsi=query.get("target_mmsi", [None])[0],
                    )
                    self._send(200, service.sensor_deterioration_snapshot(
                        query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true"))
                elif request.path == "/api/attacks/missing-vessel-class":
                    query = parse_qs(request.query)
                    config = MissingVesselClassConfig(
                        affected_fraction=float(query.get("affected_fraction", ["0.25"])[0]),
                        seed=int(query.get("seed", ["42"])[0]),
                        target_mmsi=query.get("target_mmsi", [None])[0],
                        selection_unit=query.get("selection_unit", ["report"])[0],
                    )
                    self._send(200, service.missing_vessel_class_snapshot(
                        query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true",
                    ))
                elif request.path == "/api/attacks/missing-course":
                    query = parse_qs(request.query)
                    config = MissingCourseConfig(
                        affected_fraction=float(query.get("affected_fraction", ["0.25"])[0]),
                        seed=int(query.get("seed", ["42"])[0]),
                        target_mmsi=query.get("target_mmsi", [None])[0],
                    )
                    self._send(200, service.missing_course_snapshot(
                        query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true",
                    ))
                elif request.path == "/api/attacks/missing-speed":
                    query = parse_qs(request.query)
                    config = MissingSpeedConfig(
                        affected_fraction=float(query.get("affected_fraction", ["0.25"])[0]),
                        seed=int(query.get("seed", ["42"])[0]),
                        target_mmsi=query.get("target_mmsi", [None])[0],
                    )
                    self._send(200, service.missing_speed_snapshot(
                        query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true",
                    ))
                elif request.path == "/api/attacks/reporting-gap":
                    query = parse_qs(request.query)
                    config = ReportingGapConfig(
                        start_time=query.get("start_time", [""])[0],
                        end_time=query.get("end_time", [""])[0],
                        target_mmsi=query.get("target_mmsi", [None])[0],
                    )
                    self._send(200, service.reporting_gap_snapshot(
                        query.get("decision", [""])[0], config,
                        reveal=query.get("reveal", ["false"])[0] == "true",
                        inspect=query.get("inspect", ["false"])[0] == "true",
                    ))
                elif request.path in ("/api/replay", "/api/timeline"):
                    query = parse_qs(request.query)
                    decision = query.get("decision", [""])[0]
                    scenario = query.get("scenario", ["nominal"])[0]
                    reveal = query.get("reveal", ["false"])[0] == "true"
                    if request.path == "/api/timeline":
                        self._send(200, service.timeline(decision, scenario, reveal=reveal))
                    else:
                        self._send(200, service.snapshot(decision, scenario, reveal=reveal, verify=False,
                            inspect=query.get("inspect", ["false"])[0] == "true"))
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
                result = service.snapshot(payload["decision"], payload["scenario"], reveal=False, verify=True,
                                          inspect=payload.get("inspect") is True)
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

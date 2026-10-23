"""Production HTTP adapter. Scientific inference stays in Optimized_Model."""
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
from threading import RLock

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from fastapi.responses import JSONResponse

from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.fleet import FleetService, poisoning_settings
from Optimized_Model.service import DemoService, _json_value
from api.analysis import AnalysisJobs

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def load_fleet():
    path = Path(os.getenv("ANTIDOTE_CONFIG", str(ROOT / "Optimized_Model/config_data_eval.json")))
    if not path.is_absolute():
        path = ROOT / path
    config = OptimizedConfig.load(path)
    # Production must never fall back to preprocessing raw data or training.
    if not (config.output_directory / "serving_bundle.json").is_file():
        raise FileNotFoundError("A verified serving_bundle.json and its artifacts are required.")
    service = DemoService.load(config, model_c="C_nominal")
    return FleetService(config, service.dataset, service.systems, service.extractor, evaluation_only=True)


def response(payload, status=200):
    return JSONResponse(_json_value(payload), status_code=status, headers={"Cache-Control": "no-store"})


def create_app(loader=load_fleet):
    @asynccontextmanager
    async def lifespan(app):
        app.state.fleet = None
        app.state.failure = None
        app.state.inference_lock = RLock()
        try:
            app.state.fleet = loader()
            app.state.jobs = AnalysisJobs(app.state.fleet, app.state.inference_lock)
        except Exception:
            logger.exception("Frozen serving bundle could not be loaded")
            app.state.failure = "Frozen replay unavailable. Check ANTIDOTE_CONFIG, bundle files and integrity in server logs."
        yield
        if app.state.fleet is not None:
            app.state.jobs.close()

    app = FastAPI(title="Antidote replay API", lifespan=lifespan)
    origins = [s.strip() for s in os.getenv("CORS_ORIGINS", "").split(",") if s.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must contain explicit origins, not '*'.")
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["Accept"])

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return response({"error": "Invalid query parameters."}, 400)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return response({"error": str(exc)}, 400)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return response({"error": str(exc.detail)}, exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("API request failed", exc_info=exc)
        return response({"error": "Inference failed; see server logs."}, 500)

    def fleet():
        if app.state.fleet is None:
            raise HTTPException(503, app.state.failure)
        return app.state.fleet

    def settings(value):
        if len(value) > 4096:
            raise ValueError("poisoning query is too long.")
        parsed = json.loads(value)
        poisoning_settings(parsed)
        return parsed

    @app.get("/health")
    def health():
        ready = app.state.fleet is not None
        return response({"status": "ok" if ready else "unavailable", "models_loaded": ready}, 200 if ready else 503)

    @app.get("/api/config")
    def config():
        token = os.getenv("MAPBOX_PUBLIC_TOKEN", "").strip()
        return response({"mapbox_public_token": token if token.startswith("pk.") else None})

    @app.get("/api/fleet/catalog")
    def catalog():
        return response(fleet().catalog())

    @app.get("/api/fleet/frame")
    def frame(time: float, poisoning: str = "{}", mitigate: str = "true",
              trusted_fixes: str = "false", drift_direction: str = "under"):
        if mitigate not in ("true", "false") or trusted_fixes not in ("true", "false"):
            raise ValueError("mitigate and trusted_fixes must be true or false.")
        service = fleet()
        selected = settings(poisoning)
        with app.state.inference_lock:
            payload = service.frame(time, selected, mitigate=mitigate == "true",
                                    trusted_fixes=trusted_fixes == "true", drift_direction=drift_direction)
        return response(payload)

    @app.get("/api/fleet/monthly")
    def monthly(poisoning: str = "{}", client: str = "anonymous", job: str | None = None):
        fleet()
        if len(client) > 128:
            raise ValueError("client must be at most 128 characters.")
        payload = app.state.jobs.poll(job) if job else app.state.jobs.monthly(settings(poisoning), client)
        return response(payload, 200 if payload["status"] in ("ready", "error", "superseded") else 202)

    @app.get("/api/fleet/stress")
    def stress(retry: int = 0):
        fleet()
        if retry not in (0, 1):
            raise ValueError("retry must be 0 or 1.")
        payload = app.state.jobs.stress(bool(retry))
        return response(payload, 200 if payload["status"] in ("ready", "error") else 202)

    return app


app = create_app()

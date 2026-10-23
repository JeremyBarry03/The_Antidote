"""Portable, hash-verified March replay; research loaders remain unchanged."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import joblib

from .configuration import OptimizedConfig
from .evaluation import PredictionSystem
from .features import OptimizedFeatures


def load_bundle(config: OptimizedConfig):
    root = config.output_directory
    manifest = json.loads((root / "serving_bundle.json").read_text())
    for relative, expected in manifest["files"].items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Serving artifact changed: {relative}")
    code_root = Path(__file__).resolve().parents[1]
    for relative, expected in manifest["inference_lf_sha256"].items():
        code = (code_root / relative).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(code).hexdigest() != expected:
            raise ValueError(f"Serving inference code changed: {relative}")
    # Compare scientific settings while allowing a different installation path.
    current = json.loads(json.dumps(asdict(config), default=str))
    for key in ("baseline_config", "output_directory", "later_csv"):
        current.pop(key)
    if current != manifest["scientific_config"]:
        raise ValueError("Serving scientific configuration changed")
    baseline = json.loads(json.dumps(asdict(config.baseline), default=str))
    for key in ("input_csv", "output_directory"):
        baseline.pop(key)
    if baseline != manifest["baseline_config"]:
        raise ValueError("Serving baseline configuration changed")
    dataset = joblib.load(root / "serving_replay.joblib")
    systems = [PredictionSystem(name, joblib.load(root / relative), view)
               for name, relative, view in manifest["models"]]
    return dataset, systems, OptimizedFeatures(config.baseline, config.guard)

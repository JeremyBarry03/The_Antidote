"""Serving aliases must select nominal C and preserve model-specific calibration."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.evaluation import PredictionSystem
from Optimized_Model.service import DemoService


@pytest.mark.parametrize("nominal_band", [None, {"pooled": {"half_width_minutes": 7}}])
def test_nominal_serving_keeps_ab_and_uses_its_own_calibration(tmp_path, monkeypatch, nominal_band):
    from Optimized_Model import service

    config = replace(OptimizedConfig.load(Path(__file__).resolve().parents[1] /
                                         "Optimized_Model/config_data_eval.json"), output_directory=tmp_path)
    (tmp_path / "calibration.json").write_text("{}")
    bands = {"A": {}, "B": {}, "C": {"pooled": {"half_width_minutes": 1}}}
    if nominal_band is not None:
        bands["C_nominal"] = nominal_band
    calibration = {"bands": bands}
    systems = [PredictionSystem(name, SimpleNamespace(model_name=name), "raw" if name in ("A", "B") else "guarded")
               for name in ("A", "B", "C", "C_nominal")]
    monkeypatch.setattr(service, "load_calibration", lambda config: calibration)
    monkeypatch.setattr(service, "load_systems", lambda config: systems)
    monkeypatch.setattr(service, "load_replay", lambda config: object())
    loaded = DemoService.load(config, model_c="C_nominal")
    assert [system.name for system in loaded.systems] == ["A", "B", "C"]
    assert loaded.systems[:2] == systems[:2]
    assert loaded.systems[2].predictor is systems[3].predictor
    assert loaded.systems[2].input_view == "guarded"
    assert loaded.calibration["bands"].get("C") == nominal_band
    assert calibration["bands"]["C"]["pooled"]["half_width_minutes"] == 1


@pytest.mark.parametrize("extra,expected", [([], "C_nominal"), (["--model-c", "C"], "C")])
def test_serve_defaults_to_2023_models_and_march_evaluation(monkeypatch, extra, expected):
    from Optimized_Model import __main__ as cli, service

    calls = []
    monkeypatch.setattr("sys.argv", ["Optimized_Model", "serve", *extra])
    monkeypatch.setattr(service, "serve", lambda config, port, **kwargs: calls.append((config, port, kwargs)))
    cli.main()
    config, port, options = calls[0]
    assert config.baseline.splits.start == "2023-01-01"
    assert (config.evaluation_start, config.evaluation_end) == ("2024-03-01", "2024-04-01")
    assert port == 8765 and options["model_c"] == expected

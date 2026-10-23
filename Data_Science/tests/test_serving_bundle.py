"""The shipped replay works without original training/evaluation CSVs."""
from pathlib import Path
import shutil

import pytest

from Optimized_Model.configuration import OptimizedConfig
from Optimized_Model.service import DemoService
from Optimized_Model.fleet import FleetService


def test_relocated_bundle_and_integrity(tmp_path):
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "Data_Science"
    (root / "Optimized_Model").mkdir(parents=True)
    for relative in ("config_data_eval.json", "Optimized_Model/config_data_eval.json"):
        shutil.copy(source / relative, root / relative)
    shutil.copytree(source / "artifacts/data_eval/optimized", root / "artifacts/data_eval/optimized")
    config = OptimizedConfig.load(root / "Optimized_Model/config_data_eval.json")
    assert not config.later_csv.exists()
    assert not config.baseline.input_csv.exists()
    service = DemoService.load(config, model_c="C_nominal")
    fleet = FleetService(config, service.dataset, service.systems, service.extractor, evaluation_only=True)
    catalog = fleet.catalog()
    assert catalog["training_year"] == 2023
    assert catalog["evaluation_label"] == "March 2024"
    assert len(fleet.approaches) == 243
    for settings in ({}, {"missing_speed": 100}, {"position_jump": 50}):
        assert fleet.frame(catalog["initial_time"], settings)["ships"]
    first = next(iter(fleet.approaches.itertuples()))
    assert fleet.frame(float(first.arrival_time.timestamp()), {})["ships"]
    assert len(fleet._crossing_positions()) == 243
    model = config.output_directory / "models/C_nominal.joblib"
    model.write_bytes(model.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Serving artifact changed"):
        DemoService.load(config, model_c="C_nominal")

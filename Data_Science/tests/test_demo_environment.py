"""Local Mapbox configuration stays independent of the shell and working folder."""

import os
from pathlib import Path

import pytest

from Optimized_Model.service import load_mapbox_public_token


@pytest.fixture(autouse=True)
def clear_mapbox_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MAPBOX_TOKEN", "MAPBOX_PUBLIC_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("name", ["MAPBOX_TOKEN", "MAPBOX_PUBLIC_TOKEN"])
def test_reads_quoted_public_token_without_changing_environment(tmp_path: Path, name: str) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f'# Local configuration\n{name}="pk.local-test" # public\n', encoding="utf-8-sig")
    assert load_mapbox_public_token(env_file) == "pk.local-test"
    assert name not in os.environ


@pytest.mark.parametrize("name", ["MAPBOX_TOKEN", "MAPBOX_PUBLIC_TOKEN"])
def test_explicit_environment_overrides_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAPBOX_TOKEN=pk.file-test\n", encoding="utf-8")
    monkeypatch.setenv(name, "pk.process-test")
    assert load_mapbox_public_token(env_file) == "pk.process-test"


def test_missing_env_file_preserves_optional_map_configuration(tmp_path: Path) -> None:
    assert load_mapbox_public_token(tmp_path / ".env") is None


def test_secret_token_is_not_returned_to_the_browser(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAPBOX_TOKEN=sk.secret-test\n", encoding="utf-8")
    assert load_mapbox_public_token(env_file) is None

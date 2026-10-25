import pytest

from rotatarr import config


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    """Keep settings, history and state of every test in its own folder."""
    monkeypatch.setenv("ROTATARR_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path

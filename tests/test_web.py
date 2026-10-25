import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ROTATARR_DISABLE_SCHEDULER", "1")
    from rotatarr import config, runner, web
    importlib.reload(config)
    importlib.reload(runner)
    importlib.reload(web)
    with TestClient(web.app) as c:
        yield c, config


def test_settings_roundtrip_hides_token(client):
    c, config = client
    s = config.load()
    s.plex_url, s.plex_token = "http://plex:32400", "secret"
    config.save(s)

    data = c.get("/api/settings").json()
    assert data["connected"] is True
    assert "plex_token" not in data

    data = c.put("/api/settings", json={"rotation_interval_minutes": 5, "language": "de"}).json()
    assert data["rotation_interval_minutes"] == 5
    assert config.load().plex_token == "secret"


def test_libraries_need_connection(client):
    c, _ = client
    assert c.get("/api/libraries").status_code == 409


def test_index_served(client):
    c, _ = client
    assert "Rotatarr" in c.get("/").text

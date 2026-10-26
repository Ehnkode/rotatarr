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


def test_other_websites_cannot_change_anything(client):
    c, _ = client
    assert c.post("/api/reset", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.put("/api/settings", json={"dry_run": True}, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_server_token_only_goes_to_listed_addresses(client):
    c, _ = client
    from rotatarr import web
    web._pins[7] = [{"name": "Home", "token": "t", "connections": [{"uri": "http://192.168.1.2:32400", "local": True}]}]
    r = c.post("/api/plex/server", json={"pin_id": 7, "server": 0, "uri": "http://evil.example"})
    assert r.status_code == 400


def test_settings_file_is_private(client):
    _, config = client
    config.save(config.load())
    assert config.SETTINGS_FILE.stat().st_mode & 0o077 == 0


def test_login_protects_ui_and_health_check_passes(monkeypatch, client):
    monkeypatch.setenv("ROTATARR_USERNAME", "admin")
    monkeypatch.setenv("ROTATARR_PASSWORD", "geheim")
    from rotatarr import healthcheck, web
    importlib.reload(web)
    with TestClient(web.app) as c:
        assert c.get("/api/state").status_code == 401
        assert c.get("/api/state", auth=("admin", "falsch")).status_code == 401
        req = healthcheck.request()
        assert c.get("/api/state", headers=dict(req.header_items())).status_code == 200

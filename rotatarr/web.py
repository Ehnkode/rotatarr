"""HTTP API and static web UI."""

from __future__ import annotations

import base64
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, config, plexauth, runner
from .config import LibrarySettings
from .plex import PlexClient

STATIC = Path(__file__).parent / "static"
SUPPORTED_TYPES = ("movie", "show")

scheduler = runner.Scheduler()
_running: set[str] = set()
_pins: dict[int, list[dict]] = {}  # pin id -> servers found for that sign-in


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("ROTATARR_DISABLE_SCHEDULER") != "1":
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Rotatarr", version=__version__, lifespan=lifespan)

USERNAME = os.environ.get("ROTATARR_USERNAME", "")
PASSWORD = os.environ.get("ROTATARR_PASSWORD", "")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional protection of the whole UI with HTTP basic auth."""
    if PASSWORD:
        ok = False
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, USERNAME) and secrets.compare_digest(pw, PASSWORD)
            except ValueError:
                pass
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Rotatarr"'})
    return await call_next(request)


def _client() -> PlexClient:
    settings = config.load()
    if not settings.connected:
        raise HTTPException(409, "not_connected")
    return runner.client_for(settings)


# --- settings ------------------------------------------------------------------

class SettingsIn(BaseModel):
    language: str | None = None
    rotation_interval_minutes: int | None = None
    shuffle_interval_minutes: int | None = None
    items_to_front: int | None = None
    pinned_rows: list[str] | None = None
    dry_run: bool | None = None


def _public_settings(s: config.Settings) -> dict:
    data = s.model_dump(exclude={"plex_token", "client_id", "libraries"})
    data["connected"] = s.connected
    return data


@app.get("/api/settings")
def get_settings():
    return _public_settings(config.load())


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    s = config.load()
    updated = s.model_copy(update=body.model_dump(exclude_none=True))
    s = config.Settings.model_validate(updated.model_dump())
    config.save(s)
    scheduler.reschedule()
    return _public_settings(s)


# --- Plex connection -------------------------------------------------------------

class ManualConnection(BaseModel):
    url: str
    token: str


class ServerChoice(BaseModel):
    pin_id: int
    server: int
    uri: str


def _connect(url: str, token: str) -> dict:
    s = config.load()
    try:
        name = PlexClient(url, token, s.client_id, timeout=10).server_name()
    except Exception as exc:
        raise HTTPException(400, f"connection_failed: {exc}") from exc
    s.plex_url, s.plex_token = url.rstrip("/"), token
    config.save(s)
    return {"server": name}


@app.post("/api/plex/manual")
def connect_manual(body: ManualConnection):
    return _connect(body.url, body.token)


@app.post("/api/plex/pin")
def start_pin():
    return plexauth.create_pin(config.load().client_id)


@app.get("/api/plex/pin/{pin_id}")
def poll_pin(pin_id: int):
    client_id = config.load().client_id
    token = plexauth.check_pin(client_id, pin_id)
    if not token:
        return {"done": False}
    servers = plexauth.servers(client_id, token)
    _pins[pin_id] = servers
    return {"done": True, "servers": [
        {"name": srv["name"], "connections": srv["connections"]} for srv in servers
    ]}


@app.post("/api/plex/server")
def choose_server(body: ServerChoice):
    servers = _pins.get(body.pin_id)
    if not servers or not 0 <= body.server < len(servers):
        raise HTTPException(404, "unknown_server")
    result = _connect(body.uri, servers[body.server]["token"])
    _pins.pop(body.pin_id, None)
    return result


@app.post("/api/plex/disconnect")
def disconnect():
    s = config.load()
    s.plex_url = s.plex_token = ""
    config.save(s)
    return {"ok": True}


# --- libraries -------------------------------------------------------------------

@app.get("/api/libraries")
def libraries():
    s = config.load()
    client = _client()
    result = []
    for sec in client.sections():
        if sec["type"] not in SUPPORTED_TYPES:
            continue
        lib = s.libraries.get(sec["key"], LibrarySettings())
        result.append(sec | {"settings": lib.model_dump()})
    return result


@app.put("/api/libraries/{sid}")
def put_library(sid: str, body: LibrarySettings):
    s = config.load()
    s.libraries[sid] = body
    config.save(s)
    return body


@app.get("/api/libraries/{sid}/collections")
def library_collections(sid: str):
    return [
        {"title": c.title, "items": c.child_count, "smart": c.smart}
        for c in sorted(_client().collections(sid), key=lambda c: c.title.lower())
    ]


@app.get("/api/libraries/{sid}/rows")
def library_rows(sid: str):
    """Current row order and visibility as Plex reports it."""
    return [
        {"title": h.title, "identifier": h.identifier, "collection": h.collection_key is not None,
         "recommended": h.recommended, "home": h.home, "shared": h.shared}
        for h in _client().hubs(sid)
    ]


# --- jobs ------------------------------------------------------------------------

@app.post("/api/run/{kind}")
def run_now(kind: str):
    if kind not in (runner.ROTATE, runner.SHUFFLE):
        raise HTTPException(404)
    if kind in _running:
        return {"started": False}

    def work():
        _running.add(kind)
        try:
            runner.run_job(kind)
        finally:
            _running.discard(kind)

    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


@app.get("/api/state")
def state():
    return {"version": __version__, "running": sorted(_running), "next_run": scheduler.next_run}


@app.get("/api/history")
def history():
    return runner.load_history()


# --- UI --------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")

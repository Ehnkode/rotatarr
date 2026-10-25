"""Small runtime state kept next to the settings: the snapshot for "reset" and recent picks."""

from __future__ import annotations

import json
import threading

from . import config

_lock = threading.Lock()


def _file():
    return config.CONFIG_DIR / "state.json"


def _load() -> dict:
    if not _file().exists():
        return {}
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save(data: dict) -> None:
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_file())


# --- snapshot of the state before Rotatarr changed anything ------------------------

def snapshot() -> dict:
    with _lock:
        return _load().get("snapshot", {})


def has_snapshot() -> bool:
    return bool(snapshot())


def remember_hubs(sid: str, hubs: list[dict]) -> None:
    """Store the original rows of a library, only the first time."""
    with _lock:
        data = _load()
        lib = data.setdefault("snapshot", {}).setdefault(sid, {})
        if "hubs" not in lib:
            lib["hubs"] = hubs
            _save(data)


def remember_sort(sid: str, rating_key: str, sort: str) -> None:
    """Store the original sort setting of a collection, only the first time."""
    with _lock:
        data = _load()
        sorts = data.setdefault("snapshot", {}).setdefault(sid, {}).setdefault("sorts", {})
        if rating_key not in sorts:
            sorts[rating_key] = sort
            _save(data)


def clear_snapshot() -> None:
    with _lock:
        data = _load()
        data.pop("snapshot", None)
        data.pop("recent", None)
        _save(data)


# --- recent picks for the repeat block --------------------------------------------

def recent(sid: str, runs: int) -> set[str]:
    if runs <= 0:
        return set()
    with _lock:
        history = _load().get("recent", {}).get(sid, [])
    return {key for picks in history[:runs] for key in picks}


def add_recent(sid: str, picks: list[str], keep: int = 20) -> None:
    with _lock:
        data = _load()
        history = data.setdefault("recent", {}).setdefault(sid, [])
        history.insert(0, picks)
        del history[keep:]
        _save(data)

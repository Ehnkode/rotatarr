"""Runs jobs (rotation, item shuffle), keeps a short history and schedules them."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone

from . import config
from .plex import PlexClient
from .rotation import rotate_library
from .shuffle import shuffle_library

log = logging.getLogger("rotatarr")

HISTORY_FILE = config.CONFIG_DIR / "history.json"
HISTORY_LIMIT = 50

ROTATE = "rotate"
SHUFFLE = "shuffle"

_job_lock = threading.Lock()
_history_lock = threading.Lock()


def load_history() -> list[dict]:
    with _history_lock:
        if not HISTORY_FILE.exists():
            return []
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except ValueError:
            return []


def _append_history(entry: dict) -> None:
    history = load_history()
    with _history_lock:
        history.insert(0, entry)
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history[:HISTORY_LIMIT], indent=2), encoding="utf-8")


def client_for(settings: config.Settings) -> PlexClient:
    return PlexClient(settings.plex_url, settings.plex_token, settings.client_id)


def run_job(kind: str) -> dict:
    """Run one job over all enabled libraries. Only one job runs at a time."""
    settings = config.load()
    started = datetime.now(timezone.utc)
    entry = {"kind": kind, "started": started.isoformat(), "dry_run": settings.dry_run,
             "ok": True, "lines": []}

    if not settings.connected:
        entry.update(ok=False, lines=["Not connected to Plex"])
        return entry

    with _job_lock:
        client = client_for(settings)
        try:
            sections = {s["key"]: s for s in client.sections()}
            for sid, lib in settings.libraries.items():
                if not lib.enabled or sid not in sections:
                    continue
                title = sections[sid]["title"]
                try:
                    if kind == ROTATE:
                        result = rotate_library(client, sid, title, lib, settings)
                    elif lib.shuffle_items:
                        result = shuffle_library(client, sid, title, settings)
                    else:
                        continue
                    entry["lines"] += result.lines
                except Exception as exc:  # keep going with the next library
                    log.exception("%s failed for %s", kind, title)
                    entry["ok"] = False
                    entry["lines"].append(f"{title}: {exc}")
        except Exception as exc:
            log.exception("%s failed", kind)
            entry.update(ok=False)
            entry["lines"].append(str(exc))

    entry["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    for line in entry["lines"]:
        log.info("[%s] %s", kind, line)
    _append_history(entry)
    return entry


class Scheduler(threading.Thread):
    """Runs each job when its interval has passed. Interval 0 disables the schedule."""

    def __init__(self):
        super().__init__(daemon=True, name="scheduler")
        self.next_run: dict[str, float] = {}
        self._stop = threading.Event()

    def _interval(self, kind: str) -> int:
        s = config.load()
        minutes = s.rotation_interval_minutes if kind == ROTATE else s.shuffle_interval_minutes
        return minutes * 60

    def reschedule(self) -> None:
        now = time.time()
        for kind in (ROTATE, SHUFFLE):
            interval = self._interval(kind)
            self.next_run[kind] = now + interval if interval else 0

    def run(self) -> None:
        self.reschedule()
        while not self._stop.wait(15):
            for kind in (ROTATE, SHUFFLE):
                due = self.next_run.get(kind, 0)
                if due and time.time() >= due:
                    interval = self._interval(kind)
                    self.next_run[kind] = time.time() + interval if interval else 0
                    run_job(kind)

    def stop(self) -> None:
        self._stop.set()

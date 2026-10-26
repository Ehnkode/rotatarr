"""Run reports to a Discord webhook."""

from __future__ import annotations

import logging

import requests

from . import config

log = logging.getLogger(__name__)

TITLES = {
    "en": {"rotate": "Row rotation", "shuffle": "Title shuffle", "reset": "Reset", "test": "Test message",
           "failed": "failed", "dry": "test mode"},
    "de": {"rotate": "Reihenwechsel", "shuffle": "Titel mischen", "reset": "Zurücksetzen", "test": "Testnachricht",
           "failed": "fehlgeschlagen", "dry": "Testmodus"},
}


def send(url: str, text: str) -> None:
    r = requests.post(url, json={"username": "Rotatarr", "content": text[:1900]}, timeout=10)
    r.raise_for_status()


def report(settings: config.Settings, entry: dict) -> None:
    """Send a finished job to Discord: always on failure, on success only if wanted."""
    if not settings.discord_webhook or (entry.get("ok") and not settings.notify_success):
        return
    words = TITLES.get(settings.language, TITLES["en"])
    head = ("✅ " if entry.get("ok") else "⚠️ ") + "Rotatarr · " + words.get(entry.get("kind"), entry.get("kind", ""))
    if not entry.get("ok"):
        head += f" {words['failed']}"
    if entry.get("dry_run"):
        head += f" ({words['dry']})"
    try:
        send(settings.discord_webhook, "\n".join([f"**{head}**", *entry.get("lines", [])]))
    except Exception as exc:  # a broken webhook must never break a run
        log.warning("Discord notification failed: %s", exc)


def test(settings: config.Settings) -> None:
    words = TITLES.get(settings.language, TITLES["en"])
    send(settings.discord_webhook, f"**🔔 Rotatarr · {words['test']}**")

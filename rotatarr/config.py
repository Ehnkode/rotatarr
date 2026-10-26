"""Settings model and persistence (a single JSON file in the config directory)."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

CONFIG_DIR = Path(os.environ.get("ROTATARR_CONFIG_DIR", "/config"))
SETTINGS_FILE = CONFIG_DIR / "settings.json"

DEFAULT_PINNED_ROWS = ["inprogress", "ondeck", "recentlyreleased", "recentlyadded"]


def pattern_of(word: str) -> str | None:
    """A line written as /.../ is a regular expression; anything else is plain text."""
    w = word.strip()
    if len(w) > 2 and w.startswith("/") and w.endswith("/"):
        return w[1:-1]
    return None


DISCORD_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")


class Quota(BaseModel):
    # Collections whose title contains `match` (case-insensitive) share this limit per run.
    match: str = Field(min_length=1)
    max: int = Field(ge=0)


class Seasonal(BaseModel):
    # Shown every run between start and end (MM-DD, the range may wrap over New Year),
    # hidden the rest of the year.
    title: str = Field(min_length=1)
    start: str = Field(pattern=r"^\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{2}-\d{2}$")

    def active(self, today: date) -> bool:
        now = today.strftime("%m-%d")
        if self.start <= self.end:
            return self.start <= now <= self.end
        return now >= self.start or now <= self.end


class LibrarySettings(BaseModel):
    enabled: bool = False
    # How many collection rows are visible at once in each place.
    # The rows are picked once per run and nested: the first `home` rows of the random
    # selection go to the home screen, the first `recommended` rows to Recommended, and so on.
    recommended: int = Field(default=20, ge=0)
    home: int = Field(default=10, ge=0)
    shared: int = Field(default=10, ge=0)
    min_items: int = Field(default=3, ge=0)
    exclude: list[str] = Field(default_factory=list)
    always_visible: list[str] = Field(default_factory=list)
    never: list[str] = Field(default_factory=list)  # exact titles
    seasonal: list[Seasonal] = Field(default_factory=list)
    quotas: list[Quota] = Field(default_factory=list)
    # At most this many of Plex's automatic movie collections per run; None = no limit.
    automatic_max: int | None = Field(default=None, ge=0)
    # Of those, at most this many on the home screens (yours and friends'); None = no own limit.
    automatic_max_home: int | None = Field(default=None, ge=0)
    shuffle_order: bool = True
    shuffle_items: bool = True

    @field_validator("exclude")
    @classmethod
    def _check_patterns(cls, words: list[str]) -> list[str]:
        for w in words:
            if pattern_of(w) is not None:
                try:
                    re.compile(pattern_of(w))
                except re.error as exc:
                    raise ValueError(f"invalid pattern {w}: {exc}") from exc
        return words

    @field_validator("quotas")
    @classmethod
    def _drop_broken_quotas(cls, quotas: list[Quota]) -> list[Quota]:
        # Early versions saved a bare number typed into the old quota field as a name with limit 0.
        return [q for q in quotas if not (q.match.strip().isdigit() and q.max == 0)]


class Settings(BaseModel):
    plex_url: str = ""
    plex_token: str = ""
    client_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    language: str = "en"
    rotation_interval_minutes: int = Field(default=60, ge=0)  # 0 = only manual runs
    shuffle_interval_minutes: int = Field(default=180, ge=0)
    items_to_front: int = Field(default=20, ge=1)
    pinned_rows: list[str] = Field(default_factory=lambda: list(DEFAULT_PINNED_ROWS))
    # Also show the pinned rows on your and your friends' home screens, not only in Recommended.
    pinned_everywhere: bool = True
    dry_run: bool = False
    # Collections shown in one of the last N runs are only picked again when nothing else is left.
    repeat_block_runs: int = Field(default=2, ge=0)
    # Discord webhook for run reports; empty = off. Failures are always reported.
    discord_webhook: str = ""
    notify_success: bool = False
    # Keyed by Plex section key (as a string).
    libraries: dict[str, LibrarySettings] = Field(default_factory=dict)

    @field_validator("discord_webhook")
    @classmethod
    def _check_webhook(cls, url: str) -> str:
        url = url.strip()
        if url and not url.startswith(DISCORD_PREFIXES):
            raise ValueError("invalid_webhook")
        return url

    @property
    def connected(self) -> bool:
        return bool(self.plex_url and self.plex_token)


_lock = threading.Lock()


def load() -> Settings:
    with _lock:
        if SETTINGS_FILE.exists():
            return Settings.model_validate_json(SETTINGS_FILE.read_text(encoding="utf-8"))
        settings = Settings()
    save(settings)
    return settings


def save(settings: Settings) -> None:
    with _lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.model_dump(), indent=2), encoding="utf-8")
        tmp.chmod(0o600)  # holds the Plex token
        tmp.replace(SETTINGS_FILE)

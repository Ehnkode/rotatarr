"""Row rotation: pick which collections are visible, then shuffle the row order."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from . import state
from .config import LibrarySettings, Settings
from .plex import Collection, Hub, PlexClient


@dataclass
class Placement:
    recommended: bool
    home: bool
    shared: bool

    @property
    def visible(self) -> bool:
        return self.recommended or self.home or self.shared


@dataclass
class LibraryResult:
    title: str
    pool: int = 0
    visible: int = 0
    changed: int = 0
    moved: int = 0
    lines: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"library": self.title, "visible": self.visible, "pool": self.pool,
                "changed": self.changed, "moved": self.moved}


def _contains(title: str, words: list[str]) -> bool:
    t = title.lower()
    return any(w.strip() and w.strip().lower() in t for w in words)


def _season(title: str, lib: LibrarySettings):
    t = title.strip().lower()
    return next((s for s in lib.seasonal if s.title.strip().lower() == t), None)


def build_pool(collections: list[Collection], lib: LibrarySettings, today: date | None = None) -> list[Collection]:
    """Collections that may be shown at all: enough items, not excluded and in season."""
    today = today or date.today()
    pool = []
    for c in collections:
        season = _season(c.title, lib)
        if season and not season.active(today):
            continue
        if (c.child_count >= lib.min_items
                and not _contains(c.title, lib.exclude)
                and not _contains_exact(c.title, lib.never)):
            pool.append(c)
    return pool


def select(pool: list[Collection], lib: LibrarySettings, rng: random.Random,
           recent: set[str] | None = None) -> list[Collection]:
    """Return a random, ranked selection respecting quotas.

    "Always visible" and in-season collections come first. Collections in `recent`
    (shown in the last runs) are only used when nothing else is left. The length is the
    largest of the three targets, so callers can hand out places by rank (see `placements`).
    """
    wanted = max(lib.recommended, lib.home, lib.shared)
    recent = recent or set()
    always = [c for c in pool if _contains_exact(c.title, lib.always_visible) or _season(c.title, lib)]
    fresh = [c for c in pool if c not in always and c.rating_key not in recent]
    stale = [c for c in pool if c not in always and c.rating_key in recent]
    rng.shuffle(fresh)
    rng.shuffle(stale)

    used = {q.match.lower(): 0 for q in lib.quotas}
    chosen: list[Collection] = list(always)
    for c in fresh + stale:
        if len(chosen) >= wanted:
            break
        quota = next((q for q in lib.quotas if q.match.strip() and q.match.lower() in c.title.lower()), None)
        if quota:
            key = quota.match.lower()
            if used[key] >= quota.max:
                continue
            used[key] += 1
        chosen.append(c)
    return chosen


def _contains_exact(title: str, names: list[str]) -> bool:
    t = title.strip().lower()
    return any(n.strip().lower() == t for n in names if n.strip())


def placements(selection: list[Collection], lib: LibrarySettings) -> dict[str, Placement]:
    return {
        c.rating_key: Placement(
            recommended=i < lib.recommended,
            home=i < lib.home,
            shared=i < lib.shared,
        )
        for i, c in enumerate(selection)
    }


def order_hubs(hubs: list[Hub], placed: dict[str, Placement], pinned: list[str], rng: random.Random) -> list[str]:
    """Target order for the visible rows: pinned built-in rows first, the rest shuffled.

    Hidden rows are left alone; they end up below the visible ones.
    """
    ids = [h.identifier for h in hubs]
    top: list[str] = []
    for p in pinned:
        p = p.strip().lower()
        if not p:
            continue
        for i in ids:
            if i.startswith("hub.") and p in i.lower() and i not in top:
                top.append(i)

    def will_be_visible(h: Hub) -> bool:
        key = h.collection_key
        if key is not None:
            return key in placed and placed[key].visible
        return h.visible

    rest = [h.identifier for h in hubs if h.identifier not in top and will_be_visible(h)]
    rng.shuffle(rest)
    return top + rest


def rotate_library(client: PlexClient, sid: str, title: str, lib: LibrarySettings, settings: Settings,
                   rng: random.Random | None = None) -> LibraryResult:
    rng = rng or random.Random()
    dry = settings.dry_run
    res = LibraryResult(title=title)

    pool = build_pool(client.collections(sid), lib)
    selection = select(pool, lib, rng, state.recent(sid, settings.repeat_block_runs))
    placed = placements(selection, lib)
    res.pool, res.visible = len(pool), len(selection)

    hubs = client.hubs(sid)
    existing = {h.collection_key: h for h in hubs if h.collection_key}
    if not dry:
        state.remember_hubs(sid, [
            {"identifier": h.identifier, "recommended": h.recommended, "home": h.home, "shared": h.shared}
            for h in hubs
        ])
        state.add_recent(sid, [c.rating_key for c in selection])

    # 1) Visibility. Every collection row that is not selected gets hidden.
    for key, hub in existing.items():
        want = placed.get(key, Placement(False, False, False))
        if (hub.recommended, hub.home, hub.shared) != (want.recommended, want.home, want.shared):
            res.changed += 1
            if not dry:
                client.set_visibility(sid, hub.identifier, want.recommended, want.home, want.shared)
    for key, want in placed.items():
        if key not in existing and want.visible:
            res.changed += 1
            if not dry:
                client.create_collection_hub(sid, key, want.recommended, want.home, want.shared)

    # 2) Order.
    if lib.shuffle_order:
        hubs = client.hubs(sid) if not dry else hubs
        target = order_hubs(hubs, placed, settings.pinned_rows, rng)
        if dry:
            # Newly created rows are not in `hubs` yet during a dry run.
            known = {h.identifier for h in hubs}
            target += [f"custom.collection.{sid}.{k}" for k, p in placed.items()
                       if p.visible and f"custom.collection.{sid}.{k}" not in known]
        prev = None
        for ident in target:
            if not dry:
                client.move_hub(sid, ident, prev)
            prev = ident
        res.moved = len(target)

    res.lines.append(f"{title}: {res.visible} of {res.pool} collections visible, "
                     f"{res.changed} rows changed, {res.moved} rows ordered")
    return res


def restore_library(client: PlexClient, sid: str, snap: dict) -> int:
    """Put a library back the way it was before Rotatarr's first run. Returns changed rows."""
    original = {h["identifier"]: h for h in snap.get("hubs", [])}
    changed = 0
    for hub in client.hubs(sid):
        want = original.get(hub.identifier, {"recommended": False, "home": False, "shared": False})
        if (hub.recommended, hub.home, hub.shared) != (want["recommended"], want["home"], want["shared"]):
            client.set_visibility(sid, hub.identifier, want["recommended"], want["home"], want["shared"])
            changed += 1
    current = {h.identifier for h in client.hubs(sid)}
    prev = None
    for ident in original:
        if ident in current:
            client.move_hub(sid, ident, prev)
            prev = ident
    for rating_key, sort in snap.get("sorts", {}).items():
        try:
            client.set_sort(rating_key, sort)
        except Exception:  # the collection may have been deleted since
            pass
    return changed

"""Row rotation: pick which collections are visible, then shuffle the row order."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date

from . import state
from .config import LibrarySettings, Settings, pattern_of
from .plex import Collection, Hub, PlexClient

log = logging.getLogger(__name__)


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
    for w in words:
        pattern = pattern_of(w)
        if pattern is not None:
            if re.search(pattern, title, re.IGNORECASE):
                return True
        elif w.strip() and w.strip().lower() in t:
            return True
    return False


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
    automatic = 0
    chosen: list[Collection] = list(always)
    for c in fresh + stale:
        if len(chosen) >= wanted:
            break
        if c.automatic and lib.automatic_max is not None:
            if automatic >= lib.automatic_max:
                continue
            automatic += 1
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


def rank_for_home(selection: list[Collection], lib: LibrarySettings) -> list[Collection]:
    """Reorder the selection so the home screens get at most `automatic_max_home` automatic collections.

    The home screens take the first rows of the selection, so automatic collections over the limit
    move behind them; they stay in Recommended. Always-visible and seasonal rows are never moved.
    """
    limit = lib.automatic_max_home
    if limit is None:
        return selection
    head_len = max(lib.home, lib.shared)
    head: list[Collection] = []
    later: list[Collection] = []
    used = 0
    for c in selection:
        fixed = _contains_exact(c.title, lib.always_visible) or _season(c.title, lib) is not None
        if len(head) < head_len and (fixed or not c.automatic or used < limit):
            head.append(c)
            used += c.automatic
        else:
            later.append(c)
    return head + later


def placements(selection: list[Collection], lib: LibrarySettings) -> dict[str, Placement]:
    return {
        c.rating_key: Placement(
            recommended=i < lib.recommended,
            home=i < lib.home,
            shared=i < lib.shared,
        )
        for i, c in enumerate(selection)
    }


def builtin_key(identifier: str) -> str:
    """Short name of a built-in row, as shown in the settings: "movie.recentlyadded" -> "recentlyadded"."""
    return identifier.rsplit(".", 1)[-1].lower()


def pinned_hubs(hubs: list[Hub], pinned: list[str]) -> list[str]:
    """Identifiers of the pinned built-in rows this library has, in the pinned order."""
    builtin = [h.identifier for h in hubs if h.collection_key is None]
    top: list[str] = []
    for p in pinned:
        p = p.strip().lower()
        if not p:
            continue
        for i in builtin:
            # Same key as the list in the settings ("recentlyreleased" for "movie.recentlyreleased"),
            # plus the older match on part of the name for "hub.*" rows.
            if (builtin_key(i) == p or (i.startswith("hub.") and p in i.lower())) and i not in top:
                top.append(i)
    return top


def kind_of(hub: Hub, automatic: set[str]) -> str:
    """Rough kind of a row, so similar rows can be spread out: all of Plex's automatic
    collections are one kind, otherwise the first word ("Best of 1980s", "Best of 1990s")."""
    key = hub.collection_key
    if key is None:
        return "*builtin"
    if key in automatic:
        return "*automatic"
    words = re.findall(r"[^\W\d_]+", hub.title.lower())
    return words[0] if words else ""


def spread(ids: list[str], kinds: dict[str, str], rng: random.Random) -> list[str]:
    """Random order with rows of the same kind spread evenly over the whole list.

    Each kind's rows get evenly spaced, slightly jittered places (2 of 10 rows near 25 % and 75 %),
    then rows that still follow one of the same kind swap with the next row of another kind.
    If one kind is more than half of all rows, some of them have to follow each other.
    """
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(kinds[i], []).append(i)
    placed: list[tuple[float, str]] = []
    for g in groups.values():
        rng.shuffle(g)
        placed += [((n + rng.random()) / len(g), i) for n, i in enumerate(g)]
    order = [i for _, i in sorted(placed)]
    if max((len(g) for g in groups.values()), default=0) * 2 > len(order) + 1:
        return order  # no order without neighbours of one kind; the even spacing is the best we can do
    for n in range(1, len(order)):
        if kinds[order[n]] == kinds[order[n - 1]]:
            swap = next((m for m in range(n + 1, len(order)) if kinds[order[m]] != kinds[order[n - 1]]), None)
            if swap is not None:
                order[n], order[swap] = order[swap], order[n]
    return order


def order_hubs(hubs: list[Hub], placed: dict[str, Placement], pinned: list[str], rng: random.Random,
               automatic: set[str] | None = None, trust_plex: bool = True) -> list[str]:
    """Target order for the visible rows: pinned built-in rows first, the rest shuffled with
    similar rows spread out.

    Hidden rows are left alone; they end up below the visible ones.
    """
    top = pinned_hubs(hubs, pinned)

    def will_be_visible(h: Hub) -> bool:
        key = h.collection_key
        if key is not None:
            # A row Plex still shows although it was hidden (e.g. Kometa sets it visible again)
            # is shuffled with the rest instead of piling up at the bottom.
            return (key in placed and placed[key].visible) or (trust_plex and h.visible)
        return h.visible

    rest = [h for h in hubs if h.identifier not in top and will_be_visible(h)]
    kinds = {h.identifier: kind_of(h, automatic or set()) for h in rest}
    return top + spread([h.identifier for h in rest], kinds, rng)


def keep_on_top(client: PlexClient, sid: str, target: list[str]) -> None:
    """Make sure the ordered rows really start at the top.

    Plex does not always move a row to the top when it is moved without "after". Rows that are
    still above the ordered ones are moved below them instead.
    """
    ids = [h.identifier for h in client.hubs(sid)]
    if target[0] not in ids:
        return
    above = [i for i in ids[:ids.index(target[0])] if i not in target]
    if not above:
        return
    log.info("Moving %d rows below the pinned rows because Plex kept them on top", len(above))
    prev = target[-1]
    for ident in above:
        client.move_hub(sid, ident, prev)
        prev = ident


def rotate_library(client: PlexClient, sid: str, title: str, lib: LibrarySettings, settings: Settings,
                   rng: random.Random | None = None) -> LibraryResult:
    rng = rng or random.Random()
    dry = settings.dry_run
    res = LibraryResult(title=title)

    collections = client.collections(sid)
    automatic = {c.rating_key for c in collections if c.automatic}
    pool = build_pool(collections, lib)
    selection = select(pool, lib, rng, state.recent(sid, settings.repeat_block_runs))
    selection = rank_for_home(selection, lib)
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

    # Pinned built-in rows: Plex often shows them only in Recommended. Switch on the home screens
    # chosen in the settings; a switch that is off leaves Plex's setting alone.
    by_id = {h.identifier: h for h in hubs}
    for ident in pinned_hubs(hubs, settings.pinned_rows):
        h = by_id[ident]
        home, shared = h.home or settings.pinned_home, h.shared or settings.pinned_shared
        # A pinned row always belongs in Recommended; this also repairs a row Plex switched off there.
        if (h.recommended, h.home, h.shared) != (True, home, shared):
            res.changed += 1
            if not dry:
                client.set_visibility(sid, ident, True, home, shared)

    # 2) Order. Pinned rows go on top even when the order is not shuffled.
    if not dry:
        hubs = client.hubs(sid)
    if lib.shuffle_order:
        if not dry:
            stuck = [h.title for h in hubs if h.collection_key and h.visible
                     and not (h.collection_key in placed and placed[h.collection_key].visible)]
            if stuck:
                log.warning("%s: %d rows are still visible although Rotatarr hid them, e.g. %s. "
                            "Does Kometa set visible_* for them?", title, len(stuck), ", ".join(stuck[:5]))
        # A dry run did not hide anything, so Plex's flags still show the old selection.
        target = order_hubs(hubs, placed, settings.pinned_rows, rng, automatic, trust_plex=not dry)
        if dry:
            # Newly created rows are not in `hubs` yet during a dry run.
            known = {h.identifier for h in hubs}
            target += [f"custom.collection.{sid}.{k}" for k, p in placed.items()
                       if p.visible and f"custom.collection.{sid}.{k}" not in known]
    else:
        target = pinned_hubs(hubs, settings.pinned_rows)
    prev = None
    for ident in target:
        if not dry:
            client.move_hub(sid, ident, prev)
        prev = ident
    if target and not dry:
        keep_on_top(client, sid, target)
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

"""Item shuffle: bring random titles to the front of every visible collection row."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import state
from .config import Settings
from .plex import PlexClient, is_on


@dataclass
class ShuffleResult:
    title: str
    shuffled: int = 0
    smart_skipped: int = 0
    lines: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"library": self.title, "shuffled": self.shuffled, "smart_skipped": self.smart_skipped}


def shuffle_library(client: PlexClient, sid: str, title: str, settings: Settings,
                    rng: random.Random | None = None) -> ShuffleResult:
    rng = rng or random.Random()
    res = ShuffleResult(title=title)
    smart_by_key = {c.rating_key: c.smart for c in client.collections(sid)}

    for hub in client.hubs(sid):
        key = hub.collection_key
        if key is None or not hub.visible:
            continue
        meta = None
        smart = smart_by_key.get(key)
        if smart is None:
            meta = client.collection_meta(key)
            smart = is_on(meta.get("smart"))
        if smart:
            # Plex cannot sort smart collections by hand. Use "random" sort in the smart filter instead.
            res.smart_skipped += 1
            continue
        items = client.collection_items(key)
        if len(items) < 2:
            continue
        if settings.dry_run:
            res.shuffled += 1
            continue
        meta = meta or client.collection_meta(key)
        current_sort = str(meta.get("collectionSort", "0"))
        if current_sort != "2":
            state.remember_sort(sid, key, current_sort)
            client.set_custom_sort(key)
        prev = None
        for item in rng.sample(items, min(settings.items_to_front, len(items))):
            client.move_item(key, item, prev)
            prev = item
        res.shuffled += 1

    res.lines.append(f"{title}: {res.shuffled} rows shuffled, {res.smart_skipped} smart collections skipped")
    return res

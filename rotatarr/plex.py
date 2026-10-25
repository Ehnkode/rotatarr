"""Thin client for the (unofficial) Plex Media Server endpoints Rotatarr needs."""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

import requests

from . import __version__

PRODUCT = "Rotatarr"
FLAGS = ("promotedToRecommended", "promotedToOwnHome", "promotedToSharedHome")
COLLECTION_HUB_PREFIX = "custom.collection."


def is_on(value) -> bool:
    return value in (True, 1, "1", "true")


def plex_headers(client_id: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Version": __version__,
        "X-Plex-Client-Identifier": client_id,
    }


@dataclass
class Hub:
    identifier: str
    title: str
    recommended: bool
    home: bool
    shared: bool

    @property
    def visible(self) -> bool:
        return self.recommended or self.home or self.shared

    @property
    def collection_key(self) -> str | None:
        # custom.collection.{sid}.{ratingKey}
        if not self.identifier.startswith(COLLECTION_HUB_PREFIX):
            return None
        return self.identifier.rsplit(".", 1)[-1]


@dataclass
class Collection:
    rating_key: str
    title: str
    child_count: int
    smart: bool | None  # None when the list endpoint did not say


class PlexClient:
    def __init__(self, url: str, token: str, client_id: str, timeout: int = 60):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(plex_headers(client_id))
        self.session.headers["X-Plex-Token"] = token
        self.timeout = timeout

    def _get(self, path: str, **params) -> dict:
        r = self.session.get(f"{self.url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("MediaContainer", {})

    def _send(self, method: str, path: str, **params) -> None:
        r = self.session.request(method, f"{self.url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()

    # --- server / libraries -------------------------------------------------

    def server_name(self) -> str:
        return self._get("/").get("friendlyName", "")

    def sections(self) -> list[dict]:
        return [
            {"key": str(d["key"]), "title": d.get("title", ""), "type": d.get("type", "")}
            for d in self._get("/library/sections").get("Directory", [])
        ]

    def collections(self, sid: str) -> list[Collection]:
        result = []
        for c in self._get(f"/library/sections/{sid}/collections").get("Metadata", []):
            smart = c.get("smart")
            result.append(Collection(
                rating_key=str(c["ratingKey"]),
                title=c.get("title", ""),
                child_count=int(c.get("childCount", 0) or 0),
                smart=None if smart is None else is_on(smart),
            ))
        return result

    # --- hubs (rows) ----------------------------------------------------------

    def hubs(self, sid: str) -> list[Hub]:
        return [
            Hub(
                identifier=h["identifier"],
                title=h.get("title", ""),
                recommended=is_on(h.get("promotedToRecommended")),
                home=is_on(h.get("promotedToOwnHome")),
                shared=is_on(h.get("promotedToSharedHome")),
            )
            for h in self._get(f"/hubs/sections/{sid}/manage").get("Hub", [])
        ]

    @staticmethod
    def _flags(recommended: bool, home: bool, shared: bool) -> dict[str, int]:
        return dict(zip(FLAGS, (int(recommended), int(home), int(shared))))

    def set_visibility(self, sid: str, identifier: str, recommended: bool, home: bool, shared: bool) -> None:
        q = urllib.parse.quote(identifier, safe="")
        self._send("PUT", f"/hubs/sections/{sid}/manage/{q}", **self._flags(recommended, home, shared))

    def create_collection_hub(self, sid: str, rating_key: str, recommended: bool, home: bool, shared: bool) -> None:
        self._send("POST", f"/hubs/sections/{sid}/manage", metadataItemId=rating_key,
                   **self._flags(recommended, home, shared))

    def move_hub(self, sid: str, identifier: str, after: str | None) -> None:
        q = urllib.parse.quote(identifier, safe="")
        params = {"after": after} if after else {}
        self._send("PUT", f"/hubs/sections/{sid}/manage/{q}/move", **params)

    # --- items inside a collection ------------------------------------------

    def collection_meta(self, rating_key: str) -> dict:
        items = self._get(f"/library/metadata/{rating_key}").get("Metadata", [])
        return items[0] if items else {}

    def collection_items(self, rating_key: str) -> list[str]:
        return [str(i["ratingKey"]) for i in self._get(f"/library/collections/{rating_key}/children").get("Metadata", [])]

    def set_custom_sort(self, rating_key: str) -> None:
        self._send("PUT", f"/library/metadata/{rating_key}/prefs", collectionSort=2)

    def move_item(self, rating_key: str, item: str, after: str | None) -> None:
        params = {"after": after} if after else {}
        self._send("PUT", f"/library/collections/{rating_key}/items/{item}/move", **params)

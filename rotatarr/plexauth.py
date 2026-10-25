"""Sign in with Plex (PIN flow) and list the servers of the account."""

from __future__ import annotations

import urllib.parse

import requests

from .plex import PRODUCT, plex_headers

PLEX_TV = "https://plex.tv/api/v2"


def create_pin(client_id: str) -> dict:
    r = requests.post(f"{PLEX_TV}/pins", params={"strong": "true"}, headers=plex_headers(client_id), timeout=30)
    r.raise_for_status()
    pin = r.json()
    query = urllib.parse.urlencode({
        "clientID": client_id,
        "code": pin["code"],
        "context[device][product]": PRODUCT,
    })
    return {"id": pin["id"], "auth_url": f"https://app.plex.tv/auth#?{query}"}


def check_pin(client_id: str, pin_id: int) -> str | None:
    """Return the account token once the user has approved the PIN."""
    r = requests.get(f"{PLEX_TV}/pins/{pin_id}", headers=plex_headers(client_id), timeout=30)
    r.raise_for_status()
    return r.json().get("authToken") or None


def servers(client_id: str, account_token: str) -> list[dict]:
    headers = plex_headers(client_id) | {"X-Plex-Token": account_token}
    r = requests.get(f"{PLEX_TV}/resources", params={"includeHttps": 1, "includeRelay": 0},
                     headers=headers, timeout=30)
    r.raise_for_status()
    result = []
    for res in r.json():
        if "server" not in (res.get("provides") or "") or not res.get("owned"):
            continue
        connections = sorted(res.get("connections", []), key=lambda c: (not c.get("local"), c.get("relay", False)))
        result.append({
            "name": res.get("name", ""),
            "token": res.get("accessToken") or account_token,
            "connections": [{"uri": c["uri"], "local": bool(c.get("local"))} for c in connections],
        })
    return result

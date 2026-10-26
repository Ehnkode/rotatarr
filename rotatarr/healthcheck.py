"""Docker health check: asks the running web UI for its state, with the login if one is set."""

from __future__ import annotations

import base64
import os
import sys
import urllib.request


def request() -> urllib.request.Request:
    req = urllib.request.Request(f"http://127.0.0.1:{os.environ.get('PORT', '7373')}/api/state")
    password = os.environ.get("ROTATARR_PASSWORD", "")
    if password:
        login = f"{os.environ.get('ROTATARR_USERNAME', '')}:{password}".encode()
        req.add_header("Authorization", "Basic " + base64.b64encode(login).decode())
    return req


def main() -> int:
    try:
        urllib.request.urlopen(request(), timeout=4)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

import requests

from rotatarr import plex
from rotatarr.plex import PlexClient


class Response:
    def raise_for_status(self):
        pass

    def json(self):
        return {"MediaContainer": {"friendlyName": "Home"}}


def test_retries_after_timeout(monkeypatch):
    monkeypatch.setattr(plex.time, "sleep", lambda s: None)
    client = PlexClient("http://plex", "token", "id")
    calls = []

    def request(method, url, **kw):
        calls.append(method)
        if len(calls) < 3:
            raise requests.Timeout("slow")
        return Response()

    monkeypatch.setattr(client.session, "request", request)
    assert client.server_name() == "Home"
    assert len(calls) == 3


def test_post_is_not_retried(monkeypatch):
    monkeypatch.setattr(plex.time, "sleep", lambda s: None)
    client = PlexClient("http://plex", "token", "id")
    calls = []

    def request(method, url, **kw):
        calls.append(method)
        raise requests.Timeout("slow")

    monkeypatch.setattr(client.session, "request", request)
    try:
        client.create_collection_hub("1", "42", True, True, True)
    except requests.Timeout:
        pass
    assert calls == ["POST"]


def test_detects_automatic_collections(monkeypatch):
    client = PlexClient("http://plex", "token", "id")
    data = {"Metadata": [
        {"ratingKey": 1, "title": "Harry Potter Filmreihe", "guid": "plex://collection/5d9f", "childCount": 8},
        {"ratingKey": 2, "title": "IMDb Top 250", "guid": "collection://41a2", "childCount": 96},
    ]}
    monkeypatch.setattr(client, "_get", lambda path, **params: data)
    assert [c.automatic for c in client.collections("1")] == [True, False]

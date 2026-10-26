import pytest

from rotatarr import notify
from rotatarr.config import Settings

WEBHOOK = "https://discord.com/api/webhooks/1/abc"


def test_only_discord_webhooks_are_accepted():
    assert Settings(discord_webhook=WEBHOOK).discord_webhook == WEBHOOK
    with pytest.raises(ValueError):
        Settings(discord_webhook="http://192.168.1.10/hook")


@pytest.mark.parametrize("ok, success, sent", [(False, False, True), (True, False, False), (True, True, True)])
def test_report_failures_always_successes_on_request(monkeypatch, ok, success, sent):
    calls = []
    monkeypatch.setattr(notify, "send", lambda url, text: calls.append(text))
    settings = Settings(discord_webhook=WEBHOOK, notify_success=success)
    notify.report(settings, {"kind": "rotate", "ok": ok, "lines": ["Movies: 20 of 40"]})
    assert bool(calls) == sent


def test_broken_webhook_does_not_break_a_run(monkeypatch):
    def boom(url, text):
        raise OSError("down")
    monkeypatch.setattr(notify, "send", boom)
    notify.report(Settings(discord_webhook=WEBHOOK), {"kind": "rotate", "ok": False, "lines": []})

import json

from app import notify


def test_noop_without_webhook_url(monkeypatch):
    monkeypatch.setattr(notify, "WEBHOOK_URL", "")
    calls = []
    monkeypatch.setattr(notify.urllib.request, "urlopen", lambda *a, **k: calls.append(1))
    notify.notify_new_ticket("Acme", 1, 1, "rimborso")
    assert calls == []


def test_posts_json_payload_when_configured(monkeypatch):
    monkeypatch.setattr(notify, "WEBHOOK_URL", "https://hooks.example.com/x")
    captured = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout

    monkeypatch.setattr(notify.urllib.request, "urlopen", _fake_urlopen)
    notify.notify_new_ticket("Acme", 42, 7, "rimborso ordine 123")

    assert captured["url"] == "https://hooks.example.com/x"
    assert captured["body"]["ticket_id"] == 7
    assert captured["body"]["conversation_id"] == 42
    assert "Acme" in captured["body"]["text"]


def test_swallows_errors_without_raising(monkeypatch):
    monkeypatch.setattr(notify, "WEBHOOK_URL", "https://hooks.example.com/x")

    def _raise(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", _raise)
    notify.notify_new_ticket("Acme", 1, 1, "rimborso")  # must not raise

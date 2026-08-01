"""Unit tests for the email provider dispatch (no DB / no network)."""
from app import email


class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def _use_brevo(monkeypatch):
    monkeypatch.setattr(email, "EMAIL_PROVIDER", "brevo_api")
    monkeypatch.setattr(email, "BREVO_API_KEY", "test-key")


def test_brevo_api_send_success(monkeypatch):
    _use_brevo(monkeypatch)
    monkeypatch.setattr(email.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp())
    assert email.send_email("x@y.it", "subj", "body") is True


def test_brevo_thread_headers_are_forwarded(monkeypatch):
    _use_brevo(monkeypatch)
    captured = {}

    def fake_open(req, timeout=None):
        import json

        captured.update(json.loads(req.data))
        return _FakeResp()

    monkeypatch.setattr(email.urllib.request, "urlopen", fake_open)
    assert email.send_channel_reply(
        "x@y.it", "Acme", "Ordine 42", "È stato spedito", "<root@example.it>"
    ) is True
    assert captured["subject"] == "Re: Ordine 42"
    assert captured["headers"] == {
        "In-Reply-To": "<root@example.it>",
        "References": "<root@example.it>",
    }


def test_channel_reply_strips_header_newlines(monkeypatch):
    _use_brevo(monkeypatch)
    captured = {}

    def fake_open(req, timeout=None):
        import json

        captured.update(json.loads(req.data))
        return _FakeResp()

    monkeypatch.setattr(email.urllib.request, "urlopen", fake_open)
    assert email.send_channel_reply(
        "x@y.it", "Acme", "Ordine\r\nBcc: victim@example.it", "ok", "<root>\r\nX-Bad: yes"
    ) is True
    assert "\n" not in captured["subject"]
    assert "\n" not in captured["headers"]["In-Reply-To"]


def test_brevo_api_send_failure_returns_false(monkeypatch):
    _use_brevo(monkeypatch)

    def _boom(req, timeout=None):
        raise Exception("network down")

    monkeypatch.setattr(email.urllib.request, "urlopen", _boom)
    assert email.send_email("x@y.it", "subj", "body") is False


def test_not_configured_logs_only(monkeypatch):
    # no provider configured => logged-only, returns True (dev fallback)
    monkeypatch.setattr(email, "EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(email, "SMTP_HOST", "")
    assert email.send_email("x@y.it", "subj", "body") is True


def test_config_status_reports_provider(monkeypatch):
    _use_brevo(monkeypatch)
    status = email.config_status()
    assert status["provider"] == "brevo_api"
    assert status["configured"] is True

import json

from app import whatsapp


class _Response:
    status = 202

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_send_message_posts_normalized_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_URL", "https://adapter.example/send")
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_TOKEN", "adapter-secret")

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return _Response()

    monkeypatch.setattr(whatsapp.urllib.request, "urlopen", fake_urlopen)
    assert whatsapp.send_message(
        client_id=7,
        to="+393331234567",
        body="Risposta operatore",
        reply_to_message_id="wamid.001",
    ) is True
    assert captured["request"].full_url == "https://adapter.example/send"
    assert captured["request"].headers["Authorization"] == "Bearer adapter-secret"
    assert json.loads(captured["request"].data) == {
        "client_id": 7,
        "to": "+393331234567",
        "type": "text",
        "text": "Risposta operatore",
        "reply_to_message_id": "wamid.001",
    }


def test_send_message_fails_closed_without_configuration(monkeypatch):
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_URL", "")
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_TOKEN", "")
    monkeypatch.setattr(
        whatsapp.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()),
    )
    assert whatsapp.send_message(client_id=7, to="+393331234567", body="test") is False


def test_send_template_posts_approved_template_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_URL", "https://adapter.example/send")
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_TOKEN", "adapter-secret")
    monkeypatch.setattr(
        whatsapp.urllib.request,
        "urlopen",
        lambda request, timeout: captured.update(request=request, timeout=timeout) or _Response(),
    )
    assert whatsapp.send_template(
        client_id=7, to="+393331234567", template="aggiornamento_ordine",
        language="it", parameters=["Mario", "123"],
    ) is True
    assert json.loads(captured["request"].data)["type"] == "template"
    assert json.loads(captured["request"].data)["parameters"] == ["Mario", "123"]

import io
import json

from sqlmodel import Session, select

from app import db, meta_messaging


def _payload(**overrides):
    data = {
        "platform": "messenger",
        "sender_id": "psid_12345",
        "sender_name": "Mario Rossi",
        "text": "Ho bisogno di assistenza.",
        "message_id": "mid.001",
        "thread_id": "thread.001",
    }
    data.update(overrides)
    return data


def _channel_key(client, tenant):
    created = client.post(
        "/api-keys", headers=tenant["op"],
        json={"name": "Meta adapter", "scopes": ["channels:write"]},
    )
    assert created.status_code == 200
    return {"Authorization": f"Bearer {created.json()['token']}"}


def test_messenger_inbound_creates_thread_contact_ticket_and_is_idempotent(client, tenant):
    headers = _channel_key(client, tenant)
    first = client.post("/channels/meta/inbound", headers=headers, json=_payload())
    duplicate = client.post("/channels/meta/inbound", headers=headers, json=_payload())
    assert first.status_code == 200 and first.json()["created"] is True
    assert duplicate.json() == {"ok": True, "created": False, "conversation_id": first.json()["conversation_id"]}
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, first.json()["conversation_id"])
        contact = session.get(db.Contact, conv.contact_id)
        messages = session.exec(select(db.Message).where(db.Message.conversation_id == conv.id)).all()
        tickets = session.exec(select(db.Ticket).where(db.Ticket.conversation_id == conv.id)).all()
        assert (conv.channel, conv.external_thread_id, conv.status) == ("messenger", "thread.001", "escalated")
        assert (contact.channel, contact.external_id, contact.name) == ("messenger", "psid_12345", "Mario Rossi")
        assert [(m.role, m.external_id) for m in messages] == [("user", "mid.001")]
        assert len(tickets) == 1


def test_instagram_is_separate_and_appends_to_its_thread(client, tenant):
    headers = _channel_key(client, tenant)
    first = client.post(
        "/channels/meta/inbound", headers=headers,
        json=_payload(platform="instagram", message_id="ig.mid.1", thread_id="ig.thread.1"),
    ).json()
    second = client.post(
        "/channels/meta/inbound", headers=headers,
        json=_payload(platform="instagram", message_id="ig.mid.2", thread_id="ig.thread.1", text="Ci siete?"),
    ).json()
    assert second["conversation_id"] == first["conversation_id"]
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, first["conversation_id"])
        messages = session.exec(select(db.Message).where(db.Message.conversation_id == conv.id)).all()
        assert conv.channel == "instagram"
        assert len(messages) == 2


def test_operator_reply_uses_meta_adapter(client, tenant, monkeypatch):
    conv_id = client.post(
        "/channels/meta/inbound", headers=_channel_key(client, tenant), json=_payload()
    ).json()["conversation_id"]
    sent = {}
    monkeypatch.setattr(meta_messaging, "send_message", lambda **kwargs: sent.update(kwargs) or True)
    response = client.post(
        f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "Come possiamo aiutarti?"},
    )
    assert response.json() == {"ok": True, "delivered": True}
    assert sent == {
        "client_id": tenant["cid"], "platform": "messenger", "recipient_id": "psid_12345",
        "body": "Come possiamo aiutarti?", "reply_to_message_id": "mid.001",
    }


def test_meta_inbound_is_tenant_scoped_and_rejects_widget_key(client, tenant):
    first = client.post(
        "/channels/meta/inbound", headers=_channel_key(client, tenant), json=_payload()
    ).json()
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other Meta"}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=admin,
        json={"email": "other-meta@example.it", "password": "password1"},
    )
    token = client.post(
        "/operator/login", json={"email": "other-meta@example.it", "password": "password1"},
    ).json()["token"]
    second = client.post(
        "/channels/meta/inbound",
        headers=_channel_key(client, {"op": {"Authorization": f"Bearer {token}"}}),
        json=_payload(),
    ).json()
    assert first["conversation_id"] != second["conversation_id"]
    assert client.post(
        "/channels/meta/inbound", headers=tenant["key"], json=_payload(message_id="mid.003")
    ).status_code == 401


def test_meta_inbound_validates_normalized_fields(client, tenant):
    headers = _channel_key(client, tenant)
    assert client.post("/channels/meta/inbound", headers=headers, json=_payload(platform="whatsapp")).status_code == 400
    assert client.post("/channels/meta/inbound", headers=headers, json=_payload(sender_id="bad sender")).status_code == 400
    assert client.post("/channels/meta/inbound", headers=headers, json=_payload(text=" ")).status_code == 400
    assert client.post("/channels/meta/inbound", headers=headers, json=_payload(message_id="")).status_code == 400


def test_meta_outbound_payload_and_missing_config(monkeypatch):
    monkeypatch.setattr(meta_messaging, "META_MESSAGING_OUTBOUND_URL", "https://adapter.example/send")
    monkeypatch.setattr(meta_messaging, "META_MESSAGING_OUTBOUND_TOKEN", "secret")
    captured = {}

    class Response(io.BytesIO):
        status = 202
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout):
        captured.update(payload=json.loads(request.data), authorization=request.headers["Authorization"], timeout=timeout)
        return Response()

    monkeypatch.setattr(meta_messaging.urllib.request, "urlopen", fake_urlopen)
    assert meta_messaging.send_message(
        client_id=7, platform="instagram", recipient_id="ig_1", body="Ciao", reply_to_message_id="mid_1"
    ) is True
    assert captured["payload"] == {
        "client_id": 7, "platform": "instagram", "recipient_id": "ig_1",
        "text": "Ciao", "reply_to_message_id": "mid_1",
    }
    monkeypatch.setattr(meta_messaging, "META_MESSAGING_OUTBOUND_URL", "")
    assert meta_messaging.send_message(client_id=7, platform="messenger", recipient_id="x", body="x") is False

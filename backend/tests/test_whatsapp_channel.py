from datetime import datetime, timedelta

from sqlmodel import Session, select

from app import db, whatsapp as whatsapp_service


def _payload(**overrides):
    data = {"from_number": "+393331234567", "from_name": "Mario Rossi", "text": "Aiuto ordine.", "message_id": "wamid.001"}
    data.update(overrides)
    return data


def _channel_key(client, tenant):
    created = client.post("/api-keys", headers=tenant["op"], json={"name": "WhatsApp adapter", "scopes": ["channels:write"]})
    assert created.status_code == 200
    return {"Authorization": f"Bearer {created.json()['token']}"}


def test_inbound_whatsapp_creates_thread_contact_ticket_and_is_idempotent(client, tenant):
    headers = _channel_key(client, tenant)
    first = client.post("/channels/whatsapp/inbound", headers=headers, json=_payload())
    assert first.status_code == 200 and first.json()["created"] is True
    duplicate = client.post("/channels/whatsapp/inbound", headers=headers, json=_payload())
    assert duplicate.json() == {"ok": True, "created": False, "conversation_id": first.json()["conversation_id"]}
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, first.json()["conversation_id"])
        contact = session.get(db.Contact, conv.contact_id)
        messages = session.exec(select(db.Message).where(db.Message.conversation_id == conv.id)).all()
        tickets = session.exec(select(db.Ticket).where(db.Ticket.conversation_id == conv.id)).all()
        assert (conv.channel, conv.status, conv.external_thread_id) == ("whatsapp", "escalated", "+393331234567")
        assert (contact.external_id, contact.name) == ("+393331234567", "Mario Rossi")
        assert [(m.role, m.external_id) for m in messages] == [("user", "wamid.001")]
        assert len(tickets) == 1


def test_messages_from_same_number_append_to_open_conversation(client, tenant):
    headers = _channel_key(client, tenant)
    first = client.post("/channels/whatsapp/inbound", headers=headers, json=_payload()).json()
    second = client.post("/channels/whatsapp/inbound", headers=headers, json=_payload(message_id="wamid.002", text="Ci siete?")).json()
    assert second["conversation_id"] == first["conversation_id"]


def test_operator_reply_uses_adapter_inside_customer_service_window(client, tenant, monkeypatch):
    conv_id = client.post("/channels/whatsapp/inbound", headers=_channel_key(client, tenant), json=_payload()).json()["conversation_id"]
    sent = {}
    monkeypatch.setattr(whatsapp_service, "send_message", lambda **kwargs: sent.update(kwargs) or True)
    response = client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "Come possiamo aiutarti?"})
    assert response.json() == {"ok": True, "delivered": True}
    assert sent == {"client_id": tenant["cid"], "to": "+393331234567", "body": "Come possiamo aiutarti?", "reply_to_message_id": "wamid.001"}


def test_operator_free_form_reply_is_blocked_after_24_hours(client, tenant, monkeypatch):
    conv_id = client.post("/channels/whatsapp/inbound", headers=_channel_key(client, tenant), json=_payload()).json()["conversation_id"]
    with Session(db.engine) as session:
        message = session.exec(select(db.Message).where(db.Message.conversation_id == conv_id, db.Message.role == "user")).one()
        message.created_at = datetime.utcnow() - timedelta(hours=25)
        session.add(message)
        session.commit()
    monkeypatch.setattr(whatsapp_service, "send_message", lambda **kwargs: (_ for _ in ()).throw(AssertionError()))
    response = client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "Messaggio tardivo"})
    assert response.json() == {"ok": True, "delivered": False}


def test_whatsapp_is_tenant_scoped_and_rejects_widget_key(client, tenant):
    first = client.post("/channels/whatsapp/inbound", headers=_channel_key(client, tenant), json=_payload()).json()
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other"}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=admin, json={"email": "other-wa@example.it", "password": "password1"})
    token = client.post("/operator/login", json={"email": "other-wa@example.it", "password": "password1"}).json()["token"]
    second = client.post("/channels/whatsapp/inbound", headers=_channel_key(client, {"op": {"Authorization": f"Bearer {token}"}}), json=_payload()).json()
    assert first["conversation_id"] != second["conversation_id"]
    assert client.post("/channels/whatsapp/inbound", headers=tenant["key"], json=_payload(message_id="wamid.003")).status_code == 401


def test_inbound_whatsapp_validates_normalized_fields(client, tenant):
    headers = _channel_key(client, tenant)
    assert client.post("/channels/whatsapp/inbound", headers=headers, json=_payload(from_number="333")).status_code == 400
    assert client.post("/channels/whatsapp/inbound", headers=headers, json=_payload(text=" ")).status_code == 400
    assert client.post("/channels/whatsapp/inbound", headers=headers, json=_payload(message_id="")).status_code == 400

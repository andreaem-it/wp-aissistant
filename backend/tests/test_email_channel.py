from sqlmodel import Session, select

from app import db, email as email_service


def _payload(**overrides):
    data = {
        "from_email": "mario@example.it",
        "from_name": "Mario Rossi",
        "subject": "Problema con un ordine",
        "text": "Non riesco a trovare il mio ordine.",
        "message_id": "<msg-1@example.it>",
        "thread_id": "<thread-1@example.it>",
    }
    data.update(overrides)
    return data


def _channel_key(client, tenant):
    created = client.post(
        "/api-keys",
        headers=tenant["op"],
        json={"name": "Email adapter", "scopes": ["channels:write"]},
    )
    assert created.status_code == 200
    return {"Authorization": f"Bearer {created.json()['token']}"}


def test_inbound_email_creates_escalated_thread_and_is_idempotent(client, tenant):
    channel_key = _channel_key(client, tenant)
    first = client.post("/channels/email/inbound", headers=channel_key, json=_payload())
    assert first.status_code == 200
    assert first.json()["created"] is True

    duplicate = client.post("/channels/email/inbound", headers=channel_key, json=_payload())
    assert duplicate.status_code == 200
    assert duplicate.json() == {
        "ok": True,
        "created": False,
        "conversation_id": first.json()["conversation_id"],
    }

    with Session(db.engine) as session:
        conv = session.get(db.Conversation, first.json()["conversation_id"])
        assert conv.client_id == tenant["cid"]
        assert conv.channel == "email"
        assert conv.status == "escalated"
        assert conv.channel_subject == "Problema con un ordine"
        assert conv.external_thread_id == "<thread-1@example.it>"
        contact = session.get(db.Contact, conv.contact_id)
        assert (contact.email, contact.name) == ("mario@example.it", "Mario Rossi")
        messages = session.exec(select(db.Message).where(db.Message.conversation_id == conv.id)).all()
        assert [(m.role, m.external_id) for m in messages] == [("user", "<msg-1@example.it>")]


def test_inbound_email_appends_same_thread_and_reuses_contact(client, tenant):
    channel_key = _channel_key(client, tenant)
    first = client.post("/channels/email/inbound", headers=channel_key, json=_payload()).json()
    second = client.post(
        "/channels/email/inbound",
        headers=channel_key,
        json=_payload(message_id="<msg-2@example.it>", text="Avete aggiornamenti?"),
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == first["conversation_id"]

    with Session(db.engine) as session:
        conv = session.get(db.Conversation, first["conversation_id"])
        messages = session.exec(select(db.Message).where(db.Message.conversation_id == conv.id)).all()
        tickets = session.exec(select(db.Ticket).where(db.Ticket.conversation_id == conv.id)).all()
        contacts = session.exec(
            select(db.Contact).where(db.Contact.client_id == tenant["cid"], db.Contact.channel == "email")
        ).all()
        assert len(messages) == 2
        assert len(tickets) == 1
        assert len(contacts) == 1


def test_operator_reply_is_delivered_as_threaded_email(client, tenant, monkeypatch):
    conv_id = client.post("/channels/email/inbound", headers=_channel_key(client, tenant), json=_payload()).json()[
        "conversation_id"
    ]
    sent = {}

    def fake_send(to, client_name, subject, body, thread_id="", client_id=None):
        sent.update(to=to, client_name=client_name, subject=subject, body=body,
                    thread_id=thread_id, client_id=client_id)
        return True

    monkeypatch.setattr(email_service, "send_channel_reply", fake_send)
    response = client.post(
        f"/conversations/{conv_id}/reply",
        headers=tenant["op"],
        json={"reply": "Il tuo ordine è in consegna."},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "delivered": True}
    assert sent == {
        "to": "mario@example.it",
        "client_name": "Acme",
        "subject": "Problema con un ordine",
        "body": "Il tuo ordine è in consegna.",
        "thread_id": "<thread-1@example.it>",
        "client_id": tenant["cid"],  # senza, il messaggio non entra nel costo del tenant
    }


def test_email_threads_are_tenant_scoped(client, tenant):
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other"}).json()
    first = client.post("/channels/email/inbound", headers=_channel_key(client, tenant), json=_payload()).json()
    client.post(
        f"/admin/clients/{other['id']}/operators",
        headers=admin,
        json={"email": "other@example.it", "password": "password1"},
    )
    other_token = client.post(
        "/operator/login", json={"email": "other@example.it", "password": "password1"}
    ).json()["token"]
    other_key = _channel_key(client, {"op": {"Authorization": f"Bearer {other_token}"}})
    second = client.post(
        "/channels/email/inbound",
        headers=other_key,
        json=_payload(),
    ).json()
    assert first["conversation_id"] != second["conversation_id"]


def test_inbound_email_validates_required_fields(client, tenant):
    channel_key = _channel_key(client, tenant)
    assert client.post(
        "/channels/email/inbound", headers=channel_key, json=_payload(from_email="not-an-email")
    ).status_code == 400
    assert client.post(
        "/channels/email/inbound", headers=channel_key, json=_payload(text="  ")
    ).status_code == 400
    assert client.post(
        "/channels/email/inbound", headers=channel_key, json=_payload(message_id="")
    ).status_code == 400


def test_public_widget_key_cannot_inject_email(client, tenant):
    response = client.post("/channels/email/inbound", headers=tenant["key"], json=_payload())
    assert response.status_code == 401

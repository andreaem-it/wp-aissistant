from sqlmodel import Session, select

from app import db
from conftest import TENANT_ORIGIN


ADMIN = {"Authorization": "Bearer test-admin"}


def _new_chat(client, tenant, visitor_id):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor_id, "message": "ciao"}
    ).json()


def test_web_conversations_reuse_tenant_contact(client, tenant):
    first = _new_chat(client, tenant, "browser-123")
    second = _new_chat(client, tenant, "browser-123")
    with Session(db.engine) as session:
        conversations = session.exec(
            select(db.Conversation).where(db.Conversation.id.in_([first["conversation_id"], second["conversation_id"]]))
        ).all()
        assert len({conv.contact_id for conv in conversations}) == 1
        contact = session.get(db.Contact, conversations[0].contact_id)
        assert contact.client_id == tenant["cid"]
        assert contact.channel == "web"
        assert contact.external_id == "browser-123"


def test_contact_identity_is_isolated_between_tenants(client, tenant):
    first = _new_chat(client, tenant, "same-browser")
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other Channels", "allowed_origins": TENANT_ORIGIN}).json()
    second = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {other['api_key']}"},
        json={"visitor_id": "same-browser", "message": "ciao"},
    ).json()
    with Session(db.engine) as session:
        a = session.get(db.Conversation, first["conversation_id"])
        b = session.get(db.Conversation, second["conversation_id"])
        assert a.contact_id != b.contact_id
        assert session.get(db.Contact, a.contact_id).client_id == tenant["cid"]
        assert session.get(db.Contact, b.contact_id).client_id == other["id"]


def test_visitor_email_enriches_contact_and_channel_filter_works(client, tenant):
    created = _new_chat(client, tenant, "email-browser")
    response = client.post("/chat/contact", headers=tenant["key"], json={
        "conversation_id": created["conversation_id"],
        "conversation_token": created["conversation_token"],
        "email": "Person@Example.IT",
    })
    assert response.status_code == 200
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, created["conversation_id"])
        assert conv.channel == "web"
        assert session.get(db.Contact, conv.contact_id).email == "person@example.it"

    rows = client.get("/conversations", headers=tenant["op"], params={"channel": "web"}).json()
    assert any(row["conversation"]["id"] == created["conversation_id"] for row in rows)
    assert client.get("/conversations", headers=tenant["op"], params={"channel": "invalid"}).status_code == 400

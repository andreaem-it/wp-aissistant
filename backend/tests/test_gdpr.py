"""GDPR: conversation erasure (cascade), erase-by-email, retention purge."""
import datetime as _dt

from sqlmodel import Session, select

from app import db, main

ADMIN = {"Authorization": "Bearer test-admin"}


def _escalated_with_email(client, tenant, email):
    """A conversation with messages, a ticket and captured visitor email."""
    created = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "rimborso"}).json()
    client.post("/chat/contact", headers=tenant["key"], json={
        "conversation_id": created["conversation_id"],
        "conversation_token": created["conversation_token"],
        "email": email,
    })
    return created["conversation_id"]


def _counts(conv_id):
    with Session(db.engine) as s:
        msgs = len(s.exec(select(db.Message).where(db.Message.conversation_id == conv_id)).all())
        logs = len(s.exec(select(db.AiResponseLog).where(db.AiResponseLog.conversation_id == conv_id)).all())
        tickets = len(s.exec(select(db.Ticket).where(db.Ticket.conversation_id == conv_id)).all())
        conv = s.get(db.Conversation, conv_id)
    return conv, msgs, logs, tickets


def test_delete_conversation_cascades(client, tenant):
    conv_id = _escalated_with_email(client, tenant, "v@x.it")
    _, msgs, logs, tickets = _counts(conv_id)
    assert msgs and tickets  # something to delete

    assert client.delete(f"/conversations/{conv_id}", headers=tenant["op"]).status_code == 200
    conv, msgs, logs, tickets = _counts(conv_id)
    assert conv is None and msgs == 0 and logs == 0 and tickets == 0


def test_delete_scoped_to_client(client, tenant):
    conv_id = _escalated_with_email(client, tenant, "v@x.it")
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": "o2@x.it", "password": "password1"})
    tok = client.post("/operator/login", json={"email": "o2@x.it", "password": "password1"}).json()["token"]
    assert client.delete(f"/conversations/{conv_id}", headers={"Authorization": f"Bearer {tok}"}).status_code == 404


def test_gdpr_erase_by_email(client, tenant):
    a = _escalated_with_email(client, tenant, "person@x.it")
    b = _escalated_with_email(client, tenant, "person@x.it")
    c = _escalated_with_email(client, tenant, "other@x.it")
    r = client.post("/gdpr/erase", headers=tenant["op"], json={"email": "person@x.it"}).json()
    assert r["deleted"] == 2
    with Session(db.engine) as s:
        assert s.get(db.Conversation, a) is None and s.get(db.Conversation, b) is None
        assert s.get(db.Conversation, c) is not None  # different email untouched


def test_retention_purge_deletes_old(client, tenant):
    conv_id = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()["conversation_id"]
    # backdate the conversation past the retention window
    with Session(db.engine) as s:
        conv = s.get(db.Conversation, conv_id)
        conv.created_at = _dt.datetime.utcnow() - _dt.timedelta(days=40)
        s.add(conv)
        s.commit()
        purged = main.purge_old_conversations(s, days=30)
    assert purged >= 1
    with Session(db.engine) as s:
        assert s.get(db.Conversation, conv_id) is None

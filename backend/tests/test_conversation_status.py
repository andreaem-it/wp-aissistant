"""Close/reopen a conversation + auto-reopen on a new visitor message."""
from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _conv(client, tenant, msg="ciao"):
    return client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": msg}).json()["conversation_id"]


def test_close_and_reopen(client, tenant):
    cid = _conv(client, tenant)
    r = client.post(f"/conversations/{cid}/status", headers=tenant["op"], json={"status": "closed"})
    assert r.status_code == 200 and r.json()["status"] == "closed"
    with Session(db.engine) as s:
        conv = s.get(db.Conversation, cid)
        assert conv.status == "closed" and conv.closed_at is not None
    # reopen
    client.post(f"/conversations/{cid}/status", headers=tenant["op"], json={"status": "open"})
    with Session(db.engine) as s:
        conv = s.get(db.Conversation, cid)
        assert conv.status == "open" and conv.closed_at is None


def test_invalid_status_rejected(client, tenant):
    cid = _conv(client, tenant)
    assert client.post(f"/conversations/{cid}/status", headers=tenant["op"], json={"status": "banana"}).status_code == 400


def test_scoped_to_client(client, tenant):
    cid = _conv(client, tenant)
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": "o2@x.it", "password": "password1"})
    tok = client.post("/operator/login", json={"email": "o2@x.it", "password": "password1"}).json()["token"]
    denied = client.post(f"/conversations/{cid}/status", headers={"Authorization": f"Bearer {tok}"}, json={"status": "closed"})
    assert denied.status_code == 404


def test_new_visitor_message_reopens_closed(client, tenant):
    cid = _conv(client, tenant)
    client.post(f"/conversations/{cid}/status", headers=tenant["op"], json={"status": "closed"})
    # visitor writes again -> conversation auto-reopens
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "altra domanda", "conversation_id": cid})
    with Session(db.engine) as s:
        assert s.get(db.Conversation, cid).status == "open"

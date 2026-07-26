"""Fase 3a instrumentation: AiResponseLog per /chat turn, conversation timestamps, audit log,
and the admin debug/audit read endpoints. LLM + embeddings are mocked by the conftest fixtures."""
from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _logs(conversation_id):
    with Session(db.engine) as session:
        return session.exec(
            select(db.AiResponseLog).where(db.AiResponseLog.conversation_id == conversation_id)
            .order_by(db.AiResponseLog.id)
        ).all()


def test_answered_turn_is_logged(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = r.json()["conversation_id"]
    logs = _logs(conv_id)
    assert len(logs) == 1
    assert logs[0].outcome == "answered"
    assert logs[0].message_id is not None  # links to the assistant Message


def test_keyword_escalation_is_logged(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "vorrei un rimborso"})
    conv_id = r.json()["conversation_id"]
    logs = _logs(conv_id)
    assert len(logs) == 1
    assert logs[0].outcome == "escalated_keyword"


def test_conversation_updated_at_advances(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = r.json()["conversation_id"]
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, conv_id)
        assert conv.updated_at >= conv.created_at


def test_admin_conversation_debug(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = r.json()["conversation_id"]
    debug = client.get(f"/admin/conversations/{conv_id}/debug", headers=ADMIN)
    assert debug.status_code == 200
    body = debug.json()
    assert body["conversation"]["id"] == conv_id
    assert any(m["role"] == "user" for m in body["messages"])
    assert len(body["ai_turns"]) == 1
    assert body["ai_turns"][0]["outcome"] == "answered"
    assert isinstance(body["ai_turns"][0]["retrieved"], list)  # JSON parsed back


def test_admin_debug_requires_admin(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = r.json()["conversation_id"]
    assert client.get(f"/admin/conversations/{conv_id}/debug").status_code == 401


def test_audit_log_records_admin_actions(client):
    c = client.post("/admin/clients", headers=ADMIN, json={"name": "Acme"}).json()
    client.post(f"/admin/clients/{c['id']}/rotate-key", headers=ADMIN)
    audit = client.get("/admin/audit", headers=ADMIN).json()
    actions = [a["action"] for a in audit]
    assert "client.create" in actions
    assert "client.rotate_key" in actions
    # newest first
    assert audit[0]["id"] > audit[-1]["id"]


def test_audit_filter_by_client(client):
    a = client.post("/admin/clients", headers=ADMIN, json={"name": "A"}).json()
    b = client.post("/admin/clients", headers=ADMIN, json={"name": "B"}).json()
    only_b = client.get("/admin/audit", headers=ADMIN, params={"client_id": b["id"]}).json()
    assert only_b
    assert all(x["client_id"] == b["id"] for x in only_b)


def test_ticket_reply_is_audited(client, tenant):
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "rimborso"})
    tickets = client.get("/tickets", headers=tenant["op"]).json()
    tid = tickets[0]["ticket"]["id"]
    client.post(f"/tickets/{tid}/reply", headers=tenant["op"], params={"reply": "ci penso io"})
    audit = client.get("/admin/audit", headers=ADMIN).json()
    replies = [a for a in audit if a["action"] == "ticket.reply"]
    assert replies and replies[0]["actor_type"] == "operator"

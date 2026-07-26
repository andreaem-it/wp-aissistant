"""Visitor email capture on escalation + notification on operator reply."""
from app import main

ADMIN = {"Authorization": "Bearer test-admin"}


def _escalated_conversation(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "vorrei un rimborso"}).json()
    assert r["status"] == "escalated"
    return r["conversation_id"]


def test_contact_saves_email(client, tenant):
    conv_id = _escalated_conversation(client, tenant)
    r = client.post("/chat/contact", headers=tenant["key"],
                    json={"conversation_id": conv_id, "email": "visitor@x.it", "url": "https://site.it/pagina"})
    assert r.status_code == 200


def test_contact_rejects_bad_email(client, tenant):
    conv_id = _escalated_conversation(client, tenant)
    r = client.post("/chat/contact", headers=tenant["key"], json={"conversation_id": conv_id, "email": "nope"})
    assert r.status_code == 400


def test_contact_scoped_to_client(client, tenant):
    conv_id = _escalated_conversation(client, tenant)
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    denied = client.post("/chat/contact", headers={"Authorization": f"Bearer {other['api_key']}"},
                         json={"conversation_id": conv_id, "email": "v@x.it"})
    assert denied.status_code == 404


def test_operator_reply_notifies_visitor(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main.email_service, "send_visitor_reply",
                        lambda to, client_name, url: sent.append((to, client_name, url)) or True)

    conv_id = _escalated_conversation(client, tenant)
    client.post("/chat/contact", headers=tenant["key"],
                json={"conversation_id": conv_id, "email": "visitor@x.it", "url": "https://site.it/p"})
    tid = client.get("/tickets", headers=tenant["op"]).json()[0]["ticket"]["id"]

    client.post(f"/tickets/{tid}/reply", headers=tenant["op"], params={"reply": "ecco la risposta"})
    assert sent == [("visitor@x.it", "Acme", "https://site.it/p")]


def test_operator_reply_without_contact_sends_nothing(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main.email_service, "send_visitor_reply",
                        lambda *a, **k: sent.append(a) or True)
    conv_id = _escalated_conversation(client, tenant)  # no /chat/contact call
    tid = client.get("/tickets", headers=tenant["op"]).json()[0]["ticket"]["id"]
    client.post(f"/tickets/{tid}/reply", headers=tenant["op"], params={"reply": "ok"})
    assert sent == []  # no email captured => no notification

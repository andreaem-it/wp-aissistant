"""Visitor email capture on escalation + notification on operator reply."""
from app import main
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _escalated_conversation(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "vorrei un rimborso"}).json()
    assert r["status"] == "escalated"
    return r


def test_contact_saves_email(client, tenant):
    conv = _escalated_conversation(client, tenant)
    r = client.post("/chat/contact", headers=tenant["key"],
                    json={"conversation_id": conv["conversation_id"], "conversation_token": conv["conversation_token"],
                          "email": "visitor@x.it", "url": "https://site.it/pagina"})
    assert r.status_code == 200


def test_contact_rejects_bad_email(client, tenant):
    conv = _escalated_conversation(client, tenant)
    r = client.post("/chat/contact", headers=tenant["key"], json={
        "conversation_id": conv["conversation_id"],
        "conversation_token": conv["conversation_token"],
        "email": "nope",
    })
    assert r.status_code == 400


def test_contact_scoped_to_client(client, tenant):
    conv = _escalated_conversation(client, tenant)
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other", "allowed_origins": TENANT_ORIGIN}).json()
    denied = client.post("/chat/contact", headers={"Authorization": f"Bearer {other['api_key']}"},
                         json={"conversation_id": conv["conversation_id"], "email": "v@x.it"})
    assert denied.status_code == 404


def test_operator_reply_notifies_visitor(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main.email_service, "send_visitor_reply",
                        lambda to, client_name, url, **kw: sent.append((to, client_name, url, kw.get("client_id"))) or True)

    conv = _escalated_conversation(client, tenant)
    conv_id = conv["conversation_id"]
    client.post("/chat/contact", headers=tenant["key"],
                json={"conversation_id": conv_id, "conversation_token": conv["conversation_token"],
                      "email": "visitor@x.it", "url": "https://site.it/p"})
    tid = client.get("/tickets", headers=tenant["op"]).json()[0]["ticket"]["id"]

    client.post(f"/tickets/{tid}/reply", headers=tenant["op"], params={"reply": "ecco la risposta"})
    assert sent == [("visitor@x.it", "Acme", "https://site.it/p", tenant["cid"])]


def test_operator_reply_without_contact_sends_nothing(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main.email_service, "send_visitor_reply",
                        lambda *a, **k: sent.append(a) or True)
    conv_id = _escalated_conversation(client, tenant)["conversation_id"]  # no /chat/contact call
    tid = client.get("/tickets", headers=tenant["op"]).json()[0]["ticket"]["id"]
    client.post(f"/tickets/{tid}/reply", headers=tenant["op"], params={"reply": "ok"})
    assert sent == []  # no email captured => no notification


def test_conversation_reply_adds_message_and_closes_ticket(client, tenant):
    conv_id = _escalated_conversation(client, tenant)["conversation_id"]
    r = client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "ci penso io"})
    assert r.status_code == 200
    msgs = client.get(f"/conversations/{conv_id}/messages", headers=tenant["op"]).json()["messages"]
    assert any(m["role"] == "operator" and m["content"] == "ci penso io" for m in msgs)
    # the open ticket for this conversation is now answered => no longer in the open list
    assert client.get("/tickets", headers=tenant["op"]).json() == []


def test_conversation_reply_scoped_to_client(client, tenant):
    conv_id = _escalated_conversation(client, tenant)["conversation_id"]
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other", "allowed_origins": TENANT_ORIGIN}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": "o2@x.it", "password": "password1"})
    tok = client.post("/operator/login", json={"email": "o2@x.it", "password": "password1"}).json()["token"]
    denied = client.post(f"/conversations/{conv_id}/reply", headers={"Authorization": f"Bearer {tok}"}, json={"reply": "x"})
    assert denied.status_code == 404

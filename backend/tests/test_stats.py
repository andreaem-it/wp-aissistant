"""Fase 3b/3c read models: rich operator /stats, global /admin/stats, /admin/health and
/admin/problematic. LLM/embeddings mocked by conftest."""
from app import main

ADMIN = {"Authorization": "Bearer test-admin"}


def test_operator_stats_shape(client, tenant):
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v2", "message": "vorrei un rimborso"})
    s = client.get("/stats", headers=tenant["op"]).json()
    # rich structure
    assert s["conversations"]["total"] == 2
    assert s["conversations"]["escalated"] == 1
    assert s["ai"]["answered"] == 1
    assert s["ai"]["escalated"] == 1
    assert s["escalations_by_trigger"]["keyword"] == 1
    assert isinstance(s["volume_daily"], list)
    # backward-compatible flat keys
    assert s["total_conversations"] == 2
    assert s["escalated"] == 1


def test_operator_stats_scoped_to_own_client(client, tenant):
    # another tenant's traffic must not leak into these stats
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    client.post("/chat", headers={"Authorization": f"Bearer {other['api_key']}"},
                json={"visitor_id": "x", "message": "ciao"})
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    s = client.get("/stats", headers=tenant["op"]).json()
    assert s["conversations"]["total"] == 1


def test_admin_stats_global(client, tenant):
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    s = client.get("/admin/stats", headers=ADMIN).json()
    assert s["clients"]["total"] >= 1
    assert "by_plan" in s["clients"]
    assert isinstance(s["top_clients"], list)
    assert s["conversations"]["total"] >= 1


def test_admin_stats_requires_admin(client):
    assert client.get("/admin/stats").status_code == 401


def test_admin_health(client):
    h = client.get("/admin/health", headers=ADMIN).json()
    assert h["db"] == "ok"
    assert h["status"] in ("ok", "degraded")
    assert set(h["ingest_queue"]) == {"queued", "processing", "done", "error"}
    assert "chat" in h["models"]
    assert "configured" in h["email"]  # SMTP status surfaced


def test_admin_test_email_reports_not_configured(client):
    # no SMTP in tests => the endpoint says so instead of pretending it sent
    r = client.post("/admin/test-email", headers=ADMIN, json={"to": "x@y.it"}).json()
    assert r["configured"] is False
    assert r["sent"] is False


def test_admin_test_email_sends_when_configured(client, monkeypatch):
    from app import email as email_service
    monkeypatch.setattr(email_service, "enabled", lambda: True)
    monkeypatch.setattr(email_service, "send_test", lambda to: True)
    r = client.post("/admin/test-email", headers=ADMIN, json={"to": "x@y.it"}).json()
    assert r["configured"] is True
    assert r["sent"] is True


def test_client_origins_are_normalized(client):
    # a full URL with a path can never match a browser Origin header -> strip to scheme://host
    c = client.post("/admin/clients", headers=ADMIN,
                    json={"name": "N", "allowed_origins": "https://site.it/shop"}).json()
    assert c["allowed_origins"] == "https://site.it"
    r = client.post(f"/admin/clients/{c['id']}/origins", headers=ADMIN,
                    json={"allowed_origins": "https://a.com/x, https://b.com/"}).json()
    assert r["allowed_origins"] == "https://a.com,https://b.com"


def test_admin_problematic_lists_model_escalations(client, tenant, monkeypatch):
    # force the model to escalate so an 'escalated_model' turn is logged
    monkeypatch.setattr(main, "llm_chat", lambda system, history, message: {"escalate": "non lo so"})
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "domanda difficile"})
    items = client.get("/admin/problematic", headers=ADMIN).json()
    assert any(i["kind"] == "escalated_model" for i in items)


def test_admin_problematic_excludes_greetings_by_default(client, tenant):
    # a plain answered greeting has no retrieved context but must NOT be flagged by default
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    assert client.get("/admin/problematic", headers=ADMIN).json() == []
    # ...unless ungrounded answers are explicitly requested
    withu = client.get("/admin/problematic", headers=ADMIN, params={"include_ungrounded": "true"}).json()
    assert any(i["kind"] == "answered_no_context" for i in withu)


# ---- feedback 👍/👎 ----

def test_chat_returns_message_id(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"}).json()
    assert r["status"] == "open"
    assert isinstance(r["message_id"], int)


def test_feedback_records_and_shows_in_stats(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"}).json()
    ok = client.post("/chat/feedback", headers=tenant["key"],
                     json={"conversation_id": r["conversation_id"], "conversation_token": r["conversation_token"],
                           "message_id": r["message_id"], "value": "up"})
    assert ok.status_code == 200
    s = client.get("/stats", headers=tenant["op"]).json()
    assert s["feedback"]["positive"] == 1
    assert s["feedback"]["negative"] == 0


def test_feedback_rejects_bad_value(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"}).json()
    bad = client.post("/chat/feedback", headers=tenant["key"],
                      json={"conversation_id": r["conversation_id"], "conversation_token": r["conversation_token"],
                            "message_id": r["message_id"], "value": "meh"})
    assert bad.status_code == 400


def test_feedback_scoped_to_client(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"}).json()
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    denied = client.post("/chat/feedback", headers={"Authorization": f"Bearer {other['api_key']}"},
                         json={"conversation_id": r["conversation_id"], "message_id": r["message_id"], "value": "up"})
    assert denied.status_code == 404  # not this client's conversation

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

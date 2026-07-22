"""Integration tests over the HTTP API. Require TEST_DATABASE_URL (Postgres+pgvector);
skipped otherwise. The LLM is faked in the `client` fixture."""


# ---- admin / operator auth ----

def test_admin_requires_key(client):
    assert client.post("/admin/clients", json={"name": "X"}).status_code == 401
    ok = client.post("/admin/clients", headers={"Authorization": "Bearer test-admin"}, json={"name": "X"})
    assert ok.status_code == 200
    assert ok.json()["api_key"]


def test_operator_login_and_scope(client, tenant):
    # operator token works on a panel endpoint
    assert client.get("/stats", headers=tenant["op"]).status_code == 200
    # client api_key is rejected on an operator-only endpoint
    assert client.get("/stats", headers=tenant["key"]).status_code == 401


def test_login_wrong_password(client, tenant):
    r = client.post("/operator/login", json={"email": "op@acme.it", "password": "nope"})
    assert r.status_code == 401


# ---- chat + escalation ----

def test_chat_normal_reply(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open"
    assert body["reply"] == "ok"


def test_chat_keyword_escalation_creates_ticket(client, tenant):
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "vorrei un rimborso"})
    assert r.status_code == 200
    assert r.json()["status"] == "escalated"
    tickets = client.get("/tickets", headers=tenant["op"]).json()
    assert len(tickets) == 1


# ---- ticket reply ownership ----

def test_ticket_reply_requires_ownership(client, tenant):
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "rimborso"})
    ticket_id = client.get("/tickets", headers=tenant["op"]).json()[0]["ticket"]["id"]

    # a different tenant's operator must not be able to reply
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other"}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=admin,
                json={"email": "op2@x.it", "password": "pw"})
    other_token = client.post("/operator/login", json={"email": "op2@x.it", "password": "pw"}).json()["token"]

    denied = client.post(f"/tickets/{ticket_id}/reply", params={"reply": "hi"},
                         headers={"Authorization": f"Bearer {other_token}"})
    assert denied.status_code == 404

    allowed = client.post(f"/tickets/{ticket_id}/reply", params={"reply": "hi"}, headers=tenant["op"])
    assert allowed.status_code == 200


# ---- async ingest ----

def test_ingest_enqueues_and_worker_processes(client, tenant, drain):
    r = client.post("/ingest/site-page", headers=tenant["key"],
                    json={"url": "http://s/x", "text": "hello world"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "queued"

    # status endpoint reachable with the client key
    assert client.get(f"/ingest/jobs/{job_id}", headers=tenant["key"]).json()["status"] == "queued"

    drain()  # worker is disabled in tests; process the queue manually
    assert client.get(f"/ingest/jobs/{job_id}", headers=tenant["key"]).json()["status"] == "done"


def test_ingest_job_scoped_to_client(client, tenant):
    job_id = client.post("/ingest/site-page", headers=tenant["key"],
                         json={"url": "http://s/y", "text": "t"}).json()["job_id"]
    # another client cannot read this job
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other"}).json()
    r = client.get(f"/ingest/jobs/{job_id}", headers={"Authorization": f"Bearer {other['api_key']}"})
    assert r.status_code == 404


# ---- rate limiting ----

def test_chat_rate_limit_returns_429(client, tenant, monkeypatch):
    from app import main
    monkeypatch.setattr(main.chat_limiter, "limit", 2)
    for _ in range(2):
        client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"})
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"})
    assert r.status_code == 429

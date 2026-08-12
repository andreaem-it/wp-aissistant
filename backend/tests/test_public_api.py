"""Public API: scoped keys, /v1 surface and tenant isolation."""
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}
ALL_SCOPES = ["conversations:read", "conversations:write", "knowledge:write", "stats:read"]


def _key(client, tenant, scopes=None, name="Integrazione CRM"):
    created = client.post(
        "/api-keys", headers=tenant["op"], json={"name": name, "scopes": scopes or ALL_SCOPES}
    ).json()
    return created, {"Authorization": f"Bearer {created['token']}"}


def _other_tenant(client, name="Api Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def _chat(client, tenant, visitor="api", message="ciao"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": message}
    ).json()


# ---- key lifecycle ----


def test_key_is_returned_once_and_listed_without_the_secret(client, tenant):
    created, _ = _key(client, tenant)
    assert created["token"].startswith("wpa_")
    assert created["prefix"] in created["token"]

    listed = client.get("/api-keys", headers=tenant["op"]).json()
    assert len(listed) == 1
    assert "token" not in listed[0]
    assert listed[0]["prefix"] == created["prefix"]
    assert listed[0]["scopes"] == ALL_SCOPES
    assert listed[0]["created_by"] == "op@acme.it"


def test_key_requires_valid_scopes(client, tenant):
    assert client.post("/api-keys", headers=tenant["op"], json={"scopes": []}).status_code == 400
    assert client.post(
        "/api-keys", headers=tenant["op"], json={"scopes": ["conversations:destroy"]}
    ).status_code == 400
    assert client.get("/api-keys", headers=tenant["op"]).json() == []


def test_revoked_key_stops_working(client, tenant):
    created, headers = _key(client, tenant)
    assert client.get("/v1/conversations", headers=headers).status_code == 200

    assert client.delete(f"/api-keys/{created['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/v1/conversations", headers=headers).status_code == 401
    assert client.get("/api-keys", headers=tenant["op"]).json()[0]["revoked_at"] is not None


def test_missing_or_unknown_key_is_rejected(client, tenant):
    assert client.get("/v1/conversations").status_code == 401
    assert client.get("/v1/conversations", headers={"Authorization": "Bearer wpa_ffff_nope"}).status_code == 401
    # the widget api_key is not a public-API credential
    assert client.get("/v1/conversations", headers=tenant["key"]).status_code == 401


def test_scopes_are_enforced(client, tenant):
    _, read_only = _key(client, tenant, scopes=["conversations:read"], name="Sola lettura")
    chat = _chat(client, tenant)

    assert client.get("/v1/conversations", headers=read_only).status_code == 200
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/reply", headers=read_only, json={"reply": "ciao"}
    ).status_code == 403
    assert client.get("/v1/stats", headers=read_only).status_code == 403
    assert client.post(
        "/v1/knowledge/documents", headers=read_only, json={"title": "x", "text": "y"}
    ).status_code == 403


def test_keys_are_tenant_scoped(client, tenant):
    created, _ = _key(client, tenant)
    other = _other_tenant(client)

    assert client.get("/api-keys", headers=other["op"]).json() == []
    assert client.delete(f"/api-keys/{created['id']}", headers=other["op"]).status_code == 404


# ---- /v1 surface ----


def test_list_and_read_conversations(client, tenant):
    chat = _chat(client, tenant, message="vorrei un rimborso")
    _, headers = _key(client, tenant)

    listed = client.get("/v1/conversations", headers=headers).json()
    assert [c["id"] for c in listed["data"]] == [chat["conversation_id"]]
    assert listed["data"][0]["status"] == "escalated"
    assert listed["next_before_id"] == chat["conversation_id"]

    detail = client.get(f"/v1/conversations/{chat['conversation_id']}", headers=headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user"]  # l'escalation non salva risposta AI
    assert detail["messages"][0]["content"] == "vorrei un rimborso"
    assert "access_token_hash" not in detail
    assert "messages" not in listed["data"][0]


def test_detail_never_exposes_internal_notes(client, tenant):
    chat = _chat(client, tenant)
    client.post(
        f"/conversations/{chat['conversation_id']}/notes", headers=tenant["op"], json={"body": "nota interna"}
    )
    _, headers = _key(client, tenant)
    detail = client.get(f"/v1/conversations/{chat['conversation_id']}", headers=headers).json()
    assert "notes" not in detail
    assert all("nota interna" not in m["content"] for m in detail["messages"])


def test_v1_filters(client, tenant):
    open_chat = _chat(client, tenant, visitor="open")
    escalated = _chat(client, tenant, visitor="esc", message="vorrei un rimborso")
    _, headers = _key(client, tenant)
    tag = client.post(
        f"/conversations/{open_chat['conversation_id']}/tags", headers=tenant["op"], json={"name": "VIP"}
    ).json()

    def ids(params):
        return [c["id"] for c in client.get("/v1/conversations", headers=headers, params=params).json()["data"]]

    assert ids({"status": "escalated"}) == [escalated["conversation_id"]]
    assert ids({"tag_id": tag["id"]}) == [open_chat["conversation_id"]]
    assert client.get("/v1/conversations", headers=headers, params={"status": "boh"}).status_code == 400
    assert client.get("/v1/conversations", headers=headers, params={"tag_id": 9999}).status_code == 404


def test_reply_via_api_behaves_like_an_operator_reply(client, tenant):
    chat = _chat(client, tenant, message="vorrei un rimborso")
    _, headers = _key(client, tenant)

    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/reply", headers=headers, json={"reply": "Ci pensiamo noi"}
    ).status_code == 200

    detail = client.get(f"/v1/conversations/{chat['conversation_id']}", headers=headers).json()
    assert detail["status"] == "open"
    assert detail["messages"][-1]["role"] == "operator"
    assert client.get("/tickets", headers=tenant["op"], params={"status": "open"}).json() == []
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/reply", headers=headers, json={"reply": "   "}
    ).status_code == 400


def test_status_and_tags_via_api(client, tenant):
    chat = _chat(client, tenant)
    _, headers = _key(client, tenant)

    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/status", headers=headers, json={"status": "closed"}
    ).json()["status"] == "closed"
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/status", headers=headers, json={"status": "boh"}
    ).status_code == 400

    tag = client.post(
        f"/v1/conversations/{chat['conversation_id']}/tags", headers=headers, json={"name": "Da fatturare"}
    ).json()
    assert tag["name"] == "Da fatturare"
    detail = client.get(f"/v1/conversations/{chat['conversation_id']}", headers=headers).json()
    assert detail["tags"] == ["Da fatturare"]


def test_stats_and_ingest_via_api(client, tenant, drain):
    _chat(client, tenant)
    _, headers = _key(client, tenant)

    stats = client.get("/v1/stats", headers=headers).json()
    assert stats["conversations"]["total"] == 1

    job = client.post(
        "/v1/knowledge/documents", headers=headers, json={"title": "Politica resi", "text": "Resi entro 30 giorni."}
    ).json()
    assert job["status"] == "queued"
    drain()
    kb = client.get("/knowledge-base", headers=tenant["op"]).json()
    assert any(item["source_ref"] == "Politica resi" for item in kb["documents"])
    assert client.post(
        "/v1/knowledge/documents", headers=headers, json={"title": "", "text": "x"}
    ).status_code == 400


def test_v1_cannot_reach_another_tenant(client, tenant):
    chat = _chat(client, tenant)
    other = _other_tenant(client, "Cross Api")
    other_key = client.post(
        "/api-keys", headers=other["op"], json={"name": "loro", "scopes": ALL_SCOPES}
    ).json()
    headers = {"Authorization": f"Bearer {other_key['token']}"}

    assert client.get("/v1/conversations", headers=headers).json()["data"] == []
    assert client.get(f"/v1/conversations/{chat['conversation_id']}", headers=headers).status_code == 404
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/reply", headers=headers, json={"reply": "hack"}
    ).status_code == 404
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/status", headers=headers, json={"status": "closed"}
    ).status_code == 404
    assert client.post(
        f"/v1/conversations/{chat['conversation_id']}/tags", headers=headers, json={"name": "hack"}
    ).status_code == 404

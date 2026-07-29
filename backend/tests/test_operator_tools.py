"""Canned responses, info-field definitions, and per-conversation info values."""
ADMIN = {"Authorization": "Bearer test-admin"}


def test_canned_crud_and_scope(client, tenant):
    r = client.post("/canned-responses", headers=tenant["op"], json={"title": "Saluto", "body": "Ciao {nome}"}).json()
    assert r["id"]
    assert [c["title"] for c in client.get("/canned-responses", headers=tenant["op"]).json()] == ["Saluto"]
    assert client.delete(f"/canned-responses/{r['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/canned-responses", headers=tenant["op"]).json() == []


def test_info_field_key_is_slugified_and_unique(client, tenant):
    a = client.post("/info-fields", headers=tenant["op"], json={"label": "Nome Cliente"}).json()
    assert a["key"] == "nome_cliente"
    b = client.post("/info-fields", headers=tenant["op"], json={"label": "Nome Cliente"}).json()
    assert b["key"] == "nome_cliente_2"  # deduped within the client


def test_conversation_info_roundtrip(client, tenant):
    created = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()
    conv_id = created["conversation_id"]
    widget_headers = {**tenant["key"], "X-Conversation-Token": created["conversation_token"]}
    assert client.get(f"/conversations/{conv_id}/info", headers=tenant["op"]).json() == {"info": {}}
    client.put(f"/conversations/{conv_id}/info", headers=tenant["op"], json={"info": {"id_ordine": "001"}})
    assert client.get(f"/conversations/{conv_id}/info", headers=tenant["op"]).json() == {"info": {"id_ordine": "001"}}


def test_operator_tools_scoped_to_client(client, tenant):
    r = client.post("/canned-responses", headers=tenant["op"], json={"title": "x", "body": "y"}).json()
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other"}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": "o2@x.it", "password": "password1"})
    tok = client.post("/operator/login", json={"email": "o2@x.it", "password": "password1"}).json()["token"]
    other_op = {"Authorization": f"Bearer {tok}"}
    # the other client can't see or delete this client's canned response
    assert client.get("/canned-responses", headers=other_op).json() == []
    assert client.delete(f"/canned-responses/{r['id']}", headers=other_op).status_code == 404


def test_operator_name_and_typing_indicator(client, tenant):
    # operator sets their display name
    client.post("/me/name", headers=tenant["op"], json={"name": "Giulia"})
    assert client.get("/me", headers=tenant["op"]).json()["name"] == "Giulia"

    created = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()
    conv_id = created["conversation_id"]
    widget_headers = {**tenant["key"], "X-Conversation-Token": created["conversation_token"]}
    # before any typing ping, the widget poll shows no operator typing
    poll = client.get(f"/conversations/{conv_id}/messages", headers=widget_headers).json()
    assert poll["operator_typing"] is None
    # after the operator pings typing, the widget poll surfaces the name
    client.post(f"/conversations/{conv_id}/typing", headers=tenant["op"])
    poll = client.get(f"/conversations/{conv_id}/messages", headers=widget_headers).json()
    assert poll["operator_typing"] == "Giulia"


def test_teach_knowledge_enqueues_and_ingests(client, tenant, drain):
    r = client.post("/knowledge/teach", headers=tenant["op"],
                    json={"title": "Resi", "content": "I resi sono accettati entro 30 giorni."})
    assert r.status_code == 200 and r.json()["job_id"]
    drain()  # run the ingest worker synchronously
    kb = client.get("/knowledge-base", headers=tenant["op"]).json()
    assert any("kb-manuale" in d["source_ref"] for d in kb["documents"])


def test_teach_knowledge_requires_content(client, tenant):
    assert client.post("/knowledge/teach", headers=tenant["op"], json={"content": "  "}).status_code == 400


def test_conversation_info_not_leaked_to_widget(client, tenant):
    # the visitor-facing /messages endpoint must not expose operator info fields
    created = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()
    conv_id = created["conversation_id"]
    client.put(f"/conversations/{conv_id}/info", headers=tenant["op"], json={"info": {"segreto": "x"}})
    headers = {**tenant["key"], "X-Conversation-Token": created["conversation_token"]}
    msgs = client.get(f"/conversations/{conv_id}/messages", headers=headers).json()
    assert "info" not in msgs

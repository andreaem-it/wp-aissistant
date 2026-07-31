"""Manual tags, AI classification and their safe fallbacks."""
import json

from sqlmodel import Session, select

from app import db, llm, main, tagging


ADMIN = {"Authorization": "Bearer test-admin"}


def _other_tenant(client, name="Tag Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def _conversation(client, tenant, visitor="tags", message="ciao"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": message}
    ).json()["conversation_id"]


def _row(client, tenant, conv_id, params=None):
    rows = client.get("/conversations", headers=tenant["op"], params=params or {}).json()
    return next((r for r in rows if r["conversation"]["id"] == conv_id), None)


# ---- manual tags ----


def test_create_list_and_attach_tags(client, tenant):
    conv_id = _conversation(client, tenant)
    tag = client.post("/tags", headers=tenant["op"], json={"name": "VIP", "color": "#5b4fe8"}).json()
    assert client.get("/tags", headers=tenant["op"]).json() == [
        {"id": tag["id"], "name": "VIP", "color": "#5b4fe8", "source": "manual"}
    ]

    client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"tag_id": tag["id"]})
    row = _row(client, tenant, conv_id)
    assert [t["name"] for t in row["tags"]] == ["VIP"]

    # attaching twice stays a single association
    client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"tag_id": tag["id"]})
    assert len(_row(client, tenant, conv_id)["tags"]) == 1


def test_tag_by_name_creates_it_once(client, tenant):
    conv_id = _conversation(client, tenant)
    first = client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"name": "Resi"}).json()
    second_conv = _conversation(client, tenant, visitor="tags-2")
    second = client.post(
        f"/conversations/{second_conv}/tags", headers=tenant["op"], json={"name": "  resi "}
    ).json()
    assert first["id"] == second["id"]  # case- and space-insensitive
    assert len(client.get("/tags", headers=tenant["op"]).json()) == 1


def test_duplicate_tag_and_empty_name_are_rejected(client, tenant):
    client.post("/tags", headers=tenant["op"], json={"name": "VIP"})
    assert client.post("/tags", headers=tenant["op"], json={"name": "vip"}).status_code == 409
    assert client.post("/tags", headers=tenant["op"], json={"name": "   "}).status_code == 400
    conv_id = _conversation(client, tenant)
    assert client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={}).status_code == 400


def test_remove_tag_from_conversation_and_delete_tag(client, tenant):
    conv_id = _conversation(client, tenant)
    tag = client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"name": "Urgente"}).json()

    assert client.delete(f"/conversations/{conv_id}/tags/{tag['id']}", headers=tenant["op"]).status_code == 200
    assert _row(client, tenant, conv_id)["tags"] == []
    assert client.delete(f"/conversations/{conv_id}/tags/{tag['id']}", headers=tenant["op"]).status_code == 404

    client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"tag_id": tag["id"]})
    assert client.delete(f"/tags/{tag['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/tags", headers=tenant["op"]).json() == []
    assert _row(client, tenant, conv_id)["tags"] == []


def test_filter_conversations_by_tag(client, tenant):
    tagged = _conversation(client, tenant, visitor="tagged")
    _conversation(client, tenant, visitor="untagged")
    tag = client.post(f"/conversations/{tagged}/tags", headers=tenant["op"], json={"name": "Resi"}).json()

    rows = client.get("/conversations", headers=tenant["op"], params={"tag_id": tag["id"]}).json()
    assert [r["conversation"]["id"] for r in rows] == [tagged]
    assert client.get("/conversations", headers=tenant["op"], params={"tag_id": 999999}).status_code == 404


def test_tags_are_tenant_scoped(client, tenant):
    conv_id = _conversation(client, tenant)
    tag = client.post("/tags", headers=tenant["op"], json={"name": "VIP"}).json()
    other = _other_tenant(client)

    assert client.get("/tags", headers=other["op"]).json() == []
    assert client.delete(f"/tags/{tag['id']}", headers=other["op"]).status_code == 404
    assert client.post(
        f"/conversations/{conv_id}/tags", headers=other["op"], json={"tag_id": tag["id"]}
    ).status_code == 404

    other_conv = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {other['api_key']}"},
        json={"visitor_id": "x", "message": "ciao"},
    ).json()["conversation_id"]
    assert client.post(
        f"/conversations/{other_conv}/tags", headers=other["op"], json={"tag_id": tag["id"]}
    ).status_code == 404


def test_saved_view_can_filter_by_tag(client, tenant):
    conv_id = _conversation(client, tenant)
    tag = client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"name": "Resi"}).json()
    view = client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Resi", "filters": {"tag_id": tag["id"]}}
    ).json()
    assert view["filters"] == {"tag_id": tag["id"]}

    other = _other_tenant(client, "View Tag Other")
    assert client.post(
        "/saved-views", headers=other["op"], json={"name": "Furba", "filters": {"tag_id": tag["id"]}}
    ).status_code == 404


# ---- AI classification ----


def _fake_classify(payload):
    return lambda transcript: payload


def test_manual_classification_stores_fields_and_topic_tag(client, tenant, monkeypatch):
    monkeypatch.setattr(
        tagging, "classify", _fake_classify({"intent": "reso", "topic": "reso scarpe", "urgency": "alta"})
    )
    conv_id = _conversation(client, tenant, message="vorrei restituire le scarpe")

    result = client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"]).json()
    assert result["classification"]["intent"] == "reso"
    assert result["classification"]["urgency"] == "alta"

    row = _row(client, tenant, conv_id)
    assert row["classification"]["topic"] == "reso scarpe"
    assert [(t["name"], t["source"]) for t in row["tags"]] == [("reso scarpe", "ai")]


def test_classification_filters(client, tenant, monkeypatch):
    monkeypatch.setattr(
        tagging, "classify", _fake_classify({"intent": "reclamo", "topic": "ritardo", "urgency": "alta"})
    )
    conv_id = _conversation(client, tenant, message="il pacco non è arrivato")
    client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"])
    _conversation(client, tenant, visitor="plain")

    assert [r["conversation"]["id"] for r in client.get(
        "/conversations", headers=tenant["op"], params={"intent": "reclamo"}
    ).json()] == [conv_id]
    assert [r["conversation"]["id"] for r in client.get(
        "/conversations", headers=tenant["op"], params={"urgency": "alta"}
    ).json()] == [conv_id]
    assert client.get("/conversations", headers=tenant["op"], params={"intent": "boh"}).status_code == 400
    assert client.get("/conversations", headers=tenant["op"], params={"urgency": "boh"}).status_code == 400


def test_classification_fallback_when_provider_is_down(client, tenant, monkeypatch):
    def _down(transcript):
        raise llm.LLMUnavailableError("provider down")

    monkeypatch.setattr(tagging, "classify", _down)
    conv_id = _conversation(client, tenant)

    response = client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"])
    assert response.status_code == 503
    row = _row(client, tenant, conv_id)
    assert row["classification"] is None
    assert row["tags"] == []


def test_classification_fallback_when_answer_is_unusable(client, tenant, monkeypatch):
    monkeypatch.setattr(tagging, "classify", _fake_classify(None))
    conv_id = _conversation(client, tenant)
    assert client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"]).status_code == 503
    assert _row(client, tenant, conv_id)["classification"] is None


def test_unknown_categories_are_discarded(monkeypatch):
    assert llm._parse_classification('{"intent": "boh", "topic": "resi", "urgency": "altissima"}') == {
        "intent": "",
        "topic": "resi",
        "urgency": "",
    }
    assert llm._parse_classification("non è json") is None
    assert llm._parse_classification('{"intent": "boh", "topic": "", "urgency": "x"}') is None
    assert llm._parse_classification('Ecco: {"intent": "ordine", "topic": "stato ordine", "urgency": "media"}') == {
        "intent": "ordine",
        "topic": "stato ordine",
        "urgency": "media",
    }


def test_classification_never_changes_routing_or_status(client, tenant, monkeypatch):
    monkeypatch.setattr(
        tagging, "classify", _fake_classify({"intent": "reclamo", "topic": "urgente", "urgency": "alta"})
    )
    conv_id = _conversation(client, tenant)
    before = _row(client, tenant, conv_id)["conversation"]
    client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"])
    after = _row(client, tenant, conv_id)["conversation"]
    assert (after["priority"], after["status"], after["assigned_operator_id"]) == (
        before["priority"], before["status"], before["assigned_operator_id"]
    )


def test_escalation_enqueues_a_classification_job(client, tenant, monkeypatch, drain):
    monkeypatch.setattr(tagging, "AI_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(main.tagging, "AI_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(
        tagging, "classify", _fake_classify({"intent": "reclamo", "topic": "rimborso", "urgency": "alta"})
    )
    conv_id = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "esc", "message": "vorrei un rimborso"}
    ).json()["conversation_id"]

    with Session(db.engine) as session:
        jobs = session.exec(select(db.IngestJob).where(db.IngestJob.kind == "classify")).all()
        assert [json.loads(j.payload)["conversation_id"] for j in jobs] == [conv_id]

    drain()  # the background worker runs the classification
    row = _row(client, tenant, conv_id)
    assert row["classification"]["intent"] == "reclamo"
    assert [t["source"] for t in row["tags"]] == ["ai"]


def test_failing_classification_job_does_not_fail_the_queue(client, tenant, monkeypatch, drain):
    monkeypatch.setattr(tagging, "AI_CLASSIFY_ENABLED", True)
    monkeypatch.setattr(main.tagging, "AI_CLASSIFY_ENABLED", True)

    def _down(transcript):
        raise llm.LLMUnavailableError("provider down")

    monkeypatch.setattr(tagging, "classify", _down)
    conv_id = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "esc2", "message": "vorrei un rimborso"}
    ).json()["conversation_id"]

    drain()
    with Session(db.engine) as session:
        jobs = session.exec(select(db.IngestJob).where(db.IngestJob.kind == "classify")).all()
        assert [j.status for j in jobs] == ["done"]
    assert _row(client, tenant, conv_id)["classification"] is None


def test_tag_stats_report_usage(client, tenant, monkeypatch):
    conv_id = _conversation(client, tenant)
    client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"name": "Resi"})
    monkeypatch.setattr(
        tagging, "classify", _fake_classify({"intent": "reso", "topic": "reso scarpe", "urgency": "media"})
    )
    client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"])

    stats = client.get("/stats", headers=tenant["op"]).json()
    names = {row["name"]: row for row in stats["tags"]}
    assert names["Resi"]["source"] == "manual"
    assert names["reso scarpe"]["source"] == "ai"
    assert stats["classification"]["by_intent"] == {"reso": 1}
    assert stats["classification"]["by_urgency"] == {"media": 1}


def test_erasing_a_conversation_removes_its_tag_links(client, tenant):
    conv_id = _conversation(client, tenant)
    client.post(f"/conversations/{conv_id}/tags", headers=tenant["op"], json={"name": "Resi"})
    assert client.delete(f"/conversations/{conv_id}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.ConversationTag)).all() == []
        assert len(session.exec(select(db.Tag)).all()) == 1  # the tag itself survives

"""Internal notes, mentions, presence/collision detection and the conversation audit trail."""

ADMIN = {"Authorization": "Bearer test-admin"}


def _colleague(client, tenant, email="mario.rossi@acme.it", name="Mario Rossi"):
    client.post(
        f"/admin/clients/{tenant['cid']}/operators",
        headers=ADMIN,
        json={"email": email, "password": "password1", "name": name},
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    operator_id = next(
        m["id"] for m in client.get("/team/operators", headers=tenant["op"]).json() if m["email"] == email
    )
    return {"id": operator_id, "op": {"Authorization": f"Bearer {token}"}}


def _other_tenant(client, name="Notes Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def _conversation(client, tenant, visitor="notes"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "ciao"}
    ).json()


def test_notes_are_never_visible_to_the_visitor(client, tenant):
    chat = _conversation(client, tenant)
    conv_id = chat["conversation_id"]
    client.post(
        f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "Cliente già rimborsato a giugno"}
    )

    visitor = client.get(
        f"/conversations/{conv_id}/messages",
        headers={**tenant["key"], "X-Conversation-Token": chat["conversation_token"]},
    )
    assert visitor.status_code == 200
    payload = visitor.json()
    assert all("rimborsato" not in m["content"] for m in payload["messages"])
    assert "notes" not in payload


def test_note_requires_a_body_and_is_listed_with_its_author(client, tenant):
    conv_id = _conversation(client, tenant)["conversation_id"]
    assert client.post(
        f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "   "}
    ).status_code == 400

    created = client.post(
        f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "Verificare la taglia"}
    ).json()
    notes = client.get(f"/conversations/{conv_id}/notes", headers=tenant["op"]).json()
    assert [n["id"] for n in notes] == [created["id"]]
    assert notes[0]["author"] == "op@acme.it"
    assert notes[0]["body"] == "Verificare la taglia"


def test_mentions_from_text_and_explicit_ids(client, tenant):
    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]

    note = client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "@mario_rossi puoi verificare tu?"},
    ).json()
    assert [m["operator_id"] for m in note["mentions"]] == [colleague["id"]]

    mine = client.get("/mentions", headers=colleague["op"]).json()
    assert len(mine) == 1
    assert mine[0]["conversation_id"] == conv_id
    assert mine[0]["author"] == "op@acme.it"
    assert mine[0]["read_at"] is None


def test_reading_the_notes_marks_own_mentions_as_read(client, tenant):
    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]
    client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "serve una verifica", "mentions": [colleague["id"]]},
    )

    assert len(client.get("/mentions", headers=colleague["op"]).json()) == 1
    client.get(f"/conversations/{conv_id}/notes", headers=colleague["op"])
    assert client.get("/mentions", headers=colleague["op"]).json() == []
    # the author never gets a mention notification for their own note
    assert client.get("/mentions", headers=tenant["op"]).json() == []
    assert len(client.get("/mentions", headers=colleague["op"], params={"unread_only": False}).json()) == 1


def test_mark_mentions_read_endpoint(client, tenant):
    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]
    client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "prima", "mentions": [colleague["id"]]},
    )
    client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "seconda", "mentions": [colleague["id"]]},
    )
    unread = client.get("/mentions", headers=colleague["op"]).json()
    assert len(unread) == 2

    marked = client.post("/mentions/read", headers=colleague["op"], json={"mention_ids": [unread[0]["id"]]}).json()
    assert marked["updated"] == 1
    assert len(client.get("/mentions", headers=colleague["op"]).json()) == 1
    assert client.post("/mentions/read", headers=colleague["op"], json={"mention_ids": []}).json()["updated"] == 1
    assert client.get("/mentions", headers=colleague["op"]).json() == []


def test_unknown_mention_ids_are_ignored(client, tenant):
    other = _other_tenant(client, "Mention Other")
    other_operator = client.get(f"/admin/clients/{other['cid']}/operators", headers=ADMIN).json()[0]
    conv_id = _conversation(client, tenant)["conversation_id"]

    note = client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "nota", "mentions": [other_operator["id"], 99999]},
    ).json()
    assert note["mentions"] == []
    assert client.get("/mentions", headers=other["op"]).json() == []


def test_only_the_author_can_delete_a_note(client, tenant):
    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]
    note = client.post(f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "mia"}).json()

    assert client.delete(f"/conversations/{conv_id}/notes/{note['id']}", headers=colleague["op"]).status_code == 403
    assert client.delete(f"/conversations/{conv_id}/notes/{note['id']}", headers=tenant["op"]).status_code == 200
    assert client.get(f"/conversations/{conv_id}/notes", headers=tenant["op"]).json() == []


def test_notes_are_tenant_scoped(client, tenant):
    conv_id = _conversation(client, tenant)["conversation_id"]
    note = client.post(f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "interna"}).json()
    other = _other_tenant(client)

    assert client.get(f"/conversations/{conv_id}/notes", headers=other["op"]).status_code == 404
    assert client.post(
        f"/conversations/{conv_id}/notes", headers=other["op"], json={"body": "hack"}
    ).status_code == 404
    assert client.delete(
        f"/conversations/{conv_id}/notes/{note['id']}", headers=other["op"]
    ).status_code == 404
    assert client.get(f"/conversations/{conv_id}/activity", headers=other["op"]).status_code == 404
    assert client.post(f"/conversations/{conv_id}/presence", headers=other["op"], json={}).status_code == 404


def test_presence_detects_a_collision(client, tenant):
    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]

    alone = client.post(f"/conversations/{conv_id}/presence", headers=tenant["op"], json={}).json()
    assert alone == {"others": [], "conflict": False}

    client.post(f"/conversations/{conv_id}/presence", headers=colleague["op"], json={"composing": True})
    mine = client.post(f"/conversations/{conv_id}/presence", headers=tenant["op"], json={}).json()
    assert [o["operator_id"] for o in mine["others"]] == [colleague["id"]]
    assert mine["conflict"] is True

    # the colleague stops writing: still present, no longer a conflict
    client.post(f"/conversations/{conv_id}/presence", headers=colleague["op"], json={"composing": False})
    mine = client.post(f"/conversations/{conv_id}/presence", headers=tenant["op"], json={}).json()
    assert mine["conflict"] is False
    assert len(mine["others"]) == 1


def test_presence_expires(client, tenant, monkeypatch):
    from app.routers import inbox as main  # presence state moved with the inbox router

    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]
    client.post(f"/conversations/{conv_id}/presence", headers=colleague["op"], json={"composing": True})
    monkeypatch.setattr(main, "PRESENCE_TTL", 0.0)
    mine = client.post(f"/conversations/{conv_id}/presence", headers=tenant["op"], json={}).json()
    assert mine["others"] == []


def test_activity_records_operator_actions(client, tenant):
    conv_id = _conversation(client, tenant)["conversation_id"]
    client.patch(f"/conversations/{conv_id}/routing", headers=tenant["op"], json={"priority": "high"})
    client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "eccomi"})
    note = client.post(f"/conversations/{conv_id}/notes", headers=tenant["op"], json={"body": "nota"}).json()
    client.delete(f"/conversations/{conv_id}/notes/{note['id']}", headers=tenant["op"])
    client.post(f"/conversations/{conv_id}/status", headers=tenant["op"], json={"status": "closed"})

    actions = [row["action"] for row in client.get(f"/conversations/{conv_id}/activity", headers=tenant["op"]).json()]
    assert actions == [
        "conversation.closed",
        "note.delete",
        "note.create",
        "conversation.reply",
        "conversation.routing",
    ]


def test_erasing_a_conversation_removes_its_notes(client, tenant):
    from sqlmodel import Session, select

    from app import db

    colleague = _colleague(client, tenant)
    conv_id = _conversation(client, tenant)["conversation_id"]
    client.post(
        f"/conversations/{conv_id}/notes",
        headers=tenant["op"],
        json={"body": "da cancellare", "mentions": [colleague["id"]]},
    )

    assert client.delete(f"/conversations/{conv_id}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.InternalNote)).all() == []
        assert session.exec(select(db.NoteMention)).all() == []


def test_presence_store_does_not_grow_unbounded(client, tenant, monkeypatch):
    """Conversations nobody pings again must not keep an entry forever."""
    from app.routers import inbox as main  # presence state moved with the inbox router

    monkeypatch.setattr(main, "PRESENCE_MAX_CONVERSATIONS", 0)  # sweep a ogni battito
    first = _conversation(client, tenant, visitor="p1")["conversation_id"]
    second = _conversation(client, tenant, visitor="p2")["conversation_id"]
    client.post(f"/conversations/{first}/presence", headers=tenant["op"], json={})
    monkeypatch.setattr(main, "PRESENCE_TTL", 0.0)
    client.post(f"/conversations/{second}/presence", headers=tenant["op"], json={})

    assert first not in main._conversation_presence

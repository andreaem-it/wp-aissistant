"""CSAT: the visitor's rating of the whole conversation and its reports."""
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _chat(client, tenant, visitor="csat", message="ciao"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": message}
    ).json()


def _rate(client, tenant, chat, score, comment="", token=None):
    return client.post(
        "/chat/rating",
        headers=tenant["key"],
        json={
            "conversation_id": chat["conversation_id"],
            "score": score,
            "comment": comment,
            "conversation_token": token if token is not None else chat["conversation_token"],
        },
    )


def _other_tenant(client, name="Csat Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def test_visitor_rates_the_conversation(client, tenant):
    chat = _chat(client, tenant)
    assert _rate(client, tenant, chat, 5, "Perfetto, grazie").status_code == 200

    rows = client.get("/conversations", headers=tenant["op"]).json()
    row = next(r for r in rows if r["conversation"]["id"] == chat["conversation_id"])
    assert row["rating"]["score"] == 5
    assert row["rating"]["comment"] == "Perfetto, grazie"
    assert row["rating"]["resolved_by"] == "ai"


def test_rating_is_distinct_from_message_feedback(client, tenant):
    chat = _chat(client, tenant)
    client.post(
        "/chat/feedback",
        headers=tenant["key"],
        json={
            "conversation_id": chat["conversation_id"],
            "message_id": chat["message_id"],
            "value": "down",
            "conversation_token": chat["conversation_token"],
        },
    )
    _rate(client, tenant, chat, 5)

    stats = client.get("/stats", headers=tenant["op"]).json()
    assert stats["feedback"]["negative"] == 1  # giudizio sulla singola risposta AI
    assert stats["csat"]["responses"] == 1  # giudizio sulla conversazione
    assert stats["csat"]["average"] == 5.0


def test_rating_updates_instead_of_duplicating(client, tenant):
    chat = _chat(client, tenant)
    _rate(client, tenant, chat, 2, "deluso")
    _rate(client, tenant, chat, 4, "risolto poi")

    summary = client.get("/stats", headers=tenant["op"]).json()["csat"]
    assert summary["responses"] == 1
    assert summary["average"] == 4.0
    rows = client.get("/conversations", headers=tenant["op"]).json()
    assert rows[0]["rating"]["comment"] == "risolto poi"


def test_rating_requires_valid_score_and_conversation_token(client, tenant):
    chat = _chat(client, tenant)
    assert _rate(client, tenant, chat, 0).status_code == 400
    assert _rate(client, tenant, chat, 6).status_code == 400
    # un token sbagliato risponde 404 come le conversazioni inesistenti (niente enumerazione)
    assert _rate(client, tenant, chat, 5, token="sbagliato").status_code == 404
    assert client.get("/stats", headers=tenant["op"]).json()["csat"]["responses"] == 0


def test_rating_is_tenant_scoped(client, tenant):
    chat = _chat(client, tenant)
    other = _other_tenant(client)
    response = client.post(
        "/chat/rating",
        headers={"Authorization": f"Bearer {other['api_key']}"},
        json={
            "conversation_id": chat["conversation_id"],
            "score": 5,
            "conversation_token": chat["conversation_token"],
        },
    )
    assert response.status_code == 404
    assert client.get("/csat", headers=other["op"]).json()["summary"]["responses"] == 0


def test_messages_poll_tells_the_widget_whether_it_already_rated(client, tenant):
    chat = _chat(client, tenant)
    headers = {**tenant["key"], "X-Conversation-Token": chat["conversation_token"]}
    assert client.get(f"/conversations/{chat['conversation_id']}/messages", headers=headers).json()["rated"] is False
    _rate(client, tenant, chat, 4)
    assert client.get(f"/conversations/{chat['conversation_id']}/messages", headers=headers).json()["rated"] is True


def test_report_splits_ai_and_operator(client, tenant):
    ai_chat = _chat(client, tenant, visitor="only-ai")
    _rate(client, tenant, ai_chat, 5)

    human_chat = _chat(client, tenant, visitor="with-operator", message="vorrei un rimborso")
    client.post(
        f"/conversations/{human_chat['conversation_id']}/reply", headers=tenant["op"], json={"reply": "ci penso io"}
    )
    _rate(client, tenant, human_chat, 3, "lento")

    report = client.get("/csat", headers=tenant["op"]).json()
    assert report["summary"]["responses"] == 2
    assert report["summary"]["average"] == 4.0
    assert report["summary"]["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 0, "5": 1}
    by_resolution = {row["resolved_by"]: row for row in report["by_resolution"]}
    assert by_resolution["ai"]["average"] == 5.0
    assert by_resolution["operator"]["average"] == 3.0
    assert [c["comment"] for c in report["comments"]] == ["lento"]


def test_report_by_operator_and_department(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Resi"}).json()
    chat = _chat(client, tenant, visitor="assigned")
    operator_id = client.get("/team/operators", headers=tenant["op"]).json()[0]["id"]
    client.patch(
        f"/conversations/{chat['conversation_id']}/routing",
        headers=tenant["op"],
        json={"assigned_operator_id": operator_id, "department_id": department["id"]},
    )
    _rate(client, tenant, chat, 4)

    report = client.get("/csat", headers=tenant["op"]).json()
    assert report["by_operator"][0]["operator_id"] == operator_id
    assert report["by_operator"][0]["average"] == 4.0
    assert report["by_department"][0]["name"] == "Resi"


def test_report_period_filters_older_ratings(client, tenant):
    from datetime import datetime, timedelta

    from sqlmodel import Session, select

    from app import db

    chat = _chat(client, tenant)
    _rate(client, tenant, chat, 5)
    with Session(db.engine) as session:
        rating = session.exec(select(db.ConversationRating)).one()
        rating.created_at = datetime.utcnow() - timedelta(days=60)
        session.add(rating)
        session.commit()

    assert client.get("/csat", headers=tenant["op"], params={"days": 30}).json()["summary"]["responses"] == 0
    assert client.get("/csat", headers=tenant["op"], params={"days": 90}).json()["summary"]["responses"] == 1


def test_rating_is_exported_and_erased_with_the_conversation(client, tenant):
    from sqlmodel import Session, select

    from app import db

    chat = _chat(client, tenant, visitor="gdpr", message="vorrei un rimborso")
    client.post(
        "/chat/contact",
        headers=tenant["key"],
        json={
            "conversation_id": chat["conversation_id"],
            "email": "visitatore@x.it",
            "conversation_token": chat["conversation_token"],
        },
    )
    _rate(client, tenant, chat, 2, "non risolto")

    export = client.post("/gdpr/export", headers=tenant["op"], json={"email": "visitatore@x.it"}).json()
    assert export["conversations"][0]["rating"]["score"] == 2

    assert client.delete(f"/conversations/{chat['conversation_id']}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.ConversationRating)).all() == []

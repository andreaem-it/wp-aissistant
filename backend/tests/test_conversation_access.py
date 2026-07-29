"""Regression tests for visitor conversation isolation.

The widget api_key is public by design. It must identify the tenant without granting access
to every visitor transcript within that tenant.
"""


def _conversation(client, tenant, visitor="owner"):
    response = client.post(
        "/chat",
        headers=tenant["key"],
        json={"visitor_id": visitor, "message": "ciao"},
    )
    assert response.status_code == 200
    return response.json()


def test_plaintext_conversation_token_is_not_persisted(client, tenant):
    from sqlmodel import Session
    from app import db

    created = _conversation(client, tenant)
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, created["conversation_id"])
        assert conv.access_token_hash
        assert conv.access_token_hash != created["conversation_token"]


def test_public_tenant_key_cannot_read_transcript_without_conversation_token(client, tenant):
    created = _conversation(client, tenant)
    denied = client.get(
        f"/conversations/{created['conversation_id']}/messages",
        headers=tenant["key"],
    )
    assert denied.status_code == 404

    allowed = client.get(
        f"/conversations/{created['conversation_id']}/messages",
        headers={**tenant["key"], "X-Conversation-Token": created["conversation_token"]},
    )
    assert allowed.status_code == 200


def test_public_tenant_key_cannot_continue_another_conversation(client, tenant):
    created = _conversation(client, tenant)
    denied = client.post(
        "/chat",
        headers=tenant["key"],
        json={
            "visitor_id": "attacker",
            "message": "inject",
            "conversation_id": created["conversation_id"],
            "conversation_token": "wrong-token",
        },
    )
    assert denied.status_code == 404


def test_public_tenant_key_cannot_mutate_feedback_or_contact_without_token(client, tenant):
    created = _conversation(client, tenant)
    feedback = client.post(
        "/chat/feedback",
        headers=tenant["key"],
        json={
            "conversation_id": created["conversation_id"],
            "message_id": created["message_id"],
            "value": "down",
        },
    )
    contact = client.post(
        "/chat/contact",
        headers=tenant["key"],
        json={"conversation_id": created["conversation_id"], "email": "attacker@example.test"},
    )
    assert feedback.status_code == 404
    assert contact.status_code == 404


def test_operator_can_read_without_visitor_token(client, tenant):
    created = _conversation(client, tenant)
    response = client.get(
        f"/conversations/{created['conversation_id']}/messages",
        headers=tenant["op"],
    )
    assert response.status_code == 200

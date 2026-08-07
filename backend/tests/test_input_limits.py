"""Bound expensive public inputs and paginate growing operator collections."""
import io

from app import main
# the chat and its size cap moved with the widget router when main.py was split;
# the document upload stayed in main.py, so this file needs both
from app.routers import widget


def test_chat_rejects_empty_and_oversized_messages(client, tenant, monkeypatch):
    assert client.post(
        "/chat",
        headers=tenant["key"],
        json={"visitor_id": "v", "message": "   "},
    ).status_code == 400

    monkeypatch.setattr(widget, "MAX_CHAT_MESSAGE_CHARS", 8)
    assert client.post(
        "/chat",
        headers=tenant["key"],
        json={"visitor_id": "v", "message": "x" * 9},
    ).status_code == 413


def test_document_upload_is_bounded_before_extraction(client, tenant, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 4)
    response = client.post(
        "/ingest/document",
        headers=tenant["op"],
        files={"file": ("large.txt", io.BytesIO(b"12345"), "text/plain")},
    )
    assert response.status_code == 413


def test_conversation_cursor_pagination(client, tenant):
    ids = []
    for visitor in ("v1", "v2", "v3"):
        response = client.post(
            "/chat",
            headers=tenant["key"],
            json={"visitor_id": visitor, "message": "ciao"},
        ).json()
        ids.append(response["conversation_id"])

    first_page = client.get(
        "/conversations",
        headers=tenant["op"],
        params={"limit": 2},
    ).json()
    assert [item["conversation"]["id"] for item in first_page] == list(reversed(ids[-2:]))

    second_page = client.get(
        "/conversations",
        headers=tenant["op"],
        params={"limit": 2, "before_id": first_page[-1]["conversation"]["id"]},
    ).json()
    assert [item["conversation"]["id"] for item in second_page] == [ids[0]]


def test_message_page_size_is_capped(client, tenant):
    created = client.post(
        "/chat",
        headers=tenant["key"],
        json={"visitor_id": "v", "message": "ciao"},
    ).json()
    headers = {
        **tenant["key"],
        "X-Conversation-Token": created["conversation_token"],
    }
    response = client.get(
        f"/conversations/{created['conversation_id']}/messages",
        headers=headers,
        params={"limit": 1},
    ).json()
    assert len(response["messages"]) == 1

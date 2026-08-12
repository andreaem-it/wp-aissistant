"""Streaming chat over SSE (/chat/stream). The LLM stream is mocked by conftest's _fake_stream
(yields a few deltas then a meta frame); individual tests override it for escalation paths."""
import json

from sqlmodel import Session, select

from app import db
# the chat stream moved with the widget router when main.py was split
from app.routers import widget as main
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _events(resp):
    """Parse the SSE body into a list of decoded JSON frames."""
    out = []
    for frame in resp.text.strip().split("\n\n"):
        line = frame.strip()
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


def test_stream_answered_emits_tokens_and_done(client, tenant):
    r = client.post("/chat/stream", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    assert r.status_code == 200
    events = _events(r)
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "token" in types
    assert types[-1] == "done"

    # the streamed tokens reassemble into the saved assistant message
    streamed = "".join(e["text"] for e in events if e["type"] == "token")
    assert streamed == "Ciao, come posso aiutarti?"
    done = events[-1]
    with Session(db.engine) as s:
        msg = s.get(db.Message, done["message_id"])
        assert msg.role == "assistant"
        assert msg.content == "Ciao, come posso aiutarti?"


def test_stream_answered_logs_ai_response(client, tenant):
    r = client.post("/chat/stream", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = _events(r)[0]["conversation_id"]
    with Session(db.engine) as s:
        logs = s.exec(select(db.AiResponseLog).where(db.AiResponseLog.conversation_id == conv_id)).all()
        assert len(logs) == 1
        assert logs[0].outcome == "answered"


def test_stream_cart_request_never_claims_unverified_success(client, tenant, monkeypatch):
    monkeypatch.setattr(
        main,
        "retrieve_products",
        lambda session, client_id, query: [{
            "title": "Polo",
            "price": "20",
            "image_url": "",
            "product_url": "https://shop.example/product/polo/",
        }],
    )
    r = client.post(
        "/chat/stream",
        headers=tenant["key"],
        json={"visitor_id": "cart-v1", "message": "Aggiungi la Polo al carrello"},
    )
    events = _events(r)
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    assert "usa il pulsante" in reply
    assert "Hai aggiunto" not in reply
    assert "WooCommerce" not in reply
    assert events[-1]["products"][0]["title"] == "Polo"


def test_stream_keyword_escalation_no_tokens(client, tenant):
    r = client.post("/chat/stream", headers=tenant["key"], json={"visitor_id": "v1", "message": "vorrei un rimborso"})
    events = _events(r)
    types = [e["type"] for e in events]
    assert "token" not in types  # an escalation must never leak a partial reply
    assert types[-1] == "escalated"
    # a ticket was opened
    tickets = client.get("/tickets", headers=tenant["op"]).json()
    assert len(tickets) == 1


def test_stream_out_of_hours_offers_ticket_without_escalating(client, tenant):
    r = client.post(
        "/chat/stream",
        headers=tenant["key"],
        json={"visitor_id": "v1", "message": "vorrei un rimborso", "support_available": False},
    )
    events = _events(r)
    assert events[-1]["type"] == "ticket_offered"
    assert client.get("/tickets", headers=tenant["op"]).json() == []

    started = events[0]
    opened = client.post(
        "/chat/ticket",
        headers=tenant["key"],
        json={
            "conversation_id": started["conversation_id"],
            "conversation_token": started["conversation_token"],
            "reason": events[-1]["reason"],
        },
    )
    assert opened.status_code == 200
    assert len(client.get("/tickets", headers=tenant["op"]).json()) == 1


def test_stream_model_escalation_buffers_prefix(client, tenant, monkeypatch):
    def _escalating_stream(system, history, message):
        yield ("delta", "ESCALATE: ")
        yield ("delta", "non lo so")
        yield ("meta", {"model": "test", "latency_ms": 1, "tokens_prompt": 0, "tokens_completion": 0})
    monkeypatch.setattr(main, "llm_chat_stream", _escalating_stream)
    monkeypatch.setattr(main, "_retrieval_is_in_scope", lambda meta: True)

    r = client.post("/chat/stream", headers=tenant["key"], json={"visitor_id": "v1", "message": "domanda difficile"})
    events = _events(r)
    types = [e["type"] for e in events]
    assert "token" not in types  # prefix buffered => nothing leaked
    assert types[-1] == "escalated"
    conv_id = events[0]["conversation_id"]
    with Session(db.engine) as s:
        logs = s.exec(select(db.AiResponseLog).where(db.AiResponseLog.conversation_id == conv_id)).all()
        assert logs[0].outcome == "escalated_model"


def test_stream_rejects_foreign_conversation(client, tenant):
    r = client.post("/chat/stream", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    conv_id = _events(r)[0]["conversation_id"]
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other", "allowed_origins": TENANT_ORIGIN}).json()
    denied = client.post("/chat/stream", headers={"Authorization": f"Bearer {other['api_key']}"},
                         json={"visitor_id": "x", "message": "ciao", "conversation_id": conv_id})
    assert denied.status_code == 404

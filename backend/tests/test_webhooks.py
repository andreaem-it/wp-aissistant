"""Signed webhooks: subscription, signature, retry policy, delivery log and SSRF guard."""
import hashlib
import hmac
import json

from sqlmodel import Session, select

from app import db, webhooks


ADMIN = {"Authorization": "Bearer test-admin"}
URL = "https://hooks.example.test/wpai"


class FakeTransport:
    """Records the outbound calls and replays a scripted sequence of responses."""

    def __init__(self, *responses):
        self.responses = list(responses) or [200]
        self.calls = []

    def __call__(self, url, body, headers):
        self.calls.append({"url": url, "body": body, "headers": headers})
        result = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(result, Exception):
            raise result
        return result


def _transport(monkeypatch, *responses):
    transport = FakeTransport(*responses)
    monkeypatch.setattr(webhooks, "_post", transport)
    return transport


def _endpoint(client, tenant, events=None, url=URL):
    return client.post(
        "/webhooks", headers=tenant["op"], json={"url": url, "events": events or [], "description": "CRM"}
    ).json()


def _other_tenant(client, name="Hook Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def _dispatch():
    with Session(db.engine) as session:
        return webhooks.dispatch_pending(session)


def _deliveries(client, tenant, endpoint_id):
    return client.get(f"/webhooks/{endpoint_id}/deliveries", headers=tenant["op"]).json()


# ---- endpoint management ----


def test_secret_is_returned_once_and_events_are_listed(client, tenant):
    created = _endpoint(client, tenant, events=["conversation.escalated"])
    assert created["secret"].startswith("whsec_")

    listed = client.get("/webhooks", headers=tenant["op"]).json()
    assert listed["events"] == list(webhooks.EVENTS)
    assert len(listed["endpoints"]) == 1
    assert "secret" not in listed["endpoints"][0]
    assert listed["endpoints"][0]["events"] == ["conversation.escalated"]


def test_url_and_events_are_validated(client, tenant):
    assert client.post("/webhooks", headers=tenant["op"], json={"url": "ftp://x.test/h"}).status_code == 400
    assert client.post("/webhooks", headers=tenant["op"], json={"url": "non-un-url"}).status_code == 400
    assert client.post(
        "/webhooks", headers=tenant["op"], json={"url": URL, "events": ["conversation.exploded"]}
    ).status_code == 400
    assert client.get("/webhooks", headers=tenant["op"]).json()["endpoints"] == []


def test_private_urls_are_refused_when_not_explicitly_allowed(monkeypatch):
    """Guardia SSRF: la destinazione è scelta dal tenant, non deve poter puntare alla rete interna."""
    monkeypatch.setattr(webhooks, "ALLOW_PRIVATE", False)
    for blocked in ("http://localhost/hook", "https://127.0.0.1/hook", "https://10.0.0.5/hook", "http://example.com/h"):
        try:
            webhooks.validate_url(blocked)
            raise AssertionError(f"{blocked} avrebbe dovuto essere rifiutato")
        except webhooks.WebhookUrlError:
            pass
    assert webhooks.validate_url("https://hooks.example.com/wpai") == "https://hooks.example.com/wpai"


def test_update_and_delete_endpoint(client, tenant):
    created = _endpoint(client, tenant)
    updated = client.patch(
        f"/webhooks/{created['id']}", headers=tenant["op"], json={"active": False, "events": ["conversation.closed"]}
    ).json()
    assert updated["active"] is False
    assert updated["events"] == ["conversation.closed"]
    assert client.patch(
        f"/webhooks/{created['id']}", headers=tenant["op"], json={"url": "ftp://x"}
    ).status_code == 400

    assert client.delete(f"/webhooks/{created['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/webhooks", headers=tenant["op"]).json()["endpoints"] == []


def test_webhooks_are_tenant_scoped(client, tenant):
    created = _endpoint(client, tenant)
    other = _other_tenant(client)

    assert client.get("/webhooks", headers=other["op"]).json()["endpoints"] == []
    assert client.patch(f"/webhooks/{created['id']}", headers=other["op"], json={"active": False}).status_code == 404
    assert client.delete(f"/webhooks/{created['id']}", headers=other["op"]).status_code == 404
    assert client.get(f"/webhooks/{created['id']}/deliveries", headers=other["op"]).status_code == 404
    assert client.post(f"/webhooks/{created['id']}/test", headers=other["op"]).status_code == 404


# ---- delivery ----


def test_event_is_delivered_signed(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    created = _endpoint(client, tenant, events=["conversation.escalated"])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "hook", "message": "vorrei un rimborso"})

    assert _dispatch() == 1
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == URL
    assert call["headers"]["X-WPAI-Event"] == "conversation.escalated"

    body = json.loads(call["body"])
    assert body["schema_version"] == "1.0"
    assert body["event"] == "conversation.escalated"
    assert body["data"]["reason"]
    # il payload non deve portare fuori nulla di interno
    raw = call["body"].decode()
    assert "access_token_hash" not in raw and "secret" not in raw

    # la firma è verificabile dal ricevente con il segreto dell'endpoint
    signature = call["headers"]["X-WPAI-Signature"]
    timestamp = signature.split(",")[0].split("=")[1]
    expected = hmac.new(
        created["secret"].encode(), f"{timestamp}.".encode() + call["body"], hashlib.sha256
    ).hexdigest()
    assert signature.endswith(expected)

    log = _deliveries(client, tenant, created["id"])
    assert [(d["status"], d["response_status"]) for d in log] == [("success", 200)]


def test_only_subscribed_events_are_delivered(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    created = _endpoint(client, tenant, events=["conversation.closed"])
    chat = client.post("/chat", headers=tenant["key"], json={"visitor_id": "sub", "message": "ciao"}).json()

    _dispatch()
    assert transport.calls == []  # conversation.created non è sottoscritto

    client.post(
        f"/conversations/{chat['conversation_id']}/status", headers=tenant["op"], json={"status": "closed"}
    )
    _dispatch()
    assert [json.loads(c["body"])["event"] for c in transport.calls] == ["conversation.closed"]
    assert [d["event"] for d in _deliveries(client, tenant, created["id"])] == ["conversation.closed"]


def test_endpoint_without_events_receives_everything(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    _endpoint(client, tenant, events=[])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "all", "message": "vorrei un rimborso"})

    _dispatch()
    events = [json.loads(c["body"])["event"] for c in transport.calls]
    assert events == [
        "conversation.created", "conversation.message.received", "conversation.escalated",
    ]


def test_inactive_endpoint_receives_nothing(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    created = _endpoint(client, tenant)
    client.patch(f"/webhooks/{created['id']}", headers=tenant["op"], json={"active": False})
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "off", "message": "ciao"})

    assert _dispatch() == 0
    assert transport.calls == []


def test_failure_is_retried_with_backoff_then_marked_failed(client, tenant, monkeypatch):
    _transport(monkeypatch, 500)
    created = _endpoint(client, tenant, events=["conversation.created"])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "retry", "message": "ciao"})

    _dispatch()
    log = _deliveries(client, tenant, created["id"])
    assert log[0]["status"] == "pending"
    assert log[0]["attempts"] == 1
    assert log[0]["next_attempt_at"] is not None  # riprova pianificata, non persa

    # il tentativo successivo non parte prima della sua scadenza
    assert _dispatch() == 0

    with Session(db.engine) as session:
        delivery = session.exec(select(db.WebhookDelivery)).one()
        delivery.attempts = delivery.max_attempts - 1
        delivery.next_attempt_at = delivery.created_at
        session.add(delivery)
        session.commit()

    _dispatch()
    log = _deliveries(client, tenant, created["id"])
    assert log[0]["status"] == "failed"
    assert log[0]["error"]


def test_transport_error_is_recorded_and_retried(client, tenant, monkeypatch):
    _transport(monkeypatch, OSError("connection refused"))
    created = _endpoint(client, tenant, events=["conversation.created"])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "boom", "message": "ciao"})

    _dispatch()
    log = _deliveries(client, tenant, created["id"])
    assert log[0]["status"] == "pending"
    assert "connection refused" in log[0]["error"]


def test_recovering_endpoint_succeeds_on_retry(client, tenant, monkeypatch):
    _transport(monkeypatch, 503, 200)
    created = _endpoint(client, tenant, events=["conversation.created"])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "recover", "message": "ciao"})

    _dispatch()
    with Session(db.engine) as session:
        delivery = session.exec(select(db.WebhookDelivery)).one()
        delivery.next_attempt_at = delivery.created_at
        session.add(delivery)
        session.commit()
    _dispatch()

    log = _deliveries(client, tenant, created["id"])
    assert log[0]["status"] == "success"
    assert log[0]["attempts"] == 2
    assert log[0]["delivered_at"] is not None


def test_every_web_visitor_message_emits_privacy_safe_metadata(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    _endpoint(client, tenant, events=["conversation.message.received"])
    first = client.post(
        "/chat", headers=tenant["key"],
        json={"visitor_id": "message-hook", "message": "Avete questo prodotto?"},
    ).json()
    client.post(
        "/chat", headers=tenant["key"],
        json={
            "visitor_id": "message-hook", "conversation_id": first["conversation_id"],
            "conversation_token": first["conversation_token"], "message": "Quanto costa?",
        },
    )
    assert _dispatch() == 2
    payloads = [json.loads(call["body"]) for call in transport.calls]
    assert all(payload["event"] == "conversation.message.received" for payload in payloads)
    assert all(payload["data"]["channel"] == "web" for payload in payloads)
    assert all(set(payload["data"]) == {"conversation_id", "message_id", "channel", "role"} for payload in payloads)
    assert all("conversation_token" not in json.dumps(payload) for payload in payloads)


def test_test_endpoint_reports_the_real_outcome(client, tenant, monkeypatch):
    _transport(monkeypatch, 500)
    created = _endpoint(client, tenant)
    failed = client.post(f"/webhooks/{created['id']}/test", headers=tenant["op"]).json()
    assert failed["ok"] is False
    assert failed["response_status"] == 500

    _transport(monkeypatch, 200)
    ok = client.post(f"/webhooks/{created['id']}/test", headers=tenant["op"]).json()
    assert ok["ok"] is True
    log = _deliveries(client, tenant, created["id"])
    assert [d["status"] for d in log] == ["success", "failed"]  # più recente per prima
    assert log[0]["payload"]["schema_version"] == "1.0"
    assert log[0]["payload"]["test"] is True

    failed_only = client.get(
        f"/webhooks/{created['id']}/deliveries", headers=tenant["op"],
        params={"status": "failed", "event": "conversation.created"},
    ).json()
    assert [row["status"] for row in failed_only] == ["failed"]
    assert client.get(
        f"/webhooks/{created['id']}/deliveries", headers=tenant["op"], params={"status": "broken"},
    ).status_code == 400
    newest_id = log[0]["id"]
    older = client.get(
        f"/webhooks/{created['id']}/deliveries", headers=tenant["op"],
        params={"before_id": newest_id, "limit": 1},
    ).json()
    assert [row["id"] for row in older] == [log[1]["id"]]
    assert client.get(
        f"/webhooks/{created['id']}/deliveries", headers=tenant["op"], params={"before_id": 0},
    ).status_code == 400
    stats = client.get(f"/webhooks/{created['id']}/stats", headers=tenant["op"]).json()
    assert stats == {
        "days": 30, "total": 2, "success": 1, "pending": 0, "failed": 1,
        "success_rate": 50.0, "average_attempts": 1.0,
    }
    other = _other_tenant(client, "Stats Other")
    assert client.get(f"/webhooks/{created['id']}/stats", headers=other["op"]).status_code == 404


def test_failed_delivery_can_be_replayed_without_overwriting_history(client, tenant, monkeypatch):
    _transport(monkeypatch, 500)
    created = _endpoint(client, tenant)
    failed = client.post(f"/webhooks/{created['id']}/test", headers=tenant["op"]).json()
    assert failed["ok"] is False

    transport = _transport(monkeypatch, 204)
    replay = client.post(
        f"/webhooks/{created['id']}/deliveries/{failed['delivery_id']}/replay",
        headers=tenant["op"],
    )
    assert replay.status_code == 200
    assert replay.json()["ok"] is True
    assert replay.json()["delivery_id"] != failed["delivery_id"]
    assert transport.calls[0]["headers"]["X-WPAI-Delivery"] == str(replay.json()["delivery_id"])
    assert [row["status"] for row in _deliveries(client, tenant, created["id"])] == ["success", "failed"]


def test_delivery_replay_is_tenant_scoped_and_requires_failed_state(client, tenant, monkeypatch):
    _transport(monkeypatch, 200)
    created = _endpoint(client, tenant)
    delivered = client.post(f"/webhooks/{created['id']}/test", headers=tenant["op"]).json()
    other = _other_tenant(client, "Replay Other")
    path = f"/webhooks/{created['id']}/deliveries/{delivered['delivery_id']}/replay"
    assert client.post(path, headers=other["op"]).status_code == 404
    assert client.post(path, headers=tenant["op"]).status_code == 409


def test_deliveries_never_cross_tenants(client, tenant, monkeypatch):
    transport = _transport(monkeypatch, 200)
    mine = _endpoint(client, tenant, events=["conversation.created"])
    other = _other_tenant(client, "Cross Hook")
    theirs = client.post(
        "/webhooks", headers=other["op"], json={"url": "https://altro.example.test/h", "events": []}
    ).json()

    client.post("/chat", headers=tenant["key"], json={"visitor_id": "mine", "message": "ciao"})
    _dispatch()

    assert [c["url"] for c in transport.calls] == [URL]
    assert len(_deliveries(client, tenant, mine["id"])) == 1
    assert client.get(f"/webhooks/{theirs['id']}/deliveries", headers=other["op"]).json() == []


def test_deleting_an_endpoint_removes_its_deliveries(client, tenant, monkeypatch):
    _transport(monkeypatch, 200)
    created = _endpoint(client, tenant, events=["conversation.created"])
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "del", "message": "ciao"})
    _dispatch()

    assert client.delete(f"/webhooks/{created['id']}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.WebhookDelivery)).all() == []


def test_emit_ignores_unknown_events(client, tenant, monkeypatch):
    _transport(monkeypatch, 200)
    _endpoint(client, tenant, events=[])
    with Session(db.engine) as session:
        assert webhooks.emit(session, tenant["cid"], "conversation.exploded", {}) == 0
        assert session.exec(select(db.WebhookDelivery)).all() == []

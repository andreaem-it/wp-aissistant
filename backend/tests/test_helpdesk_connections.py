import io
import json

from sqlmodel import Session, select

from app import db, helpdesk
from test_leads import _other_tenant


def _ticket(client, tenant):
    chat = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "helpdesk-user", "message": "Mi serve aiuto"},
    ).json()
    client.post("/chat/contact", headers=tenant["key"], json={
        "conversation_id": chat["conversation_id"],
        "conversation_token": chat["conversation_token"],
        "email": "cliente@example.it",
    })
    with Session(db.engine) as session:
        ticket = db.Ticket(conversation_id=chat["conversation_id"], reason="Problema ordine")
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
        return ticket.id


def test_helpdesk_connections_are_tenant_scoped_and_operator_only(client, tenant):
    created = client.put(
        "/helpdesk/connections/zendesk", headers=tenant["op"],
        json={"external_account_id": "acme.zendesk.com"},
    )
    assert created.status_code == 200
    assert client.get("/helpdesk/connections", headers=tenant["op"]).json()["providers"] == ["zendesk", "freshdesk"]
    other = _other_tenant(client, "Helpdesk Other")
    assert client.get("/helpdesk/connections", headers=other["op"]).json()["connections"] == []
    assert client.delete("/helpdesk/connections/zendesk", headers=other["op"]).status_code == 404
    assert client.get("/helpdesk/connections", headers=tenant["key"]).status_code == 401


def test_helpdesk_configuration_rejects_unknown_provider_and_unsafe_account(client, tenant):
    assert client.put(
        "/helpdesk/connections/intercom", headers=tenant["op"], json={"external_account_id": "acme"},
    ).status_code == 400
    assert client.put(
        "/helpdesk/connections/zendesk", headers=tenant["op"], json={"external_account_id": "<script>"},
    ).status_code == 400


def test_ticket_export_is_idempotent_contains_transcript_and_is_listed(client, tenant, monkeypatch):
    ticket_id = _ticket(client, tenant)
    client.put(
        "/helpdesk/connections/freshdesk", headers=tenant["op"],
        json={"external_account_id": "acme.freshdesk.com"},
    )
    calls = []
    monkeypatch.setattr(helpdesk, "export_ticket", lambda **kwargs: calls.append(kwargs) or (
        True, "external-42", "https://acme.freshdesk.com/tickets/42", "",
    ))
    first = client.post(
        f"/tickets/{ticket_id}/helpdesk-export", headers=tenant["op"], json={"provider": "freshdesk"},
    )
    second = client.post(
        f"/tickets/{ticket_id}/helpdesk-export", headers=tenant["op"], json={"provider": "freshdesk"},
    )
    assert first.json()["status"] == second.json()["status"] == "delivered"
    assert calls[0]["ticket"]["contact"]["email"] == "cliente@example.it"
    assert calls[0]["ticket"]["messages"][0]["content"] == "Mi serve aiuto"
    with Session(db.engine) as session:
        assert len(session.exec(select(db.HelpdeskExport).where(db.HelpdeskExport.ticket_id == ticket_id)).all()) == 1
    listed = client.get("/tickets", headers=tenant["op"]).json()[0]
    assert listed["helpdesk_exports"]["freshdesk"]["external_id"] == "external-42"


def test_ticket_export_cannot_cross_tenants_and_records_safe_failure(client, tenant, monkeypatch):
    ticket_id = _ticket(client, tenant)
    client.put(
        "/helpdesk/connections/zendesk", headers=tenant["op"], json={"external_account_id": "acme.zendesk.com"},
    )
    other = _other_tenant(client, "Helpdesk Isolated")
    assert client.post(
        f"/tickets/{ticket_id}/helpdesk-export", headers=other["op"], json={"provider": "zendesk"},
    ).status_code == 404
    monkeypatch.setattr(helpdesk, "export_ticket", lambda **kwargs: (
        False, "", "", "Helpdesk temporaneamente non raggiungibile",
    ))
    result = client.post(
        f"/tickets/{ticket_id}/helpdesk-export", headers=tenant["op"], json={"provider": "zendesk"},
    ).json()
    assert result["status"] == "failed"
    assert "raggiungibile" in result["error"]


def test_helpdesk_adapter_payload_never_contains_adapter_secret(monkeypatch):
    monkeypatch.setattr(helpdesk, "HELPDESK_ADAPTER_URL", "https://adapter.example/export")
    monkeypatch.setattr(helpdesk, "HELPDESK_ADAPTER_TOKEN", "shared-secret")
    captured = {}

    class Response(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout):
        captured.update(payload=json.loads(request.data), authorization=request.headers["Authorization"])
        return Response(b'{"ok":true,"external_id":"zd-1","external_url":"https://example/tickets/1"}')

    monkeypatch.setattr(helpdesk.urllib.request, "urlopen", fake_urlopen)
    result = helpdesk.export_ticket(
        client_id=7, provider="zendesk", external_account_id="acme", ticket={"id": 9},
    )
    assert result[:2] == (True, "zd-1")
    assert captured["payload"]["client_id"] == 7
    assert "shared-secret" not in json.dumps(captured["payload"])

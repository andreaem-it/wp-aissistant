import io
import json

from sqlmodel import Session, select

from app import crm, db
from test_leads import _form, _other_tenant, _submit


def _lead(client, tenant):
    form = _form(client, tenant).json()
    response = _submit(client, tenant, form["id"], {"nome": "Anna", "email": "anna@example.it"})
    assert response.status_code == 200
    return response.json()["id"]


def test_crm_connection_configuration_is_tenant_scoped(client, tenant, monkeypatch):
    monkeypatch.setattr(crm, "disconnect", lambda **kwargs: True)
    created = client.put(
        "/crm/connections/brevo", headers=tenant["op"],
        json={"external_account_id": "portal-123", "enabled": True},
    )
    assert created.status_code == 200
    assert created.json()["external_account_id"] == "portal-123"
    listed = client.get("/crm/connections", headers=tenant["op"]).json()
    assert listed["providers"] == ["brevo", "zoho", "pipedrive"]
    assert [row["provider"] for row in listed["connections"]] == ["brevo"]
    other = _other_tenant(client, "CRM Other")
    assert client.get("/crm/connections", headers=other["op"]).json()["connections"] == []
    assert client.delete("/crm/connections/brevo", headers=other["op"]).status_code == 404


def test_crm_connection_rejects_unknown_provider_invalid_account_and_widget_key(client, tenant):
    assert client.put(
        "/crm/connections/salesforce", headers=tenant["op"], json={"external_account_id": "123"},
    ).status_code == 400
    assert client.put(
        "/crm/connections/brevo", headers=tenant["op"], json={"external_account_id": "bad account<script>"},
    ).status_code == 400
    assert client.get("/crm/connections", headers=tenant["key"]).status_code == 401


def test_brevo_guided_connection_verifies_secret_without_storing_it(client, tenant, monkeypatch):
    captured = {}
    monkeypatch.setattr(crm, "configure_brevo", lambda **kwargs: captured.update(kwargs) or (True, "owner@example.it", ""))
    response = client.post(
        "/crm/connect/brevo", headers=tenant["op"], json={"api_key": "xkeysib-valid-secret-value"},
    )
    assert response.status_code == 200
    assert response.json()["external_account_id"] == "owner@example.it"
    assert captured == {"client_id": tenant["cid"], "api_key": "xkeysib-valid-secret-value"}
    with Session(db.engine) as session:
        row = session.exec(select(db.CrmConnection).where(db.CrmConnection.client_id == tenant["cid"])).one()
        assert row.external_account_id == "owner@example.it"
        assert "xkeysib" not in str(row)
    assert client.post(
        "/crm/connect/brevo", headers=tenant["key"], json={"api_key": "xkeysib-valid-secret-value"},
    ).status_code == 401


def test_lead_sync_is_explicit_idempotent_and_exposes_status(client, tenant, monkeypatch):
    lead_id = _lead(client, tenant)
    client.put(
        "/crm/connections/pipedrive", headers=tenant["op"],
        json={"external_account_id": "org/456"},
    )
    calls = []
    monkeypatch.setattr(crm, "sync_lead", lambda **kwargs: calls.append(kwargs) or (True, "person-9", ""))
    first = client.post(
        f"/leads/{lead_id}/crm-sync", headers=tenant["op"], json={"provider": "pipedrive"},
    )
    second = client.post(
        f"/leads/{lead_id}/crm-sync", headers=tenant["op"], json={"provider": "pipedrive"},
    )
    assert first.json()["status"] == second.json()["status"] == "delivered"
    assert calls[0]["external_account_id"] == "org/456"
    assert calls[0]["lead"]["data"]["email"] == "anna@example.it"
    with Session(db.engine) as session:
        assert len(session.exec(select(db.CrmSync).where(db.CrmSync.lead_id == lead_id)).all()) == 1
    listed = client.get("/leads", headers=tenant["op"]).json()[0]
    assert listed["crm_syncs"]["pipedrive"] == {
        "status": "delivered", "external_id": "person-9", "error": "",
    }


def test_lead_sync_cannot_cross_tenants_and_records_safe_failure(client, tenant, monkeypatch):
    lead_id = _lead(client, tenant)
    client.put(
        "/crm/connections/zoho", headers=tenant["op"], json={"external_account_id": "org:1"},
    )
    other = _other_tenant(client, "CRM Isolated")
    assert client.post(
        f"/leads/{lead_id}/crm-sync", headers=other["op"], json={"provider": "zoho"},
    ).status_code == 404
    monkeypatch.setattr(crm, "sync_lead", lambda **kwargs: (False, "", "CRM temporaneamente non raggiungibile"))
    response = client.post(
        f"/leads/{lead_id}/crm-sync", headers=tenant["op"], json={"provider": "zoho"},
    )
    assert response.json()["status"] == "failed"
    assert "raggiungibile" in response.json()["error"]


def test_crm_adapter_payload_and_missing_configuration(monkeypatch):
    monkeypatch.setattr(crm, "CRM_ADAPTER_URL", "https://adapter.example/crm")
    monkeypatch.setattr(crm, "CRM_ADAPTER_TOKEN", "shared-secret")
    captured = {}

    class Response(io.BytesIO):
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False

    def fake_urlopen(request, timeout):
        captured.update(payload=json.loads(request.data), authorization=request.headers["Authorization"], timeout=timeout)
        return Response(b'{"ok":true,"external_id":"contact-42"}')

    monkeypatch.setattr(crm.urllib.request, "urlopen", fake_urlopen)
    result = crm.sync_lead(
        client_id=7, provider="brevo", external_account_id="account-1",
        lead={"id": 9, "data": {"email": "a@example.it"}},
    )
    assert result == (True, "contact-42", "")
    assert captured["payload"]["client_id"] == 7
    assert "shared-secret" not in json.dumps(captured["payload"])
    monkeypatch.setattr(crm, "CRM_ADAPTER_URL", "")
    assert crm.sync_lead(client_id=7, provider="brevo", external_account_id="p", lead={})[0] is False

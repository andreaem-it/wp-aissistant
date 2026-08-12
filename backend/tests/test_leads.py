"""Lead capture: dynamic forms, consent, scoring, isolation and CSV export."""
import json

from sqlmodel import Session, select

from app import db, webhooks
from conftest import TENANT_ORIGIN


ADMIN = {"Authorization": "Bearer test-admin"}

FIELDS = [
    {"label": "Nome", "type": "text", "required": True, "points": 10},
    {"label": "Email", "type": "email", "required": True, "points": 40},
    {"label": "Telefono", "type": "tel", "points": 30},
    {"label": "Budget", "type": "select", "options": ["<1k", "1-5k", ">5k"], "points": 20},
]


def _form(client, tenant, **overrides):
    payload = {
        "name": "Qualificazione",
        "fields": FIELDS,
        "trigger": "escalation",
        "intro": "Lasciaci due informazioni",
        "consent_text": "Acconsento al trattamento dei dati.",
    }
    payload.update(overrides)
    return client.post("/lead-forms", headers=tenant["op"], json=payload)


def _submit(client, tenant, form_id, data, consent=True, conversation=None):
    body = {"form_id": form_id, "data": data, "consent": consent}
    if conversation:
        body["conversation_id"] = conversation["conversation_id"]
        body["conversation_token"] = conversation["conversation_token"]
    return client.post("/widget/leads", headers=tenant["key"], json=body)


def _other_tenant(client, name="Lead Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {
        "cid": other["id"],
        "key": {"Authorization": f"Bearer {other['api_key']}"},
        "op": {"Authorization": f"Bearer {token}"},
    }


# ---- form configuration ----


def test_create_form_and_slugged_keys(client, tenant):
    created = _form(client, tenant).json()
    assert [f["key"] for f in created["fields"]] == ["nome", "email", "telefono", "budget"]
    assert created["fields"][1]["points"] == 40

    listed = client.get("/lead-forms", headers=tenant["op"]).json()
    assert listed["field_types"] == ["text", "email", "tel", "select"]
    assert [f["id"] for f in listed["forms"]] == [created["id"]]


def test_form_validation(client, tenant):
    assert _form(client, tenant, fields=[]).status_code == 400
    assert _form(client, tenant, fields=[{"label": ""}]).status_code == 400
    assert _form(client, tenant, fields=[{"label": "X", "type": "captcha"}]).status_code == 400
    assert _form(client, tenant, fields=[{"label": "Scelta", "type": "select"}]).status_code == 400
    assert _form(client, tenant, fields=[{"label": "A"}, {"label": "A"}]).status_code == 400
    assert _form(client, tenant, trigger="quando_capita").status_code == 400
    assert client.get("/lead-forms", headers=tenant["op"]).json()["forms"] == []


def test_widget_form_hides_the_scoring_weights(client, tenant):
    _form(client, tenant)
    payload = client.get("/widget/lead-form", headers=tenant["key"]).json()["form"]
    assert payload["intro"] == "Lasciaci due informazioni"
    assert all("points" not in field for field in payload["fields"])
    assert "name" not in payload  # il nome interno del form resta interno


def test_widget_form_matches_the_trigger_and_active_flag(client, tenant):
    _form(client, tenant, trigger="chat_start", active=False)
    assert client.get("/widget/lead-form", headers=tenant["key"], params={"trigger": "chat_start"}).json()["form"] is None
    assert client.get("/widget/lead-form", headers=tenant["key"]).json()["form"] is None

    created = _form(client, tenant, name="Attivo", trigger="chat_start").json()
    assert client.get(
        "/widget/lead-form", headers=tenant["key"], params={"trigger": "chat_start"}
    ).json()["form"]["id"] == created["id"]
    assert client.get("/widget/lead-form", headers=tenant["key"]).json()["form"] is None
    assert client.get(
        "/widget/lead-form", headers=tenant["key"], params={"trigger": "quando_capita"}
    ).status_code == 400


# ---- submission ----


def test_score_is_the_sum_of_the_filled_fields(client, tenant):
    form = _form(client, tenant).json()

    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "anna@x.it"})
    _submit(client, tenant, form["id"], {
        "nome": "Bruno", "email": "bruno@x.it", "telefono": "333", "budget": ">5k",
    })

    leads = client.get("/leads", headers=tenant["op"]).json()
    by_name = {lead["data"]["nome"]: lead for lead in leads}
    assert by_name["Anna"]["score"] == 50  # 10 + 40
    assert by_name["Bruno"]["score"] == 100  # 10 + 40 + 30 + 20


def test_consent_is_enforced_server_side(client, tenant):
    form = _form(client, tenant).json()
    response = _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"}, consent=False)
    assert response.status_code == 400
    assert client.get("/leads", headers=tenant["op"]).json() == []

    # senza testo di consenso il campo non è richiesto
    free = _form(client, tenant, name="Senza consenso", consent_text="").json()
    assert _submit(client, tenant, free["id"], {"nome": "B", "email": "b@x.it"}, consent=False).status_code == 200


def test_required_fields_are_enforced(client, tenant):
    form = _form(client, tenant).json()
    assert _submit(client, tenant, form["id"], {"nome": "Anna"}).status_code == 400
    assert client.get("/leads", headers=tenant["op"]).json() == []


def test_consent_text_is_snapshotted(client, tenant):
    form = _form(client, tenant).json()
    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"})
    client.patch(f"/lead-forms/{form['id']}", headers=tenant["op"], json={"consent_text": "Testo cambiato"})

    lead = client.get("/leads", headers=tenant["op"]).json()[0]
    assert lead["consent_text"] == "Acconsento al trattamento dei dati."
    assert lead["consent"] is True


def test_lead_can_be_attached_to_a_conversation(client, tenant):
    form = _form(client, tenant).json()
    chat = client.post("/chat", headers=tenant["key"], json={"visitor_id": "lead", "message": "ciao"}).json()

    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"}, conversation=chat)
    assert client.get("/leads", headers=tenant["op"]).json()[0]["conversation_id"] == chat["conversation_id"]

    bad = client.post("/widget/leads", headers=tenant["key"], json={
        "form_id": form["id"], "data": {"nome": "X", "email": "x@x.it"}, "consent": True,
        "conversation_id": chat["conversation_id"], "conversation_token": "sbagliato",
    })
    assert bad.status_code == 404


def test_capture_emits_a_webhook(client, tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(webhooks, "_post", lambda url, body, headers: calls.append(body) or 200)
    client.post("/webhooks", headers=tenant["op"], json={
        "url": "https://crm.example.test/leads", "events": ["lead.captured"],
    })
    form = _form(client, tenant).json()

    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "anna@x.it"})
    with Session(db.engine) as session:
        webhooks.dispatch_pending(session)

    payloads = [json.loads(body) for body in calls]
    assert [p["event"] for p in payloads] == ["lead.captured"]
    assert payloads[0]["data"]["score"] == 50
    assert payloads[0]["data"]["data"]["email"] == "anna@x.it"


# ---- listing, export, isolation ----


def test_filters(client, tenant):
    form = _form(client, tenant).json()
    _submit(client, tenant, form["id"], {"nome": "Basso", "email": "b@x.it"})  # 50
    _submit(client, tenant, form["id"], {"nome": "Alto", "email": "a@x.it", "telefono": "1", "budget": ">5k"})  # 100

    high = client.get("/leads", headers=tenant["op"], params={"min_score": 60}).json()
    assert [lead["data"]["nome"] for lead in high] == ["Alto"]
    assert len(client.get("/leads", headers=tenant["op"], params={"days": 1}).json()) == 2


def test_csv_export_neutralises_formula_injection(client, tenant):
    form = _form(client, tenant, consent_text="").json()
    _submit(client, tenant, form["id"], {"nome": "=1+1", "email": "a@x.it"}, consent=False)

    response = client.get("/leads/export", headers=tenant["op"])
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "lead.csv" in response.headers["content-disposition"]
    body = response.text
    assert '"\'=1+1"' in body  # la formula è neutralizzata, non eseguibile dal foglio di calcolo
    assert "a@x.it" in body
    assert body.splitlines()[0].startswith('﻿"id"')


def test_deleting_a_form_keeps_the_leads(client, tenant):
    form = _form(client, tenant).json()
    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"})

    assert client.delete(f"/lead-forms/{form['id']}", headers=tenant["op"]).status_code == 200
    leads = client.get("/leads", headers=tenant["op"]).json()
    assert len(leads) == 1
    assert leads[0]["form_id"] is None


def test_leads_are_tenant_scoped(client, tenant):
    form = _form(client, tenant).json()
    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"})
    other = _other_tenant(client)

    assert client.get("/leads", headers=other["op"]).json() == []
    assert client.get("/lead-forms", headers=other["op"]).json()["forms"] == []
    assert client.get("/widget/lead-form", headers=other["key"]).json()["form"] is None
    assert client.patch(f"/lead-forms/{form['id']}", headers=other["op"], json={"active": False}).status_code == 404
    assert client.delete(f"/lead-forms/{form['id']}", headers=other["op"]).status_code == 404
    # non si può nemmeno inviare un lead sul form di un altro tenant
    assert client.post("/widget/leads", headers=other["key"], json={
        "form_id": form["id"], "data": {"nome": "X", "email": "x@x.it"}, "consent": True,
    }).status_code == 404
    assert "Anna" not in client.get("/leads/export", headers=other["op"]).text


def test_erasing_a_conversation_removes_its_leads(client, tenant):
    form = _form(client, tenant).json()
    chat = client.post("/chat", headers=tenant["key"], json={"visitor_id": "gdpr", "message": "ciao"}).json()
    _submit(client, tenant, form["id"], {"nome": "Anna", "email": "a@x.it"}, conversation=chat)

    assert client.delete(f"/conversations/{chat['conversation_id']}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.Lead)).all() == []

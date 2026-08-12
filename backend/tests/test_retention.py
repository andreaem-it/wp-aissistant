"""Sospensione alla disdetta e cancellazione dei dati dopo il periodo di grazia.

Non esiste una versione gratuita del prodotto. Prima, chi disdiceva veniva retrocesso a un piano
chiamato "Free" con `monthly_message_limit = 0` — cioè messaggi illimitati: il servizio
continuava gratis, senza scadenza. Ora l'abbonamento che finisce sospende l'assistente, i dati
restano per un periodo di grazia annunciato, poi vengono eliminati.
"""
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from app import billing, db, email as email_service, retention
from conftest import TENANT_ORIGIN


ADMIN = {"Authorization": "Bearer test-admin"}


def _set(cid, **fields):
    with Session(db.engine) as session:
        client = session.get(db.Client, cid)
        for key, value in fields.items():
            setattr(client, key, value)
        session.add(client)
        session.commit()


def _get(cid):
    with Session(db.engine) as session:
        return session.get(db.Client, cid)


# ---- sospensione del servizio -------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_a_paying_tenant_is_served(client, tenant, status):
    """`past_due` è dentro di proposito: è la grazia mentre Stripe ritenta il pagamento, e
    spegnere l'assistente per una carta scaduta farebbe perdere conversazioni vere."""
    _set(tenant["cid"], billing_status=status)

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "ciao",
    }).json()

    assert body["status"] != "suspended"


@pytest.mark.parametrize("status", ["canceled", "incomplete"])
def test_a_tenant_without_a_subscription_is_not_served(client, tenant, status):
    _set(tenant["cid"], billing_status=status)

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "ciao",
    }).json()

    assert body["status"] == "suspended"
    assert body["reply"] is None


def test_the_stream_says_suspended_too(client, tenant):
    _set(tenant["cid"], billing_status="canceled")

    with client.stream("POST", "/chat/stream", headers=tenant["key"],
                       json={"visitor_id": "v1", "message": "ciao"}) as response:
        body = "".join(response.iter_text())

    assert '"type": "suspended"' in body or '"type":"suspended"' in body


def test_no_plan_grants_access_by_itself(client, tenant):
    """Il piano non è più un interruttore: un tenant disdetto resta sul piano che aveva e
    comunque non viene servito. Prima bastava il plan_id giusto."""
    plan = client.post("/admin/plans", headers=ADMIN,
                       json={"name": "Costoso", "price_cents": 9900}).json()
    _set(tenant["cid"], billing_status="canceled", plan_id=plan["id"])

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "ciao"}).json()

    assert body["status"] == "suspended"


# ---- conto alla rovescia ------------------------------------------------------------------


def test_cancelling_starts_the_countdown_from_the_paid_period_end(client, tenant, monkeypatch):
    """I 90 giorni partono da quando finisce ciò che ha pagato, non da quando disdice: chi
    disdice a inizio mese ha già comprato il resto del mese."""
    period_end = datetime.utcnow() + timedelta(days=20)
    _set(tenant["cid"], stripe_subscription_id="sub_x", subscription_period_end=period_end)
    event = {"type": "customer.subscription.deleted",
             "data": {"object": {"id": "sub_x", "status": "canceled", "metadata": {}}}}
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda p, s, sec: event)

    client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})

    due = _get(tenant["cid"]).data_deletion_due_at
    assert due is not None
    assert abs((due - (period_end + timedelta(days=90))).total_seconds()) < 5


def test_reactivating_cancels_the_countdown(client, tenant):
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() + timedelta(days=30),
         deletion_reminder_sent_days=30)

    _set(tenant["cid"], billing_status="active")
    with Session(db.engine) as session:
        retention.run_due(session)

    client_row = _get(tenant["cid"])
    assert client_row.data_deletion_due_at is None
    assert client_row.deletion_reminder_sent_days is None


# ---- promemoria ---------------------------------------------------------------------------


@pytest.fixture
def reminders(monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "send_deletion_reminder",
                        lambda to, days_left, deletion_at=None: sent.append(days_left) or True)
    return sent


def _verified_operator(cid, email="op@x.it"):
    with Session(db.engine) as session:
        operator = session.exec(
            select(db.Operator).where(db.Operator.client_id == cid)
        ).first()
        operator.email_verified = True
        session.add(operator)
        session.commit()


def test_a_reminder_goes_out_at_each_threshold(client, tenant, reminders):
    _verified_operator(tenant["cid"])
    for days, expected in ((25, 30), (10, 14), (5, 7), (2, 3)):
        _set(tenant["cid"], billing_status="canceled",
             data_deletion_due_at=datetime.utcnow() + timedelta(days=days, hours=1))
        with Session(db.engine) as session:
            retention.run_due(session)
        assert reminders[-1] == days, f"a {days} giorni non è partito l'avviso giusto"
        assert _get(tenant["cid"]).deletion_reminder_sent_days == expected


def test_the_same_reminder_is_not_sent_twice(client, tenant, reminders):
    """Il worker gira di continuo: senza memoria di cosa è già uscito, il cliente riceverebbe
    la stessa email a ogni giro."""
    _verified_operator(tenant["cid"])
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() + timedelta(days=10, hours=1))

    for _ in range(3):
        with Session(db.engine) as session:
            retention.run_due(session)

    assert reminders == [10]


def test_a_missed_window_is_recovered_not_skipped(client, tenant, reminders):
    """Un worker fermo una settimana deve mandare l'avviso saltato, non passare oltre."""
    _verified_operator(tenant["cid"])
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() + timedelta(days=20, hours=1))

    with Session(db.engine) as session:
        retention.run_due(session)

    assert reminders == [20]  # soglia dei 30, non saltata
    assert _get(tenant["cid"]).deletion_reminder_sent_days == 30


def test_no_reminder_before_the_first_threshold(client, tenant, reminders):
    _verified_operator(tenant["cid"])
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() + timedelta(days=60))

    with Session(db.engine) as session:
        retention.run_due(session)

    assert reminders == []


# ---- cancellazione ------------------------------------------------------------------------


def test_data_is_deleted_when_the_date_arrives(client, tenant):
    client.post("/ingest/site-page", headers=tenant["key"],
                json={"url": "https://x.it/a", "text": "contenuto " * 30})
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "ciao"})
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() - timedelta(minutes=1))

    with Session(db.engine) as session:
        result = retention.run_due(session)

    assert result["purged"] == 1
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]) is None
        assert not session.exec(
            select(db.Conversation).where(db.Conversation.client_id == tenant["cid"])).all()
        assert not session.exec(
            select(db.Operator).where(db.Operator.client_id == tenant["cid"])).all()


def test_nothing_is_deleted_before_the_date(client, tenant):
    _set(tenant["cid"], billing_status="canceled",
         data_deletion_due_at=datetime.utcnow() + timedelta(days=1))

    with Session(db.engine) as session:
        assert retention.run_due(session)["purged"] == 0
    assert _get(tenant["cid"]) is not None


def test_a_tenant_without_a_due_date_is_never_touched(client, tenant):
    """La cancellazione può partire solo da una data scritta prima: nessuna scorciatoia che
    elimini "adesso" un tenant che non è mai stato messo in coda."""
    _set(tenant["cid"], billing_status="canceled", data_deletion_due_at=None)

    with Session(db.engine) as session:
        assert retention.run_due(session)["purged"] == 0
    assert _get(tenant["cid"]) is not None


def test_a_purge_never_touches_another_tenant(client, tenant):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Vicino", "allowed_origins": TENANT_ORIGIN}).json()
    other_key = {"Authorization": f"Bearer {other['api_key']}"}
    client.post("/chat", headers=other_key, json={"visitor_id": "v", "message": "ciao"})

    with Session(db.engine) as session:
        retention.purge_client(session, tenant["cid"])

    with Session(db.engine) as session:
        assert session.get(db.Client, other["id"]) is not None
        assert session.exec(
            select(db.Conversation).where(db.Conversation.client_id == other["id"])).all()


def test_every_tenant_scoped_table_is_covered(client, tenant):
    """Le tabelle si ricavano dai metadati proprio perché una dimenticanza non darebbe errore:
    lascerebbe dati di un cliente cancellato dentro un sistema multi-tenant."""
    from sqlmodel import SQLModel

    with Session(db.engine) as session:
        retention.purge_client(session, tenant["cid"])

    leftovers = []
    with Session(db.engine) as session:
        for table in SQLModel.metadata.sorted_tables:
            if "client_id" not in table.c or table.name in ("plan", "modelprice"):
                continue
            rows = session.exec(table.select().where(table.c.client_id == tenant["cid"])).all()
            if rows:
                leftovers.append(table.name)

    assert leftovers == []


# ---- l'azione dal pannello ----------------------------------------------------------------


def test_deleting_a_client_requires_its_exact_name(client, tenant):
    """In una lista di clienti la riga sbagliata è a un pixel da quella giusta."""
    refused = client.request("DELETE", f"/admin/clients/{tenant['cid']}",
                             headers=ADMIN, json={"confirm": "sì"})

    assert refused.status_code == 400
    assert _get(tenant["cid"]) is not None


def test_deleting_a_client_works_with_the_name(client, tenant):
    name = _get(tenant["cid"]).name

    response = client.request("DELETE", f"/admin/clients/{tenant['cid']}",
                              headers=ADMIN, json={"confirm": name})

    assert response.status_code == 200
    assert _get(tenant["cid"]) is None


def test_deleting_a_client_is_audited(client, tenant):
    name = _get(tenant["cid"]).name
    client.request("DELETE", f"/admin/clients/{tenant['cid']}", headers=ADMIN,
                   json={"confirm": name})

    actions = [row["action"] for row in client.get("/admin/audit", headers=ADMIN).json()]

    assert "client.deleted" in actions


def test_only_an_admin_can_delete_a_client(client, tenant):
    name = _get(tenant["cid"]).name

    response = client.request("DELETE", f"/admin/clients/{tenant['cid']}",
                              headers=tenant["op"], json={"confirm": name})

    assert response.status_code in (401, 403)
    assert _get(tenant["cid"]) is not None

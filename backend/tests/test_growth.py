"""Activation funnel and at-risk clients. Dates are written directly so each cohort under test
is exact — the fixtures create everything "now", which no funnel test could distinguish."""
from datetime import datetime, timedelta

from sqlmodel import Session

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _client(client, name, *, age_days=1, paid_days_ago=None, status="active"):
    created = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    with Session(db.engine) as session:
        row = session.get(db.Client, created["id"])
        row.created_at = datetime.utcnow() - timedelta(days=age_days)
        row.billing_status = status
        if paid_days_ago is not None:
            row.first_paid_at = datetime.utcnow() - timedelta(days=paid_days_ago)
        session.add(row)
        session.commit()
    return created["id"]


def _conversation(client_id, *, age_days=0, answered=False, rating=None):
    with Session(db.engine) as session:
        when = datetime.utcnow() - timedelta(days=age_days)
        conv = db.Conversation(client_id=client_id, visitor_id="v", created_at=when)
        session.add(conv)
        session.commit()
        session.refresh(conv)
        if answered:
            session.add(db.AiResponseLog(
                client_id=client_id, conversation_id=conv.id,
                outcome="answered", model="m", created_at=when,
            ))
        if rating is not None:
            session.add(db.ConversationRating(
                client_id=client_id, conversation_id=conv.id, score=rating, created_at=when,
            ))
        session.commit()
        return conv.id


def _installed(client_id):
    with Session(db.engine) as session:
        session.add(db.PluginInstallation(
            client_id=client_id,
            site_origin=f"https://s{client_id}.it",
            secret_hash=f"hash-{client_id}",  # unique per installation, as the real flow stores it
        ))
        session.commit()


# ---- Activation funnel -------------------------------------------------------------------------


def test_funnel_counts_each_step(client):
    a = _client(client, "Completo", age_days=5, paid_days_ago=1)
    _installed(a)
    _conversation(a, age_days=4, answered=True)
    b = _client(client, "SoloInstallato", age_days=5)
    _installed(b)
    _client(client, "Fermo", age_days=5)

    data = client.get("/admin/activation", headers=ADMIN).json()
    steps = {s["key"]: s["clients"] for s in data["steps"]}

    assert data["cohort"] == 3
    assert steps == {"created": 3, "installed": 2, "chatted": 1, "activated": 1, "paid": 1}


def test_an_empty_chat_is_not_activation(client):
    """Opening a conversation the AI never answered has not delivered value."""
    cid = _client(client, "Vuoto", age_days=3)
    _conversation(cid, age_days=2, answered=False)

    steps = {s["key"]: s["clients"] for s in client.get("/admin/activation", headers=ADMIN).json()["steps"]}

    assert steps["chatted"] == 1
    assert steps["activated"] == 0


def test_clients_without_a_creation_date_are_reported_separately(client):
    """They predate the field: excluded from the cohort, counted out loud, never invented."""
    known = _client(client, "Datato", age_days=2)
    _conversation(known, answered=True)
    unknown = client.post("/admin/clients", headers=ADMIN, json={"name": "Ignoto"}).json()["id"]
    with Session(db.engine) as session:
        row = session.get(db.Client, unknown)
        row.created_at = None
        session.add(row)
        session.commit()

    data = client.get("/admin/activation", headers=ADMIN).json()

    assert data["cohort"] == 1
    assert data["undated_clients"] == 1
    # the undated client must not count as a failure to activate
    assert next(s["pct"] for s in data["steps"] if s["key"] == "activated") == 100.0


def test_funnel_respects_the_window(client):
    recent = _client(client, "Recente", age_days=10)
    _conversation(recent, answered=True)
    old = _client(client, "Vecchio", age_days=200)
    _conversation(old, age_days=199, answered=True)

    narrow = client.get("/admin/activation", headers=ADMIN, params={"days": 30}).json()
    wide = client.get("/admin/activation", headers=ADMIN, params={"days": 365}).json()

    assert narrow["cohort"] == 1
    assert wide["cohort"] == 2


def test_funnel_reports_time_to_activation(client):
    cid = _client(client, "Veloce", age_days=2)
    with Session(db.engine) as session:
        row = session.get(db.Client, cid)
        created = row.created_at
    with Session(db.engine) as session:
        conv = db.Conversation(client_id=cid, visitor_id="v", created_at=created + timedelta(hours=6))
        session.add(conv)
        session.commit()
        session.refresh(conv)
        session.add(db.AiResponseLog(client_id=cid, conversation_id=conv.id, outcome="answered",
                                     model="m", created_at=created + timedelta(hours=6)))
        session.commit()

    assert client.get("/admin/activation", headers=ADMIN).json()["median_hours_to_activation"] == 6.0


def test_funnel_lists_who_is_stuck(client):
    _client(client, "Bloccato", age_days=9)
    ok = _client(client, "Attivo", age_days=9)
    _conversation(ok, answered=True)

    stuck = client.get("/admin/activation", headers=ADMIN).json()["stuck"]

    assert [s["name"] for s in stuck] == ["Bloccato"]
    assert stuck[0]["reached"] == "created"


def test_activation_window_is_bounded(client):
    assert client.get("/admin/activation", headers=ADMIN, params={"days": 0}).status_code == 400
    assert client.get("/admin/activation", headers=ADMIN, params={"days": 400}).status_code == 400


# ---- At-risk clients ---------------------------------------------------------------------------


def test_usage_drop_is_measured_against_the_client_itself(client):
    """A big tenant halving matters; a small one going from 2 to 1 is noise."""
    big = _client(client, "Grande", age_days=60)
    for _ in range(10):
        _conversation(big, age_days=20)   # previous window
    _conversation(big, age_days=3)        # current window
    small = _client(client, "Piccolo", age_days=60)
    for _ in range(2):
        _conversation(small, age_days=20)
    _conversation(small, age_days=3)

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]
    flagged = {r["name"]: r["reasons"] for r in rows}

    assert any("uso calato" in reason for reason in flagged.get("Grande", []))
    assert not any("uso calato" in reason for reason in flagged.get("Piccolo", []))


def test_billing_trouble_is_a_reason(client):
    cid = _client(client, "Insoluto", age_days=30, status="past_due")
    _conversation(cid, age_days=1)

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]

    assert "pagamento non riuscito" in next(r["reasons"] for r in rows if r["client_id"] == cid)


def test_scheduled_cancellation_is_a_reason(client):
    cid = _client(client, "Disdetto", age_days=30)
    _conversation(cid, age_days=1)
    with Session(db.engine) as session:
        row = session.get(db.Client, cid)
        row.subscription_cancel_at_period_end = True
        session.add(row)
        session.commit()

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]

    assert "disdetta programmata" in next(r["reasons"] for r in rows if r["client_id"] == cid)


def test_silence_and_never_used_are_distinguished(client):
    silent = _client(client, "Silenzioso", age_days=60)
    _conversation(silent, age_days=40)
    never = _client(client, "MaiUsato", age_days=30)

    rows = {r["name"]: r["reasons"] for r in client.get("/admin/at-risk", headers=ADMIN).json()["clients"]}

    assert any("nessuna conversazione da" in r for r in rows["Silenzioso"])
    assert "mai usato dopo la registrazione" in rows["MaiUsato"]


def test_low_csat_is_a_reason(client):
    cid = _client(client, "Scontento", age_days=30)
    _conversation(cid, age_days=1, answered=True, rating=1)
    _conversation(cid, age_days=1, answered=True, rating=2)

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]

    assert any("CSAT" in r for r in next(x["reasons"] for x in rows if x["client_id"] == cid))


def test_a_healthy_client_is_not_flagged(client):
    cid = _client(client, "Sano", age_days=60)
    for _ in range(6):
        _conversation(cid, age_days=20)
    for _ in range(6):
        _conversation(cid, age_days=2, answered=True, rating=5)

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]

    assert cid not in [r["client_id"] for r in rows]


def test_clients_with_more_reasons_come_first(client):
    one = _client(client, "UnMotivo", age_days=30)
    _conversation(one, age_days=40)
    many = _client(client, "PiuMotivi", age_days=30, status="past_due")
    _conversation(many, age_days=40)

    rows = client.get("/admin/at-risk", headers=ADMIN).json()["clients"]

    assert rows[0]["name"] == "PiuMotivi"


def test_risk_window_is_bounded(client):
    assert client.get("/admin/at-risk", headers=ADMIN, params={"days": 0}).status_code == 400
    assert client.get("/admin/at-risk", headers=ADMIN, params={"days": 200}).status_code == 400


# ---- First payment ------------------------------------------------------------------------------


def test_first_payment_is_recorded_once(client, tenant, monkeypatch):
    """Later renewals must not push the date forward: it marks when a trial became revenue."""
    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        row.stripe_subscription_id = "sub_paid"
        session.add(row)
        session.commit()
    event = {"type": "invoice.payment_succeeded",
             "data": {"object": {"subscription": "sub_paid", "amount_paid": 7900, "metadata": {}}}}
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda p, s, sec: event)

    client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})
    with Session(db.engine) as session:
        first = session.get(db.Client, tenant["cid"]).first_paid_at
    assert first is not None

    client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).first_paid_at == first


def test_a_zero_amount_invoice_is_not_a_payment(client, tenant, monkeypatch):
    """A fully discounted trial invoice collects nothing and must not count as revenue."""
    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        row.stripe_subscription_id = "sub_free"
        session.add(row)
        session.commit()
    event = {"type": "invoice.payment_succeeded",
             "data": {"object": {"subscription": "sub_free", "amount_paid": 0, "metadata": {}}}}
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda p, s, sec: event)

    client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})

    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).first_paid_at is None


# ---- Access --------------------------------------------------------------------------------------


def test_growth_endpoints_require_the_admin_key(client, tenant):
    """Cross-tenant: both views span every client, so an operator token must never reach them."""
    for path in ("/admin/activation", "/admin/at-risk"):
        assert client.get(path, headers=tenant["op"]).status_code in (401, 403)
        assert client.get(path).status_code in (401, 403)

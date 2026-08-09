"""Billing (Stripe) integration tests. Stripe network calls are monkeypatched, so no real
account/keys are needed — conftest sets dummy STRIPE_* env so /billing/* is enabled."""
import types
from datetime import datetime, timedelta

from sqlmodel import Session

from app import db


def _attach_customer(client_id, customer="cus_portal", subscription="sub_portal"):
    """Give the tenant a Stripe customer/subscription, as a completed checkout would."""
    with Session(db.engine) as session:
        row = session.get(db.Client, client_id)
        row.stripe_customer_id = customer
        row.stripe_subscription_id = subscription
        session.add(row)
        session.commit()


def _capture_emails(monkeypatch):
    """Collect every outgoing email instead of sending it; returns the growing list."""
    sent = []

    def fake_send(to, subject, body, **kwargs):
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.email.send_email", fake_send)
    return sent


def _fire(client, monkeypatch, event):
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda payload, sig, secret: event)
    return client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})


def _make_paid_plan(client, price_id="price_123"):
    """Create a plan via the admin API and give it a Stripe price id; returns its id."""
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post("/admin/plans", headers=admin, json={"name": "Pro", "price_cents": 7900}).json()
    client.post(f"/admin/plans/{plan['id']}", headers=admin, json={"stripe_price_id": price_id})
    return plan["id"]


def test_checkout_returns_url(client, tenant, monkeypatch):
    plan_id = _make_paid_plan(client)
    monkeypatch.setattr(
        "stripe.checkout.Session.create",
        lambda **kw: types.SimpleNamespace(url="https://checkout.stripe/x", id="cs_test_1"),
    )
    r = client.post("/billing/checkout", headers=tenant["op"], json={"plan_id": plan_id})
    assert r.status_code == 200
    assert r.json()["checkout_url"] == "https://checkout.stripe/x"


def test_checkout_uses_yearly_price(client, tenant, monkeypatch):
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post(
        "/admin/plans",
        headers=admin,
        json={
            "name": "Annual",
            "price_cents": 4900,
            "yearly_price_cents": 49000,
            "stripe_price_id": "price_month",
            "stripe_yearly_price_id": "price_year",
        },
    ).json()
    captured = {}

    def create_checkout(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(url="https://checkout.stripe/year", id="cs_year")

    monkeypatch.setattr("stripe.checkout.Session.create", create_checkout)
    response = client.post(
        "/billing/checkout",
        headers=tenant["op"],
        json={"plan_id": plan["id"], "billing_interval": "year"},
    )

    assert response.status_code == 200
    assert captured["line_items"][0]["price"] == "price_year"


def test_checkout_requires_stripe_price_id(client, tenant):
    # a plan without a stripe_price_id can't be checked out
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post("/admin/plans", headers=admin, json={"name": "NoPrice", "price_cents": 900}).json()
    r = client.post("/billing/checkout", headers=tenant["op"], json={"plan_id": plan["id"]})
    assert r.status_code == 400


def test_admin_can_update_plan_commercial_settings(client):
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post(
        "/admin/plans",
        headers=admin,
        json={"name": "Old", "price_cents": 7900},
    ).json()

    response = client.post(
        f"/admin/plans/{plan['id']}",
        headers=admin,
        json={
            "name": "Pro",
            "price_cents": 4900,
            "currency": "EUR",
            "chat_rate_limit": 120,
            "ingest_rate_limit": 240,
            "monthly_message_limit": 2500,
            "stripe_price_id": "price_new",
            "yearly_price_cents": 49000,
            "stripe_yearly_price_id": "price_yearly",
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Pro"
    assert updated["price_cents"] == 4900
    assert updated["currency"] == "eur"
    assert updated["monthly_message_limit"] == 2500
    assert updated["stripe_price_id"] == "price_new"
    assert updated["yearly_price_cents"] == 49000
    assert updated["stripe_yearly_price_id"] == "price_yearly"


def test_admin_rejects_invalid_plan_commercial_settings(client):
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post("/admin/plans", headers=admin, json={"name": "Valid", "price_cents": 900}).json()

    response = client.post(
        f"/admin/plans/{plan['id']}",
        headers=admin,
        json={"price_cents": -1},
    )

    assert response.status_code == 400


def test_webhook_checkout_completed_activates_plan(client, tenant, monkeypatch):
    plan_id = _make_paid_plan(client, price_id="price_pro")
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"client_id": str(tenant["cid"]), "plan_id": str(plan_id)},
            "customer": "cus_1",
            "subscription": "sub_1",
        }},
    }
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda payload, sig, secret: event)

    r = client.post("/billing/webhook", data="{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 200

    with Session(db.engine) as session:
        c = session.get(db.Client, tenant["cid"])
        assert c.plan_id == plan_id
        assert c.billing_status == "active"
        assert c.stripe_customer_id == "cus_1"
        assert c.stripe_subscription_id == "sub_1"


def test_webhook_cancel_suspends_without_downgrading(client, tenant, monkeypatch):

    paid_plan_id = _make_paid_plan(client, price_id="price_cancel")
    with Session(db.engine) as session:
        c = session.get(db.Client, tenant["cid"])
        c.plan_id = paid_plan_id
        c.stripe_subscription_id = "sub_cancel"
        session.add(c)
        session.commit()

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_cancel", "status": "canceled", "metadata": {}}},
    }
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda payload, sig, secret: event)
    assert client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"}).status_code == 200

    with Session(db.engine) as session:
        c = session.get(db.Client, tenant["cid"])
        assert c.billing_status == "canceled"
        # nessuna retrocessione: non esiste un piano gratuito. Il piano resta quello che aveva,
        # come traccia di cosa riattivare; a decidere l'accesso è billing_status.
        assert c.plan_id == paid_plan_id
        assert c.data_deletion_due_at is not None  # parte il conto alla rovescia dei 90 giorni


def test_webhook_subscription_deleted_marks_canceled(client, tenant, monkeypatch):
    # first attach a subscription id to the client
    with Session(db.engine) as session:
        c = session.get(db.Client, tenant["cid"])
        c.stripe_subscription_id = "sub_del"
        session.add(c)
        session.commit()

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_del", "status": "canceled", "metadata": {}}},
    }
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda payload, sig, secret: event)

    r = client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"})
    assert r.status_code == 200
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).billing_status == "canceled"


# ---- Billing portal ------------------------------------------------------------------------


def test_portal_returns_url(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"])
    monkeypatch.setattr(
        "stripe.billing_portal.Session.create",
        lambda **kw: types.SimpleNamespace(url="https://billing.stripe/p/session"),
    )

    response = client.post("/billing/portal", headers=tenant["op"])

    assert response.status_code == 200
    assert response.json()["portal_url"] == "https://billing.stripe/p/session"


def test_portal_without_subscription_is_explicit(client, tenant):
    # never checked out: say there is nothing to manage rather than open an empty portal
    response = client.post("/billing/portal", headers=tenant["op"])
    assert response.status_code == 409


def test_portal_reports_stripe_failure(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"])

    def explode(**kwargs):
        raise RuntimeError("stripe is down")

    monkeypatch.setattr("stripe.billing_portal.Session.create", explode)

    response = client.post("/billing/portal", headers=tenant["op"])

    # no optimistic confirmation: the operator is told the portal is unavailable
    assert response.status_code == 502


def test_portal_requires_authentication(client, tenant):
    _attach_customer(tenant["cid"])
    assert client.post("/billing/portal").status_code in (401, 403)


def test_portal_opens_only_the_callers_own_customer(client, tenant, monkeypatch):
    """Tenant isolation: the customer comes from the caller's session, never from the request."""
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Other"}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators",
        headers=admin,
        json={"email": "op@other.it", "password": "pw"},
    )
    other_token = client.post(
        "/operator/login", json={"email": "op@other.it", "password": "pw"}
    ).json()["token"]
    _attach_customer(tenant["cid"], customer="cus_acme", subscription="sub_acme")
    _attach_customer(other["id"], customer="cus_other", subscription="sub_other")
    seen = {}

    def create_portal(**kwargs):
        seen.update(kwargs)
        return types.SimpleNamespace(url="https://billing.stripe/p/x")

    monkeypatch.setattr("stripe.billing_portal.Session.create", create_portal)

    client.post("/billing/portal", headers={"Authorization": f"Bearer {other_token}"})

    assert seen["customer"] == "cus_other"


# ---- Subscription period mirrored onto the client -------------------------------------------


def test_webhook_stores_subscription_period(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_period")
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_period",
            "status": "active",
            "current_period_end": 1789000000,
            "cancel_at_period_end": False,
            "metadata": {},
        }},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        assert row.subscription_period_end == datetime.utcfromtimestamp(1789000000)
        assert row.subscription_cancel_at_period_end is False


def test_usage_reports_period_without_calling_stripe(client, tenant, monkeypatch):
    """/usage is polled by the WordPress plugin: it must read the row, not call Stripe."""
    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        row.subscription_period_end = datetime(2026, 9, 12, 10, 30)
        row.subscription_cancel_at_period_end = True
        row.stripe_subscription_id = "sub_usage"
        session.add(row)
        session.commit()

    def forbidden(*args, **kwargs):
        raise AssertionError("/usage must not call Stripe")

    monkeypatch.setattr("stripe.Subscription.retrieve", forbidden)

    payload = client.get("/usage", headers=tenant["op"]).json()

    assert payload["subscription_expires_at"].startswith("2026-09-12T10:30:00")
    assert payload["cancel_at_period_end"] is True


def test_webhook_ignores_a_malformed_period(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_bad")
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_bad", "status": "active", "current_period_end": "boom", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    with Session(db.engine) as session:
        # an unreadable date leaves the field untouched rather than storing a wrong one
        assert session.get(db.Client, tenant["cid"]).subscription_period_end is None


# ---- Dunning notifications ------------------------------------------------------------------


def test_payment_failure_warns_the_tenant(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_dunning")
    sent = _capture_emails(monkeypatch)
    event = {
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_dunning", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    assert [m["to"] for m in sent] == ["op@acme.it"]
    assert "Pagamento non riuscito" in sent[0]["subject"]


def test_trial_ending_warns_the_tenant(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_trial")
    sent = _capture_emails(monkeypatch)
    event = {
        "type": "customer.subscription.trial_will_end",
        "data": {"object": {"id": "sub_trial", "trial_end": 1789000000, "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    assert len(sent) == 1
    assert "prova" in sent[0]["subject"].lower()


def test_scheduled_cancellation_is_announced_once(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_sched")
    sent = _capture_emails(monkeypatch)
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_sched",
            "status": "active",
            "cancel_at_period_end": True,
            "current_period_end": 1789000000,
            "metadata": {},
        }},
    }

    assert _fire(client, monkeypatch, event).status_code == 200
    assert _fire(client, monkeypatch, event).status_code == 200  # Stripe repeats the event

    assert len(sent) == 1  # the customer is told once, not on every subscription update
    assert "Disdetta" in sent[0]["subject"]


def test_cancellation_notifies_the_tenant(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_gone")
    sent = _capture_emails(monkeypatch)
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_gone", "status": "canceled", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    assert len(sent) == 1
    assert "terminato" in sent[0]["subject"].lower()


def test_notification_failure_does_not_break_the_sync(client, tenant, monkeypatch):
    """Stripe must still get its 200: a broken mailer cannot cause endless webhook retries."""
    _attach_customer(tenant["cid"], subscription="sub_mailfail")

    def explode(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("app.email.send_email", explode)
    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_mailfail", "status": "canceled", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).billing_status == "canceled"


def test_billing_events_do_not_notify_other_tenants(client, tenant, monkeypatch):
    """Tenant isolation on the notification path: only the owning tenant's operators are mailed."""
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Bystander"}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators",
        headers=admin,
        json={"email": "op@bystander.it", "password": "pw"},
    )
    _attach_customer(tenant["cid"], subscription="sub_scoped")
    sent = _capture_emails(monkeypatch)
    event = {
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": "sub_scoped", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    assert [m["to"] for m in sent] == ["op@acme.it"]


# ---- Revenue reporting ----------------------------------------------------------------------


def _plan(client, name, price_cents=0, yearly_price_cents=0, currency="eur"):
    admin = {"Authorization": "Bearer test-admin"}
    return client.post("/admin/plans", headers=admin, json={
        "name": name,
        "price_cents": price_cents,
        "yearly_price_cents": yearly_price_cents,
        "currency": currency,
    }).json()["id"]


def _subscriber(client, name, plan_id, *, status="active", interval="month", **fields):
    """Create a tenant already in a given commercial state, as the webhook would leave it."""
    admin = {"Authorization": "Bearer test-admin"}
    created = client.post("/admin/clients", headers=admin, json={"name": name}).json()
    with Session(db.engine) as session:
        row = session.get(db.Client, created["id"])
        row.plan_id = plan_id
        row.billing_status = status
        row.subscription_interval = interval
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()
    return created["id"]


ADMIN = {"Authorization": "Bearer test-admin"}


def test_revenue_normalises_yearly_subscriptions(client):
    """A yearly subscriber contributes a twelfth per month, not the monthly price."""
    monthly = _plan(client, "Mensile", price_cents=10_000, yearly_price_cents=120_000)
    _subscriber(client, "Mese", monthly, interval="month")
    _subscriber(client, "Anno", monthly, interval="year")

    data = client.get("/admin/revenue", headers=ADMIN).json()

    # 10000 (monthly) + 120000/12 = 10000 -> 20000, not 10000 + 10000*12
    assert data["mrr_cents"] == 20_000
    assert data["arr_cents"] == 240_000
    assert data["paying_clients"] == 2
    assert data["arpa_cents"] == 10_000


def test_revenue_does_not_price_a_yearly_plan_without_a_yearly_price(client):
    """Rather than charge them the monthly rate, an unpriceable subscription counts as zero."""
    plan_id = _plan(client, "SoloMensile", price_cents=5_000, yearly_price_cents=0)
    _subscriber(client, "Annuale", plan_id, interval="year")

    assert client.get("/admin/revenue", headers=ADMIN).json()["mrr_cents"] == 0


def test_revenue_separates_paid_at_risk_and_trial(client):
    plan_id = _plan(client, "Pro", price_cents=7_900)
    _subscriber(client, "Paga", plan_id, status="active")
    _subscriber(client, "Insoluto", plan_id, status="past_due")
    _subscriber(client, "Prova", plan_id, status="trialing")
    _subscriber(client, "Uscito", plan_id, status="canceled")

    data = client.get("/admin/revenue", headers=ADMIN).json()

    # money actually collected is never mixed with money at risk or merely hoped for
    assert data["mrr_cents"] == 7_900
    assert data["at_risk_cents"] == 7_900
    assert data["trial_cents"] == 7_900
    assert [r["name"] for r in data["past_due"]] == ["Insoluto"]


def test_revenue_flags_mixed_currencies_instead_of_summing_them(client):
    euro = _plan(client, "Euro", price_cents=10_000, currency="eur")
    dollars = _plan(client, "Dollari", price_cents=10_000, currency="usd")
    _subscriber(client, "IT", euro)
    _subscriber(client, "US", dollars)

    data = client.get("/admin/revenue", headers=ADMIN).json()

    assert data["mixed_currencies"] is True
    assert data["currency"] is None  # no single currency can label the total


def test_revenue_groups_by_plan(client):
    small = _plan(client, "Small", price_cents=2_900)
    big = _plan(client, "Big", price_cents=9_900)
    _subscriber(client, "A", small)
    _subscriber(client, "B", big)
    _subscriber(client, "C", big)

    by_plan = client.get("/admin/revenue", headers=ADMIN).json()["by_plan"]

    assert by_plan["Small"] == {"clients": 1, "mrr_cents": 2_900}
    assert by_plan["Big"] == {"clients": 2, "mrr_cents": 19_800}


def test_revenue_lists_trials_ending_within_a_week(client):
    plan_id = _plan(client, "Trial", price_cents=4_900)
    _subscriber(
        client, "Scade", plan_id, status="trialing",
        subscription_period_end=datetime.utcnow() + timedelta(days=3),
    )
    _subscriber(
        client, "Lontano", plan_id, status="trialing",
        subscription_period_end=datetime.utcnow() + timedelta(days=30),
    )

    ending = client.get("/admin/revenue", headers=ADMIN).json()["trials_ending"]

    assert [r["name"] for r in ending] == ["Scade"]


def test_revenue_reports_cancellations_in_the_window(client):
    plan_id = _plan(client, "Churn", price_cents=4_900)
    _subscriber(
        client, "Recente", plan_id, status="canceled",
        subscription_canceled_at=datetime.utcnow() - timedelta(days=3),
    )
    _subscriber(
        client, "Vecchia", plan_id, status="canceled",
        subscription_canceled_at=datetime.utcnow() - timedelta(days=200),
    )

    data = client.get("/admin/revenue", headers=ADMIN).json()

    assert [r["name"] for r in data["recent_cancellations"]] == ["Recente"]
    assert data["window_days"] == 30
    # a rate is never reported: without historical snapshots it would be invented
    assert "churn_rate" not in data


def test_revenue_window_is_configurable_and_bounded(client):
    plan_id = _plan(client, "Window", price_cents=1_000)
    _subscriber(
        client, "Uscito", plan_id, status="canceled",
        subscription_canceled_at=datetime.utcnow() - timedelta(days=100),
    )

    wide = client.get("/admin/revenue", headers=ADMIN, params={"days": 180}).json()
    assert [r["name"] for r in wide["recent_cancellations"]] == ["Uscito"]
    assert client.get("/admin/revenue", headers=ADMIN, params={"days": 0}).status_code == 400
    assert client.get("/admin/revenue", headers=ADMIN, params={"days": 400}).status_code == 400


def test_revenue_lists_scheduled_cancellations(client):
    plan_id = _plan(client, "Scheduled", price_cents=4_900)
    _subscriber(
        client, "Disdetto", plan_id, subscription_cancel_at_period_end=True,
        subscription_period_end=datetime.utcnow() + timedelta(days=10),
    )
    _subscriber(client, "Resta", plan_id)

    scheduled = client.get("/admin/revenue", headers=ADMIN).json()["scheduled_cancellations"]

    assert [r["name"] for r in scheduled] == ["Disdetto"]


def test_revenue_requires_the_admin_key(client, tenant):
    """Cross-tenant: revenue spans every client, so an operator token must never reach it."""
    assert client.get("/admin/revenue", headers=tenant["op"]).status_code in (401, 403)
    assert client.get("/admin/revenue").status_code in (401, 403)


# ---- Billing interval captured from Stripe --------------------------------------------------


def test_webhook_reads_the_interval_from_the_subscription(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_interval")
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_interval",
            "status": "active",
            "items": {"data": [{"price": {"recurring": {"interval": "year"}}}]},
            "metadata": {},
        }},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).subscription_interval == "year"


def test_webhook_keeps_the_known_interval_when_stripe_omits_it(client, tenant, monkeypatch):
    """Guessing "month" for a yearly subscriber would inflate the MRR twelvefold."""
    _attach_customer(tenant["cid"], subscription="sub_keep")
    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        row.subscription_interval = "year"
        session.add(row)
        session.commit()
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_keep", "status": "active", "metadata": {}}},
    }

    assert _fire(client, monkeypatch, event).status_code == 200

    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).subscription_interval == "year"


def test_cancellation_is_timestamped_and_cleared_on_resubscribe(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_churn")
    deleted = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_churn", "status": "canceled", "metadata": {}}},
    }
    assert _fire(client, monkeypatch, deleted).status_code == 200
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).subscription_canceled_at is not None

    revived = {
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub_churn", "status": "active", "metadata": {}}},
    }
    assert _fire(client, monkeypatch, revived).status_code == 200
    with Session(db.engine) as session:
        # a live subscription is not churn: the timestamp must not linger
        assert session.get(db.Client, tenant["cid"]).subscription_canceled_at is None


# ---- Commercial actions ---------------------------------------------------------------------


def _capture_modify(monkeypatch):
    """Record what would be sent to Stripe instead of sending it."""
    calls = []

    def fake_modify(subscription_id, **kwargs):
        calls.append({"id": subscription_id, **kwargs})
        return types.SimpleNamespace(id=subscription_id)

    monkeypatch.setattr("stripe.Subscription.modify", fake_modify)
    return calls


def test_trial_extension_counts_from_today(client, tenant, monkeypatch):
    """Extending an expired trial by 3 days must mean 3 days from now, not from a past date."""
    _attach_customer(tenant["cid"], subscription="sub_trial_ext")
    calls = _capture_modify(monkeypatch)

    response = client.post(f"/admin/clients/{tenant['cid']}/subscription/trial",
                           headers=ADMIN, json={"days": 3})

    assert response.status_code == 200
    expected = datetime.utcnow() + timedelta(days=3)
    assert abs(calls[0]["trial_end"] - int(expected.timestamp())) < 120
    assert calls[0]["proration_behavior"] == "none"


def test_trial_extension_is_bounded(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_bounds")
    _capture_modify(monkeypatch)

    for days in (0, -5, 400):
        response = client.post(f"/admin/clients/{tenant['cid']}/subscription/trial",
                               headers=ADMIN, json={"days": days})
        assert response.status_code == 409


def test_actions_require_a_subscription(client, tenant, monkeypatch):
    """A client that never checked out has nothing to act on: say so, don't pretend."""
    _capture_modify(monkeypatch)

    response = client.post(f"/admin/clients/{tenant['cid']}/subscription/trial",
                           headers=ADMIN, json={"days": 7})

    assert response.status_code == 409
    assert "abbonamento" in response.json()["detail"].lower()


def test_discount_is_applied_and_removed(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_disc")
    calls = _capture_modify(monkeypatch)

    client.post(f"/admin/clients/{tenant['cid']}/subscription/discount",
                headers=ADMIN, json={"coupon": "NATALE20"})
    client.delete(f"/admin/clients/{tenant['cid']}/subscription/discount", headers=ADMIN)

    assert calls[0]["coupon"] == "NATALE20"
    assert calls[1]["coupon"] == ""  # emptying the field is how Stripe removes a discount


def test_pause_and_resume_collection(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_pause")
    calls = _capture_modify(monkeypatch)

    client.post(f"/admin/clients/{tenant['cid']}/subscription/pause", headers=ADMIN, json={"paused": True})
    client.post(f"/admin/clients/{tenant['cid']}/subscription/pause", headers=ADMIN, json={"paused": False})

    assert calls[0]["pause_collection"] == {"behavior": "void"}
    assert calls[1]["pause_collection"] == ""


def test_cancellation_is_scheduled_never_immediate(client, tenant, monkeypatch):
    """The customer paid through the period: taking the service away early invites a dispute."""
    _attach_customer(tenant["cid"], subscription="sub_cancel_admin")
    calls = _capture_modify(monkeypatch)

    client.post(f"/admin/clients/{tenant['cid']}/subscription/cancel", headers=ADMIN, json={"cancel": True})

    assert calls[0]["cancel_at_period_end"] is True
    assert "cancel_now" not in calls[0] and "invoice_now" not in calls[0]


def test_cancellation_can_be_revoked(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_revoke")
    calls = _capture_modify(monkeypatch)

    client.post(f"/admin/clients/{tenant['cid']}/subscription/cancel", headers=ADMIN, json={"cancel": False})

    assert calls[0]["cancel_at_period_end"] is False


def test_actions_do_not_write_billing_state_directly(client, tenant, monkeypatch):
    """The webhook is the only writer: an action must leave the row untouched."""
    _attach_customer(tenant["cid"], subscription="sub_nowrite")
    _capture_modify(monkeypatch)
    with Session(db.engine) as session:
        before = session.get(db.Client, tenant["cid"]).billing_status

    client.post(f"/admin/clients/{tenant['cid']}/subscription/cancel", headers=ADMIN, json={"cancel": True})

    with Session(db.engine) as session:
        row = session.get(db.Client, tenant["cid"])
        assert row.billing_status == before
        assert row.subscription_cancel_at_period_end is False  # only the webhook may set this


def test_a_stripe_refusal_is_reported(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_refused")

    def refuse(subscription_id, **kwargs):
        raise RuntimeError("coupon does not exist")

    monkeypatch.setattr("stripe.Subscription.modify", refuse)

    response = client.post(f"/admin/clients/{tenant['cid']}/subscription/discount",
                           headers=ADMIN, json={"coupon": "INESISTENTE"})

    assert response.status_code == 409  # no optimistic "done" when Stripe said no


def test_commercial_actions_are_audited(client, tenant, monkeypatch):
    _attach_customer(tenant["cid"], subscription="sub_audited")
    _capture_modify(monkeypatch)

    client.post(f"/admin/clients/{tenant['cid']}/subscription/trial", headers=ADMIN, json={"days": 5})

    actions = [row["action"] for row in client.get("/admin/audit", headers=ADMIN).json()]
    assert "subscription.trial_extended" in actions


def test_commercial_actions_require_the_admin_key(client, tenant):
    for path, method in (
        (f"/admin/clients/{tenant['cid']}/subscription/trial", "post"),
        (f"/admin/clients/{tenant['cid']}/subscription/discount", "post"),
        (f"/admin/clients/{tenant['cid']}/subscription/cancel", "post"),
    ):
        response = getattr(client, method)(path, headers=tenant["op"], json={"days": 1, "coupon": "X"})
        assert response.status_code in (401, 403)


# ---- Plan change goes through Stripe ----------------------------------------------------------


def test_plan_change_routes_through_stripe_when_subscribed(client, tenant, monkeypatch):
    """The old behaviour wrote plan_id straight to the row, leaving Stripe billing the old plan."""
    plan_id = _make_paid_plan(client, price_id="price_target")
    _attach_customer(tenant["cid"], subscription="sub_planchange")
    calls = _capture_modify(monkeypatch)
    monkeypatch.setattr(
        "stripe.Subscription.retrieve",
        lambda sid: {"items": {"data": [{"id": "si_1"}]}},
    )

    response = client.post(f"/admin/clients/{tenant['cid']}/plan", headers=ADMIN, json={"plan_id": plan_id})

    assert response.status_code == 200
    body = response.json()
    assert body["via"] == "stripe"
    assert body["pending_plan_id"] == plan_id
    assert calls[0]["items"] == [{"id": "si_1", "price": "price_target"}]
    with Session(db.engine) as session:
        # untouched until the webhook confirms it
        assert session.get(db.Client, tenant["cid"]).plan_id != plan_id


def test_plan_change_replaces_the_line_instead_of_adding_one(client, tenant, monkeypatch):
    """Without the existing item id Stripe would add a second line and bill the customer twice."""
    plan_id = _make_paid_plan(client, price_id="price_second")
    _attach_customer(tenant["cid"], subscription="sub_line")
    calls = _capture_modify(monkeypatch)
    monkeypatch.setattr("stripe.Subscription.retrieve", lambda sid: {"items": {"data": [{"id": "si_existing"}]}})

    client.post(f"/admin/clients/{tenant['cid']}/plan", headers=ADMIN, json={"plan_id": plan_id})

    assert calls[0]["items"][0]["id"] == "si_existing"
    assert len(calls[0]["items"]) == 1


def test_plan_change_stays_direct_without_a_subscription(client, tenant):
    """Free and manually provisioned clients have nothing to sync: the direct write remains."""
    plan_id = _make_paid_plan(client, price_id="price_direct")

    response = client.post(f"/admin/clients/{tenant['cid']}/plan", headers=ADMIN, json={"plan_id": plan_id})

    assert response.json()["via"] == "direct"
    with Session(db.engine) as session:
        assert session.get(db.Client, tenant["cid"]).plan_id == plan_id

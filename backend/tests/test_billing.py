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
    plan = client.post("/admin/plans", headers=admin, json={"name": "NoPrice"}).json()
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
    plan = client.post("/admin/plans", headers=admin, json={"name": "Valid"}).json()

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


def test_webhook_cancel_downgrades_to_free(client, tenant, monkeypatch):
    from sqlmodel import select

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
        free = session.exec(select(db.Plan).where(db.Plan.name == "Free")).first()
        assert c.billing_status == "canceled"
        assert c.plan_id == free.id  # downgraded off the paid plan


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

"""Billing (Stripe) integration tests. Stripe network calls are monkeypatched, so no real
account/keys are needed — conftest sets dummy STRIPE_* env so /billing/* is enabled."""
import types
from datetime import datetime

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

"""Billing (Stripe) integration tests. Stripe network calls are monkeypatched, so no real
account/keys are needed — conftest sets dummy STRIPE_* env so /billing/* is enabled."""
import types

from sqlmodel import Session

from app import db


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


def test_checkout_requires_stripe_price_id(client, tenant):
    # a plan without a stripe_price_id can't be checked out
    admin = {"Authorization": "Bearer test-admin"}
    plan = client.post("/admin/plans", headers=admin, json={"name": "NoPrice"}).json()
    r = client.post("/billing/checkout", headers=tenant["op"], json={"plan_id": plan["id"]})
    assert r.status_code == 400


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

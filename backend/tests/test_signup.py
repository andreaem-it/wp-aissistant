"""Self-serve signup tests. Stripe is monkeypatched; conftest sets dummy STRIPE_* env so
billing is enabled. A 'Free' plan is created first so it's the default (oldest) plan, matching
production where migration 0005 seeds it."""
import types

from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _setup_plans(client):
    """Seed a Free plan (default, no price) + a purchasable Pro plan; returns Pro's id."""
    client.post("/admin/plans", headers=ADMIN, json={"name": "Free"})
    pro = client.post("/admin/plans", headers=ADMIN, json={"name": "Pro", "price_cents": 4900}).json()
    client.post(f"/admin/plans/{pro['id']}", headers=ADMIN, json={"stripe_price_id": "price_pro"})
    return pro["id"]


def _mock_checkout(monkeypatch, url="https://checkout.stripe/x"):
    monkeypatch.setattr(
        "stripe.checkout.Session.create",
        lambda **kw: types.SimpleNamespace(url=url, id="cs_signup"),
    )


def test_public_plans_only_purchasable(client):
    pro_id = _setup_plans(client)
    plans = client.get("/public/plans").json()  # no auth
    names = [p["name"] for p in plans]
    assert "Pro" in names
    assert "Free" not in names  # no stripe_price_id -> hidden


def test_signup_starts_checkout_and_creates_incomplete_account(client, monkeypatch):
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    r = client.post("/signup", json={
        "company_name": "Acme", "email": "new@acme.it", "password": "password1", "plan_id": pro_id,
    })
    assert r.status_code == 200
    assert r.json()["checkout_url"] == "https://checkout.stripe/x"

    with Session(db.engine) as session:
        op = session.exec(select(db.Operator).where(db.Operator.email == "new@acme.it")).first()
        assert op is not None
        c = session.get(db.Client, op.client_id)
        assert c.billing_status == "incomplete"
        assert c.plan_id != pro_id  # on Free until the subscription activates


def test_signup_allows_login(client, monkeypatch):
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    client.post("/signup", json={
        "company_name": "Acme", "email": "log@acme.it", "password": "password1", "plan_id": pro_id,
    })
    r = client.post("/operator/login", json={"email": "log@acme.it", "password": "password1"})
    assert r.status_code == 200


def test_signup_duplicate_active_email_rejected(client, monkeypatch):
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    client.post("/signup", json={"company_name": "A", "email": "dup@acme.it", "password": "password1", "plan_id": pro_id})
    # mark that account active (as if payment completed)
    with Session(db.engine) as session:
        op = session.exec(select(db.Operator).where(db.Operator.email == "dup@acme.it")).first()
        c = session.get(db.Client, op.client_id)
        c.billing_status = "active"
        session.add(c)
        session.commit()
    r = client.post("/signup", json={"company_name": "A", "email": "dup@acme.it", "password": "password2", "plan_id": pro_id})
    assert r.status_code == 409


def test_subscription_created_activates_trial_and_plan(client, monkeypatch):
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    client.post("/signup", json={"company_name": "Acme", "email": "tri@acme.it", "password": "password1", "plan_id": pro_id})
    with Session(db.engine) as session:
        cid = session.exec(select(db.Operator).where(db.Operator.email == "tri@acme.it")).first().client_id

    event = {
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub_tri", "status": "trialing",
                            "metadata": {"client_id": str(cid), "plan_id": str(pro_id)}}},
    }
    monkeypatch.setattr("stripe.Webhook.construct_event", lambda payload, sig, secret: event)
    assert client.post("/billing/webhook", data="{}", headers={"stripe-signature": "x"}).status_code == 200

    with Session(db.engine) as session:
        c = session.get(db.Client, cid)
        assert c.billing_status == "trialing"
        assert c.plan_id == pro_id  # upgraded to the chosen plan

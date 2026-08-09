"""Self-serve signup tests. Stripe is monkeypatched; conftest sets dummy STRIPE_* env so
billing is enabled. A 'Free' plan is created first so it's the default (oldest) plan, matching
production where migration 0005 seeds it."""
import types

from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _setup_plans(client):
    """Seed the bootstrap plan + a purchasable Pro plan; returns Pro's id."""
    client.post("/admin/plans", headers=ADMIN, json={"name": "Base", "price_cents": 100})
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


def test_public_plans_are_sorted_by_price(client):
    client.post(
        "/admin/plans",
        headers=ADMIN,
        json={"name": "Business", "price_cents": 9900, "stripe_price_id": "price_business"},
    )
    client.post(
        "/admin/plans",
        headers=ADMIN,
        json={"name": "Starter", "price_cents": 1900, "stripe_price_id": "price_starter"},
    )
    client.post(
        "/admin/plans",
        headers=ADMIN,
        json={"name": "Pro", "price_cents": 4900, "stripe_price_id": "price_pro"},
    )

    plans = client.get("/public/plans").json()

    assert [plan["name"] for plan in plans] == ["Starter", "Pro", "Business"]


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
        assert c.plan_id != pro_id  # sul piano di partenza finché l'abbonamento non si attiva


def test_signup_uses_yearly_price(client, monkeypatch):
    client.post("/admin/plans", headers=ADMIN, json={"name": "Base", "price_cents": 100})
    annual = client.post(
        "/admin/plans",
        headers=ADMIN,
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
        return types.SimpleNamespace(url="https://checkout.stripe/year", id="cs_signup_year")

    monkeypatch.setattr("stripe.checkout.Session.create", create_checkout)
    response = client.post(
        "/signup",
        json={
            "company_name": "Annual Co",
            "email": "annual@example.test",
            "password": "password1",
            "plan_id": annual["id"],
            "billing_interval": "year",
        },
    )

    assert response.status_code == 200
    assert captured["line_items"][0]["price"] == "price_year"


def _verify_token(email, purpose="verify_email"):
    """Read the latest unused email token for an operator straight from the DB (in tests
    SMTP is unset, so the link is only logged — we fetch the raw token instead)."""
    with Session(db.engine) as session:
        op = session.exec(select(db.Operator).where(db.Operator.email == email)).first()
        row = session.exec(
            select(db.AuthToken)
            .where(db.AuthToken.operator_id == op.id, db.AuthToken.purpose == purpose,
                   db.AuthToken.used_at.is_(None))
            .order_by(db.AuthToken.id.desc())
        ).first()
        return row.token if row else None


def test_signup_blocks_login_until_verified_when_smtp_configured(client, monkeypatch):
    from app import main
    # email verification is only enforced when SMTP is actually configured
    monkeypatch.setattr(main.email_service, "enabled", lambda: True)
    monkeypatch.setattr(main.email_service, "send_verification", lambda to, token: True)
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    client.post("/signup", json={
        "company_name": "Acme", "email": "log@acme.it", "password": "password1", "plan_id": pro_id,
    })
    # unverified => login is refused
    r = client.post("/operator/login", json={"email": "log@acme.it", "password": "password1"})
    assert r.status_code == 403

    # confirm the email with the token issued at signup, then login succeeds
    token = _verify_token("log@acme.it")
    assert token
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    r = client.post("/operator/login", json={"email": "log@acme.it", "password": "password1"})
    assert r.status_code == 200


def test_signup_without_smtp_allows_immediate_login(client, monkeypatch):
    # default test env has no SMTP => the account is created already usable (no verification gate)
    pro_id = _setup_plans(client)
    _mock_checkout(monkeypatch)
    client.post("/signup", json={
        "company_name": "Acme", "email": "nosmtp@acme.it", "password": "password1", "plan_id": pro_id,
    })
    r = client.post("/operator/login", json={"email": "nosmtp@acme.it", "password": "password1"})
    assert r.status_code == 200


def test_verify_email_rejects_bad_token(client):
    assert client.post("/auth/verify-email", json={"token": "nope"}).status_code == 400


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

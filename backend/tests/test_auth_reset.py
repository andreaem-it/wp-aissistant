"""Password-reset flow. SMTP is unset in tests, so the reset link is only logged; we read
the token straight from the DB. /auth/forgot never reveals whether an email exists."""
from sqlmodel import Session, select

from app import db
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _make_operator(client, email="reset@acme.it", password="password1"):
    c = client.post("/admin/clients", headers=ADMIN, json={"name": "Acme", "allowed_origins": TENANT_ORIGIN}).json()
    client.post(f"/admin/clients/{c['id']}/operators", headers=ADMIN, json={"email": email, "password": password})
    return c


def _reset_token(email):
    with Session(db.engine) as session:
        op = session.exec(select(db.Operator).where(db.Operator.email == email)).first()
        row = session.exec(
            select(db.AuthToken)
            .where(db.AuthToken.operator_id == op.id, db.AuthToken.purpose == "reset",
                   db.AuthToken.used_at.is_(None))
            .order_by(db.AuthToken.id.desc())
        ).first()
        return row.token if row else None


def test_forgot_is_silent_for_unknown_email(client):
    r = client.post("/auth/forgot", json={"email": "ghost@nowhere.it"})
    assert r.status_code == 200  # no enumeration
    assert r.json() == {"ok": True}


def test_full_reset_flow(client):
    _make_operator(client)
    assert client.post("/auth/forgot", json={"email": "reset@acme.it"}).status_code == 200
    token = _reset_token("reset@acme.it")
    assert token

    # old password still logs in until reset completes
    assert client.post("/operator/login", json={"email": "reset@acme.it", "password": "password1"}).status_code == 200

    r = client.post("/auth/reset", json={"token": token, "new_password": "brandnew2"})
    assert r.status_code == 200

    # new password works, old one no longer
    assert client.post("/operator/login", json={"email": "reset@acme.it", "password": "brandnew2"}).status_code == 200
    assert client.post("/operator/login", json={"email": "reset@acme.it", "password": "password1"}).status_code == 401


def test_reset_token_is_single_use(client):
    _make_operator(client, email="once@acme.it")
    client.post("/auth/forgot", json={"email": "once@acme.it"})
    token = _reset_token("once@acme.it")
    assert client.post("/auth/reset", json={"token": token, "new_password": "brandnew2"}).status_code == 200
    # replay is rejected
    assert client.post("/auth/reset", json={"token": token, "new_password": "another33"}).status_code == 400


def test_reset_rejects_short_password(client):
    _make_operator(client, email="short@acme.it")
    client.post("/auth/forgot", json={"email": "short@acme.it"})
    token = _reset_token("short@acme.it")
    assert client.post("/auth/reset", json={"token": token, "new_password": "short"}).status_code == 400


def test_reset_revokes_active_sessions(client):
    _make_operator(client, email="sess@acme.it")
    login = client.post("/operator/login", json={"email": "sess@acme.it", "password": "password1"}).json()
    old_session = {"Authorization": f"Bearer {login['token']}"}
    # session works before reset
    assert client.get("/me", headers=old_session).status_code == 200

    client.post("/auth/forgot", json={"email": "sess@acme.it"})
    token = _reset_token("sess@acme.it")
    client.post("/auth/reset", json={"token": token, "new_password": "brandnew2"})

    # the pre-reset session is now dead
    assert client.get("/me", headers=old_session).status_code == 401

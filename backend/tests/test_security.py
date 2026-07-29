from app.security import _hash_password_legacy, hash_password, password_needs_rehash, verify_password


def test_verify_correct_password():
    h = hash_password("s3cret")
    assert verify_password("s3cret", h)


def test_reject_wrong_password():
    h = hash_password("s3cret")
    assert not verify_password("wrong", h)


def test_salt_differs_per_call():
    assert hash_password("s3cret") != hash_password("s3cret")


def test_malformed_hash_fails_closed():
    assert not verify_password("s3cret", "garbage")
    assert not verify_password("s3cret", "")


def test_stored_format():
    h = hash_password("pw")
    assert h.startswith("$argon2id$")
    assert not password_needs_rehash(h)


def test_legacy_pbkdf2_is_accepted_and_marked_for_upgrade():
    h = _hash_password_legacy("pw")
    assert verify_password("pw", h)
    assert not verify_password("wrong", h)
    assert password_needs_rehash(h)


def test_login_transparently_upgrades_legacy_hash(client, tenant):
    from sqlmodel import Session, select
    from app import db

    with Session(db.engine) as session:
        operator = session.exec(
            select(db.Operator).where(db.Operator.email == "op@acme.it")
        ).one()
        operator.password_hash = _hash_password_legacy("pw")
        session.add(operator)
        session.commit()

    response = client.post(
        "/operator/login",
        json={"email": "op@acme.it", "password": "pw"},
    )
    assert response.status_code == 200

    with Session(db.engine) as session:
        operator = session.exec(
            select(db.Operator).where(db.Operator.email == "op@acme.it")
        ).one()
        assert operator.password_hash.startswith("$argon2id$")

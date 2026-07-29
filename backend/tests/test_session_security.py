"""Operator sessions have an absolute lifetime and expired credentials are removed."""
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app import db
from app import main


def test_expired_operator_session_is_rejected_and_deleted(client, tenant):
    token = tenant["op"]["Authorization"].removeprefix("Bearer ")
    with Session(db.engine) as session:
        row = session.exec(
            select(db.OperatorSession).where(
                db.OperatorSession.token_hash == main._hash_session_token(token)
            )
        ).one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        session.add(row)
        session.commit()

    assert client.get("/me", headers=tenant["op"]).status_code == 401

    with Session(db.engine) as session:
        assert session.exec(
            select(db.OperatorSession).where(
                db.OperatorSession.token_hash == main._hash_session_token(token)
            )
        ).first() is None


def test_plaintext_operator_token_is_not_persisted(client, tenant):
    token = tenant["op"]["Authorization"].removeprefix("Bearer ")
    with Session(db.engine) as session:
        row = session.exec(
            select(db.OperatorSession).where(
                db.OperatorSession.token_hash == main._hash_session_token(token)
            )
        ).one()
        assert row.token is None
        assert row.token_hash != token

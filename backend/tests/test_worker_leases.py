"""Ingest jobs use leases and bounded retries across worker replicas."""
from datetime import datetime, timedelta

from sqlmodel import Session

from app import db, worker


def _job(tenant, **overrides):
    values = {
        "client_id": tenant["cid"],
        "kind": "site-page",
        "payload": "{}",
        **overrides,
    }
    return db.IngestJob(**values)


def test_claim_sets_owner_lease_and_attempt(client, tenant):
    with Session(db.engine) as session:
        job = _job(tenant)
        session.add(job)
        session.commit()
        claimed = worker._claim_next(session, worker_id="worker-a")
        assert claimed.id == job.id
        assert claimed.status == "processing"
        assert claimed.attempts == 1
        assert claimed.locked_by == "worker-a"
        assert claimed.locked_at is not None


def test_startup_does_not_requeue_active_lease(client, tenant):
    with Session(db.engine) as session:
        job = _job(
            tenant,
            status="processing",
            locked_at=datetime.utcnow(),
            locked_by="worker-live",
        )
        session.add(job)
        session.commit()
        assert worker.requeue_stale(session, lease_seconds=60) == 0
        session.refresh(job)
        assert job.status == "processing"


def test_startup_requeues_expired_lease(client, tenant):
    with Session(db.engine) as session:
        job = _job(
            tenant,
            status="processing",
            locked_at=datetime.utcnow() - timedelta(minutes=10),
            locked_by="worker-dead",
        )
        session.add(job)
        session.commit()
        assert worker.requeue_stale(session, lease_seconds=60) == 1
        session.refresh(job)
        assert job.status == "queued"
        assert job.locked_at is None
        assert job.locked_by == ""


def test_failure_retries_then_becomes_terminal(client, tenant):
    with Session(db.engine) as session:
        job = _job(tenant, status="processing", attempts=1, max_attempts=2)
        session.add(job)
        session.commit()
        session.refresh(job)

        assert worker._retry_or_fail(session, job.id, "temporary") == "queued"
        session.refresh(job)
        assert job.available_at > datetime.utcnow()

        job.status = "processing"
        job.attempts = 2
        session.add(job)
        session.commit()
        assert worker._retry_or_fail(session, job.id, "still broken") == "error"

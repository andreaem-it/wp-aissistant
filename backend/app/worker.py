"""Background ingest worker.

Endpoints enqueue IngestJob rows; this worker claims and processes them so the slow
chunking+embedding never blocks a request. Jobs are claimed with FOR UPDATE SKIP LOCKED,
so running several uvicorn workers (each with its own worker thread) is safe — a job is
processed exactly once. State lives in Postgres, so a crash mid-job is recoverable
(requeue_stale on startup).
"""

import json
import threading
from datetime import datetime

from sqlmodel import Session, select

from .db import Chunk, IngestJob, engine
from .rag import ingest, ingest_product

POLL_INTERVAL = 2.0  # seconds between polls when the queue is empty


def _process(session: Session, job: IngestJob) -> None:
    data = json.loads(job.payload)
    if job.kind == "document":
        ingest(session, job.client_id, "document", data["source_ref"], data["text"])
    elif job.kind == "site-page":
        # replace previous chunks for this URL so edits don't duplicate
        old = session.exec(
            select(Chunk).where(Chunk.client_id == job.client_id, Chunk.source_ref == data["url"])
        ).all()
        for chunk in old:
            session.delete(chunk)
        session.commit()
        ingest(session, job.client_id, "site", data["url"], data["text"])
    elif job.kind == "product":
        ingest_product(
            session, job.client_id, data["url"], data["title"],
            data["price"], data["image_url"], data["text"],
        )
    else:
        raise ValueError(f"unknown job kind: {job.kind}")


def _claim_next(session: Session) -> IngestJob | None:
    """Atomically pick the oldest queued job and mark it processing (SKIP LOCKED so
    concurrent workers don't grab the same row)."""
    job = session.exec(
        select(IngestJob)
        .where(IngestJob.status == "queued")
        .order_by(IngestJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if job:
        job.status = "processing"
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
    return job


def _mark(session: Session, job_id: int, status: str, error: str) -> None:
    job = session.get(IngestJob, job_id)
    if job:
        job.status = status
        job.error = error
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()


def requeue_stale(session: Session) -> int:
    """Return jobs stuck in 'processing' (from a crashed run) back to 'queued'. Run at startup."""
    stale = session.exec(select(IngestJob).where(IngestJob.status == "processing")).all()
    for job in stale:
        job.status = "queued"
        job.updated_at = datetime.utcnow()
        session.add(job)
    session.commit()
    return len(stale)


def run_worker(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with Session(engine) as session:
                job = _claim_next(session)
                if job is None:
                    stop.wait(POLL_INTERVAL)
                    continue
                job_id = job.id
                try:
                    _process(session, job)
                    _mark(session, job_id, "done", "")
                except Exception as exc:  # noqa: BLE001 — record failure, keep the worker alive
                    session.rollback()
                    _mark(session, job_id, "error", str(exc)[:500])
        except Exception:  # noqa: BLE001 — DB hiccup etc.; back off and retry
            stop.wait(POLL_INTERVAL)

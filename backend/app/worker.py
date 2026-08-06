"""Background ingest worker.

Endpoints enqueue IngestJob rows; this worker claims and processes them so the slow
chunking+embedding never blocks a request. Jobs are claimed with FOR UPDATE SKIP LOCKED,
so running several uvicorn workers (each with its own worker thread) is safe — a job is
processed exactly once. State lives in Postgres, so a crash mid-job is recoverable
(requeue_stale on startup).
"""

import json
import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import metrics, workflows
from .db import Chunk, Conversation, IngestJob, engine
from .logging_config import log
from .rag import ingest, ingest_product
from .tagging import classify_conversation

logger = logging.getLogger("wpai.worker")

POLL_INTERVAL = 2.0  # seconds between polls when the queue is empty
LEASE_SECONDS = int(os.getenv("INGEST_LEASE_SECONDS", "1800"))
MAX_ATTEMPTS = int(os.getenv("INGEST_MAX_ATTEMPTS", "3"))
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


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
    elif job.kind == "classify":
        # AI classification of a conversation. Best-effort by design: classify_conversation
        # swallows provider errors and returns None, so a failing classifier never sends the
        # job through the retry/error path meant for real ingest failures.
        conv = session.get(Conversation, data["conversation_id"])
        if conv and conv.client_id == job.client_id:
            classify_conversation(session, conv)
    else:
        raise ValueError(f"unknown job kind: {job.kind}")


def _claim_next(session: Session, worker_id: str = WORKER_ID) -> IngestJob | None:
    """Atomically pick the oldest queued job and mark it processing (SKIP LOCKED so
    concurrent workers don't grab the same row)."""
    job = session.exec(
        select(IngestJob)
        .where(
            IngestJob.status == "queued",
            IngestJob.available_at <= datetime.utcnow(),
        )
        .order_by(IngestJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if job:
        job.status = "processing"
        job.attempts += 1
        job.max_attempts = job.max_attempts or MAX_ATTEMPTS
        job.locked_at = datetime.utcnow()
        job.locked_by = worker_id
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
    return job


def _mark(session: Session, job_id: int, status: str, error: str) -> None:
    job = session.get(IngestJob, job_id)
    if job:
        job.status = status
        job.error = error
        job.locked_at = None
        job.locked_by = ""
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        metrics.ingest_jobs_total.labels(status=status).inc()


def _retry_or_fail(session: Session, job_id: int, error: str) -> str:
    """Retry transient failures with exponential backoff, then move to terminal error."""
    job = session.get(IngestJob, job_id)
    if not job:
        return "missing"
    job.error = error
    job.locked_at = None
    job.locked_by = ""
    if job.attempts < (job.max_attempts or MAX_ATTEMPTS):
        job.status = "queued"
        delay = min(2 ** max(job.attempts - 1, 0) * 5, 300)
        job.available_at = datetime.utcnow() + timedelta(seconds=delay)
    else:
        job.status = "error"
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    metrics.ingest_jobs_total.labels(status=job.status).inc()
    return job.status


def requeue_stale(session: Session, lease_seconds: int = LEASE_SECONDS) -> int:
    """Requeue only abandoned leases, never every currently processing job at startup."""
    cutoff = datetime.utcnow() - timedelta(seconds=lease_seconds)
    stale = session.exec(
        select(IngestJob).where(
            IngestJob.status == "processing",
            (IngestJob.locked_at.is_(None)) | (IngestJob.locked_at < cutoff),
        )
    ).all()
    for job in stale:
        job.status = "queued"
        job.locked_at = None
        job.locked_by = ""
        job.available_at = datetime.utcnow()
        job.updated_at = datetime.utcnow()
        session.add(job)
    session.commit()
    return len(stale)


def run_worker(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            with Session(engine) as session:
                workflows.dispatch_scheduled(session)
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
                    final_status = _retry_or_fail(session, job_id, str(exc)[:500])
                    log(logger, logging.ERROR, "ingest.job_failed", job_id=job_id, kind=job.kind, client_id=job.client_id, error=str(exc)[:500])
        except Exception:  # noqa: BLE001 — DB hiccup etc.; back off and retry
            stop.wait(POLL_INTERVAL)


def enqueue(session: "Session", client_id: int, kind: str, payload: dict) -> "IngestJob":
    """Put one ingest job on the queue. Lives with the worker that drains it, so the shape of a
    job is defined in one place."""
    job = IngestJob(
        client_id=client_id,
        kind=kind,
        payload=json.dumps(payload),
        max_attempts=int(os.getenv("INGEST_MAX_ATTEMPTS", "3")),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job

"""Shared pytest fixtures.

Unit tests (test_security, test_ratelimit, test_llm, test_chunking) need only the
installed deps — no database, no Ollama. Integration tests use FastAPI's TestClient
against a real Postgres+pgvector database and a mocked LLM; they are skipped unless
TEST_DATABASE_URL points at one, e.g.:

    createdb rag_test  # a database on the docker pgvector instance
    TEST_DATABASE_URL=postgresql+psycopg://rag:rag@localhost:5432/rag_test pytest
"""
import os

# Must be set before importing the app (module-level config reads env at import time).
os.environ.setdefault("ADMIN_API_KEY", "test-admin")
os.environ.setdefault("INGEST_WORKER_ENABLED", "false")  # drive the queue manually in tests
os.environ.setdefault("CORS_ALLOW_ALL", "true")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")  # Stripe calls are mocked in tests
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("METRICS_TOKEN", "metrics-test")  # /metrics is token-gated
os.environ.setdefault("SLA_MONITOR_ENABLED", "false")  # tests call check_sla_breaches directly
os.environ.setdefault("AI_CLASSIFY_ENABLED", "false")  # no LLM call behind an escalation in tests
os.environ.setdefault("WEBHOOK_DISPATCHER_ENABLED", "false")  # tests call dispatch_pending directly
os.environ.setdefault("WEBHOOK_ALLOW_PRIVATE", "true")  # test endpoints are not public hosts

_TEST_DB = os.environ.get("TEST_DATABASE_URL")
if _TEST_DB:
    os.environ["DATABASE_URL"] = _TEST_DB

import pytest


@pytest.fixture
def client(monkeypatch):
    """A TestClient with a fresh schema and a faked LLM. Skips without TEST_DATABASE_URL."""
    if not _TEST_DB:
        pytest.skip("set TEST_DATABASE_URL (Postgres+pgvector) to run integration tests")

    from fastapi.testclient import TestClient
    from sqlmodel import SQLModel
    from app import db, main, rag
    from app.ratelimit import FixedWindowLimiter

    # The rate limiters are process-wide singletons (app/main.py module globals), and the
    # test DB is dropped+recreated per test so serial ids (incl. client.id, used in the
    # rate-limit key) restart at 1 — without a fresh limiter here, hits from an earlier
    # test's "client 1" would count against this test's unrelated "client 1" and cause
    # sporadic 429s across the suite.
    # chat/ingest limiters moved to app/deps.py when main.py was split; patch them where they
    # live now, or the limit stays shared across tests and produces sporadic 429s
    from app import deps
    monkeypatch.setattr(deps, "chat_limiter", FixedWindowLimiter(deps.chat_limiter.limit, 60))
    monkeypatch.setattr(deps, "ingest_limiter", FixedWindowLimiter(deps.ingest_limiter.limit, 60))
    monkeypatch.setattr(main, "auth_limiter", FixedWindowLimiter(main.auth_limiter.limit, 60))
    # api_limiter moved to the public API router when main.py was split; patch it where it
    # lives now, or the public API keeps a limiter shared across tests and 429s sporadically
    from app.routers import public_api
    monkeypatch.setattr(public_api, "api_limiter", FixedWindowLimiter(public_api.api_limiter.limit, 60))

    # no Ollama in tests: deterministic embeddings and a canned chat reply
    monkeypatch.setattr(rag, "embed", lambda text: [0.0] * db.EMBED_DIM)
    monkeypatch.setattr(main, "embed", lambda text: [0.0] * db.EMBED_DIM)  # used by /admin/reembed
    # the chat moved to the widget router when main.py was split: patch the LLM where it is called
    from app.routers import widget as widget_router
    monkeypatch.setattr(widget_router, "llm_chat", lambda system, history, message: {"reply": "ok"})

    def _fake_stream(system, history, message):
        # mirror the ("delta", ...)* then ("meta", ...) protocol of llm.chat_stream
        for tok in ["Ciao", ", come ", "posso ", "aiutarti?"]:
            yield ("delta", tok)
        yield ("meta", {"model": "test", "latency_ms": 1, "tokens_prompt": 0, "tokens_completion": 0})

    monkeypatch.setattr(widget_router, "llm_chat_stream", _fake_stream)

    try:
        with db.engine.connect() as conn:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            conn.commit()
        SQLModel.metadata.create_all(db.engine)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"test database not reachable: {exc}")

    with TestClient(main.app) as test_client:
        yield test_client

    SQLModel.metadata.drop_all(db.engine)


@pytest.fixture
def tenant(client):
    """Create a client + operator and return ready-made auth headers."""
    admin = {"Authorization": "Bearer test-admin"}
    c = client.post("/admin/clients", headers=admin, json={"name": "Acme"}).json()
    client.post(
        f"/admin/clients/{c['id']}/operators",
        headers=admin,
        json={"email": "op@acme.it", "password": "pw"},
    )
    token = client.post(
        "/operator/login", json={"email": "op@acme.it", "password": "pw"}
    ).json()["token"]
    return {
        "cid": c["id"],
        "api_key": c["api_key"],
        "key": {"Authorization": f"Bearer {c['api_key']}"},  # client (widget/plugin)
        "op": {"Authorization": f"Bearer {token}"},           # operator (panel)
    }


@pytest.fixture
def drain():
    """Process the ingest queue synchronously (the background worker is disabled in tests)."""
    def _drain():
        from sqlmodel import Session
        from app import db, worker

        with Session(db.engine) as session:
            while True:
                job = worker._claim_next(session)
                if job is None:
                    break
                try:
                    worker._process(session, job)
                    worker._mark(session, job.id, "done", "")
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    worker._mark(session, job.id, "error", str(exc)[:500])

    return _drain

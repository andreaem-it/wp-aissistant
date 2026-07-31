import os
from datetime import datetime, timedelta
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlmodel import SQLModel, Field, create_engine, Session, Column

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://rag:rag@localhost:5432/rag")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))  # 1024 = bge-m3 (Workers AI); 768 = nomic-embed-text

engine = create_engine(DATABASE_URL)


class Plan(SQLModel, table=True):
    """Billing plan: name, price (display only until Stripe is wired), and the per-plan
    rate limits it grants. stripe_price_id stays empty until a Stripe account exists —
    plans and gating work standalone; only checkout needs it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    price_cents: int = 0
    currency: str = "eur"
    chat_rate_limit: int = 30
    ingest_rate_limit: int = 60
    # monthly chat-message quota (visitor messages that reach the AI); 0 = unlimited.
    # Counted per calendar month; over quota the AI stops answering (see enforcement in /chat).
    monthly_message_limit: int = 0
    yearly_price_cents: int = 0
    stripe_price_id: str = ""
    stripe_yearly_price_id: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    api_key: str = Field(index=True, unique=True)
    # comma-separated widget origins allowed to use this client's key from a browser;
    # empty = not configured (no per-client origin enforcement for this client)
    allowed_origins: str = ""
    plan_id: int = Field(foreign_key="plan.id")
    # billing_status is kept in sync by the Stripe webhook (app/billing.py). Policy: on
    # "canceled" the client is downgraded to the Free plan (plan_id changes, so the per-plan
    # rate limits follow automatically); "past_due" keeps the paid plan as a grace period.
    billing_status: str = "active"  # active | trialing | past_due | canceled
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""


class Chunk(SQLModel, table=True):
    """One embedded piece of content, from an uploaded doc or a synced site page."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    source: str  # "document" | "site"
    source_ref: str  # filename or URL
    text: str
    embedding: list[float] = Field(sa_column=Column(Vector(EMBED_DIM)))


class Product(SQLModel, table=True):
    """Structured WooCommerce product, kept separate from Chunk so the widget can render a card."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    product_url: str = Field(index=True)
    title: str
    price: str = ""
    image_url: str = ""
    embedding: list[float] = Field(sa_column=Column(Vector(EMBED_DIM)))


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    visitor_id: str
    # SHA-256 digest of the opaque token issued to the visitor when the conversation is
    # created. The public widget api_key identifies only the tenant; this token proves that
    # the browser owns this specific conversation.
    access_token_hash: str = Field(default="", index=True)
    # optional: the visitor can leave an email (on escalation) to be notified when an operator
    # replies; visitor_url is the page they chatted from, used as the link back in that email.
    visitor_email: Optional[str] = None
    visitor_url: Optional[str] = None
    # operator-filled structured info for this conversation, keyed by InfoField.key. JSON dict.
    info: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # updated_at is touched on every new message / status change; closed_at is stamped when a
    # conversation is closed. Together they let the stats compute response times & durations.
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    status: str = "open"  # open | escalated | closed
    priority: str = Field(default="normal", index=True)  # low | normal | high | urgent
    assigned_operator_id: Optional[int] = Field(default=None, foreign_key="operator.id", index=True)
    department_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    # ---- SLA tracking ----
    # The clock starts when the conversation actually needs a human (escalation), not when the
    # visitor opens the chat: the AI answers instantly, so an SLA on every conversation would be
    # meaningless. sla_policy_id records which policy matched at that moment; the due/warn stamps
    # are denormalized so the inbox can filter by SLA state directly in SQL.
    sla_policy_id: Optional[int] = Field(default=None, foreign_key="slapolicy.id", index=True)
    sla_started_at: Optional[datetime] = Field(default=None, index=True)
    first_response_at: Optional[datetime] = None  # first operator message on this conversation
    first_response_due_at: Optional[datetime] = Field(default=None, index=True)
    first_response_warn_at: Optional[datetime] = None
    resolution_due_at: Optional[datetime] = Field(default=None, index=True)
    resolution_warn_at: Optional[datetime] = None
    # set once the breach alert has been sent, so the monitor notifies at most once per target
    first_response_breach_notified: bool = False
    resolution_breach_notified: bool = False
    # ---- AI classification (advisory: it never changes status, priority or routing) ----
    ai_intent: str = ""
    ai_topic: str = ""
    ai_urgency: str = ""  # bassa | media | alta
    ai_classified_at: Optional[datetime] = None


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    role: str  # user | assistant | operator
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # visitor rating on an assistant message: 1 = 👍, -1 = 👎, None = no vote. Feeds quality stats.
    feedback: Optional[int] = None


class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    reason: str
    status: str = "open"  # open | answered | closed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)  # touched on status change/reply


class AiResponseLog(SQLModel, table=True):
    """Per-turn AI diagnostics: what was retrieved (chunk refs + cosine distances + which the
    reranker selected), which model answered, how long it took, token usage, and the outcome.
    One row per /chat turn. Powers the admin debug view ("why did it answer this way?") and the
    latency/quality stats. `retrieved` is a JSON list of {chunk_id, source, source_ref,
    distance, selected}."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    message_id: Optional[int] = Field(default=None, foreign_key="message.id")
    outcome: str  # answered | escalated_keyword | escalated_model | escalated_llm_down
    model: str = ""
    latency_ms: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    retrieved: str = ""  # JSON
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    """Append-only record of privileged actions (admin onboarding + operator actions) so the
    superadmin can see who did what, when. `detail` is action-specific JSON."""
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_type: str = Field(index=True)  # admin | operator | system
    actor_id: str = ""  # operator email/id, or "admin" for the shared admin key
    action: str = Field(index=True)  # e.g. client.create, client.rotate_key, ticket.reply
    target: str = ""  # affected entity, e.g. "client:12"
    client_id: Optional[int] = Field(default=None, index=True)  # tenant scope when applicable
    detail: str = ""  # JSON
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CannedResponse(SQLModel, table=True):
    """A per-client saved reply the operator can insert with one click. `body` may contain
    {placeholder} tokens matching InfoField.key, substituted from the conversation's info."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    title: str  # short label shown on the button
    body: str
    position: int = 0


class InfoField(SQLModel, table=True):
    """Per-client definition of a structured info field shown on each conversation
    (e.g. label 'Nome cliente', key 'nome_cliente'). Values live in Conversation.info."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    label: str
    key: str  # slug used both to store the value and as {key} placeholder in canned responses
    position: int = 0


class Department(SQLModel, table=True):
    """Tenant-scoped support queue used for routing and inbox filtering."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DepartmentMember(SQLModel, table=True):
    """Operator ↔ department membership. Round-robin routing picks only among the members of
    the conversation's department; without members the department has no pool and the
    conversation stays in the unassigned queue."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    department_id: int = Field(index=True, foreign_key="department.id")
    operator_id: int = Field(index=True, foreign_key="operator.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SlaPolicy(SQLModel, table=True):
    """Tenant-scoped SLA rule. `department_id=None` matches any department and `priority=""`
    matches any priority, so a tenant can keep one generic policy and override it for the
    queues that need tighter targets. The most specific active policy wins (see
    _match_sla_policy in main.py). Minutes at 0 disable that target."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    department_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    priority: str = ""  # "" = any | low | normal | high | urgent
    first_response_minutes: int = 60
    resolution_minutes: int = 480
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApiKey(SQLModel, table=True):
    """Scoped credential for the public API (`/v1/…`), separate from the widget `Client.api_key`:
    that one is public by design and identifies only the tenant, this one authorizes server-side
    calls and can be scoped and revoked. Only the SHA-256 digest is stored; `prefix` is the
    non-secret part shown in the panel so a key can be recognised without revealing it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str = ""
    prefix: str = Field(index=True, unique=True)
    token_hash: str = Field(index=True, unique=True)
    scopes: str = ""  # comma-separated, see API_SCOPES in main.py
    created_by: str = ""  # operator email, for the audit trail
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookEndpoint(SQLModel, table=True):
    """A tenant-configured HTTPS destination for events. `secret` signs the payload so the
    receiver can verify the call really came from us (HMAC-SHA256, see app/webhooks.py)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    url: str
    secret: str
    events: str = ""  # comma-separated; empty = every event
    description: str = ""
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WebhookDelivery(SQLModel, table=True):
    """One attempt log per (event, endpoint). Rows are the delivery log the tenant can inspect
    and the retry queue at the same time: a failed delivery keeps its payload and comes back at
    next_attempt_at until it succeeds or runs out of attempts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    endpoint_id: int = Field(index=True, foreign_key="webhookendpoint.id")
    event: str = Field(index=True)
    payload: str  # JSON
    status: str = Field(default="pending", index=True)  # pending | success | failed
    attempts: int = 0
    max_attempts: int = 5
    response_status: int = 0
    error: str = ""
    next_attempt_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    delivered_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationRating(SQLModel, table=True):
    """CSAT: the visitor's rating of the whole conversation (1–5 + optional comment), distinct
    from Message.feedback which judges a single AI answer. `resolved_by`, `operator_id` and
    `department_id` are frozen when the rating is left, so a later re-assignment can't rewrite
    history in the reports. One rating per conversation: a second submission updates it."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    conversation_id: int = Field(index=True, unique=True, foreign_key="conversation.id")
    score: int  # 1..5
    comment: str = ""
    resolved_by: str = "ai"  # ai | operator — who actually answered the visitor
    operator_id: Optional[int] = Field(default=None, foreign_key="operator.id", index=True)
    department_id: Optional[int] = Field(default=None, foreign_key="department.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Tag(SQLModel, table=True):
    """Tenant-scoped label for conversations. `source` records whether a human created it or
    the AI classifier did, so the two can be told apart in reports and filters."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    color: str = ""  # optional hex, e.g. "#5b4fe8"
    source: str = "manual"  # manual | ai
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationTag(SQLModel, table=True):
    """Many-to-many between conversations and tags (a conversation can carry several)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    tag_id: int = Field(index=True, foreign_key="tag.id")
    source: str = "manual"  # manual | ai
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InternalNote(SQLModel, table=True):
    """An operator-only note on a conversation. Deliberately NOT a Message: the widget reads
    messages, so anything internal must live in a table the visitor endpoints never touch."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    operator_id: int = Field(index=True, foreign_key="operator.id")
    body: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NoteMention(SQLModel, table=True):
    """An operator mentioned in a note (`@nome`). Stored as rows rather than JSON so the panel
    can query "my unread mentions" cheaply."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    note_id: int = Field(index=True, foreign_key="internalnote.id")
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    operator_id: int = Field(index=True, foreign_key="operator.id")
    read_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SavedView(SQLModel, table=True):
    """A saved inbox filter. Belongs to the operator who created it; `shared=True` makes it
    visible to the whole tenant (still editable only by its owner). `filters` is a JSON dict of
    the validated inbox filters, `sort` the ordering applied on top of them."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    operator_id: int = Field(index=True, foreign_key="operator.id")
    name: str
    shared: bool = False
    filters: str = "{}"  # JSON
    sort: str = "recent"  # recent | oldest | priority | sla
    position: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RoutingSetting(SQLModel, table=True):
    """Per-tenant auto-routing configuration, applied when a conversation escalates.
    mode=off leaves everything manual; mode=round_robin assigns the next operator in the
    pool. last_operator_id is the round-robin cursor. fallback_department_id is the queue a
    conversation lands in when it has no department yet."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, unique=True, foreign_key="client.id")
    mode: str = "off"  # off | round_robin
    fallback_department_id: Optional[int] = Field(default=None, foreign_key="department.id")
    last_operator_id: Optional[int] = Field(default=None, foreign_key="operator.id")
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Operator(SQLModel, table=True):
    """A human agent who logs into the panel. Belongs to one client (tenant)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    email: str = Field(index=True, unique=True)
    password_hash: str
    # display name shown to visitors (e.g. in the "… sta scrivendo" indicator); falls back to email
    name: str = ""
    # self-serve signups must confirm their email before they can log in; admin-provisioned
    # operators are created already verified (see create_operator). Migration 0006 backfills
    # every pre-existing operator to True so nobody gets locked out on upgrade.
    email_verified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuthToken(SQLModel, table=True):
    """Short-lived, single-use opaque token for email flows (password reset, email
    verification). purpose distinguishes the flow; used_at is stamped once consumed so a
    token can't be replayed. Expired/used tokens are simply rejected (no cleanup job needed
    for the volumes involved; a periodic prune can be added later)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    operator_id: int = Field(index=True, foreign_key="operator.id")
    purpose: str = Field(index=True)  # reset | verify_email
    token: str = Field(index=True, unique=True)
    expires_at: datetime
    used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OperatorSession(SQLModel, table=True):
    """Operator bearer session. Only a SHA-256 digest is stored for newly issued tokens.

    `token` is a nullable legacy column kept during the rolling migration so sessions issued
    by the previous release remain valid once and are upgraded on first use.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    operator_id: int = Field(index=True, foreign_key="operator.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    token: Optional[str] = Field(default=None, index=True, unique=True)
    token_hash: str = Field(default="", index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=30))


class IngestJob(SQLModel, table=True):
    """Queued ingest work. Endpoints enqueue a job and return immediately; a background
    worker does the slow chunking+embedding. payload is JSON, shape depends on kind."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    kind: str  # document | site-page | product
    status: str = Field(default="queued", index=True)  # queued | processing | done | error
    payload: str  # JSON
    error: str = ""
    attempts: int = 0
    max_attempts: int = 3
    available_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    locked_at: Optional[datetime] = Field(default=None, index=True)
    locked_by: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


def init_db():
    """Ensure the pgvector extension exists. Schema is managed by Alembic
    (`alembic upgrade head`); set DB_AUTO_CREATE=true only for a quick dev spin-up
    to create tables directly from the models instead of running migrations."""
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    if os.getenv("DB_AUTO_CREATE", "false").lower() == "true":
        SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session

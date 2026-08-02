import os
from datetime import datetime, timedelta
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import UniqueConstraint
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


class Contact(SQLModel, table=True):
    """A tenant-scoped person/address shared by conversations across every channel.

    `external_id` is channel-specific: browser visitor id for web, normalized address for
    email, provider user id for messaging channels. It is never globally unique.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    channel: str = Field(default="web", index=True)  # web | email | whatsapp | messenger | instagram
    external_id: str = Field(index=True)
    email: Optional[str] = Field(default=None, index=True)
    name: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("client_id", "channel", "external_id", name="uq_contact_tenant_channel_external"),
    )


class WhatsAppConsent(SQLModel, table=True):
    """Auditable WhatsApp opt-in state, separate from the contact identity itself."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    contact_id: int = Field(index=True, foreign_key="contact.id")
    granted: bool = False
    source: str = ""
    granted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("client_id", "contact_id", name="uq_whatsapp_consent_tenant_contact"),
    )


class PushSubscription(SQLModel, table=True):
    """One browser push subscription owned by one tenant-scoped operator."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    operator_id: int = Field(index=True, foreign_key="operator.id")
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    escalations: bool = True
    assignments: bool = True
    mentions: bool = True
    sla_breaches: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    visitor_id: str
    # Unified channel identity. Legacy web fields stay populated for widget compatibility.
    channel: str = Field(default="web", index=True)
    contact_id: Optional[int] = Field(default=None, foreign_key="contact.id", index=True)
    external_thread_id: str = Field(default="", index=True)
    channel_subject: str = ""
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
    # language the visitor writes in (see app/language.py); the assistant answers in it even
    # when the knowledge base is in another language
    language: str = Field(default="it", index=True)
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
    # Provider message id for idempotent channel webhooks. Web/widget messages keep it null.
    external_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # visitor rating on an assistant message: 1 = 👍, -1 = 👎, None = no vote. Feeds quality stats.
    feedback: Optional[int] = None
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "external_id", name="uq_message_conversation_external_id"
        ),
    )


class Attachment(SQLModel, table=True):
    """Private object metadata; bytes live in R2 and are never exposed through public URLs."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    message_id: int = Field(index=True, foreign_key="message.id")
    object_key: str = Field(unique=True)
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


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


class KnowledgeGapReview(SQLModel, table=True):
    """An operator's decision about a detected knowledge gap.

    The gaps themselves are derived from the AI logs at query time — deriving beats storing,
    because the answer changes as the knowledge base grows. What must persist is the human
    decision: this question was answered (taught) or isn't worth answering (ignored), so it
    stops coming back in the list. `question_hash` is the normalised question, so the same
    question asked with different spacing or casing is the same row."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    question_hash: str = Field(index=True)
    question: str = ""
    status: str = "taught"  # taught | ignored
    operator_email: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LeadForm(SQLModel, table=True):
    """A short form the widget can show to qualify a visitor. `fields` is a JSON list of
    {key,label,type,required,points}: the points are what makes the score explainable — it is
    the sum of the points of the fields the visitor actually filled, not a black box."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    trigger: str = "escalation"  # escalation | chat_start
    fields: str = "[]"  # JSON
    intro: str = ""
    consent_text: str = ""  # shown next to the checkbox; empty = no consent required
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Lead(SQLModel, table=True):
    """A captured lead. `consent_text` is snapshotted from the form so we can always show what
    the visitor actually agreed to, even after the form is edited."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    form_id: Optional[int] = Field(default=None, foreign_key="leadform.id", index=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id", index=True)
    data: str = "{}"  # JSON of the submitted values
    score: int = 0
    consent: bool = False
    consent_text: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class CrmConnection(SQLModel, table=True):
    """Tenant CRM mapping. Provider credentials live in the external adapter, never here."""
    __table_args__ = (UniqueConstraint("client_id", "provider"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    provider: str = Field(index=True)
    external_account_id: str = ""
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CrmSync(SQLModel, table=True):
    """Latest delivery outcome for a lead and CRM connection; one row makes retries idempotent."""
    __table_args__ = (UniqueConstraint("connection_id", "lead_id"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    connection_id: int = Field(index=True, foreign_key="crmconnection.id")
    lead_id: int = Field(index=True, foreign_key="lead.id")
    status: str = "pending"  # pending | delivered | failed
    external_id: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProactiveRule(SQLModel, table=True):
    """A contextual message the widget offers before the visitor asks anything.

    The rules are evaluated in the browser (no round-trip per page view), so this row is
    public-by-design content: it must never carry anything internal. `impressions` and
    `engagements` are the only feedback loop we get on whether a rule is worth keeping."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    trigger_type: str = "time_on_page"  # url | time_on_page | exit_intent | cart
    url_pattern: str = ""  # substring of the page URL; empty = any page
    delay_seconds: int = 15
    message: str = ""
    frequency: str = "once_per_day"  # once_per_session | once_per_day | always
    active: bool = True
    position: int = 0
    impressions: int = 0
    engagements: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Workflow(SQLModel, table=True):
    """A tenant automation: when `trigger` fires, if every condition matches, run the actions.
    `conditions` and `actions` are JSON lists validated against a closed vocabulary (see
    app/workflows.py) — a rule that can't be understood is refused at save time, never
    half-applied at run time."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    name: str
    trigger: str = Field(index=True)
    conditions: str = "[]"  # JSON list of {field, op, value}, ANDed
    actions: str = "[]"  # JSON list of {type, ...params}, applied in order
    active: bool = True
    position: int = 0
    run_count: int = 0
    last_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowRun(SQLModel, table=True):
    """One evaluation of a workflow. Non-matching evaluations are recorded too: "why didn't my
    automation fire?" is the first question an operator asks."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    workflow_id: int = Field(index=True, foreign_key="workflow.id")
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id", index=True)
    event: str
    matched: bool = False
    applied: str = "[]"  # JSON list of the actions actually applied
    error: str = ""
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

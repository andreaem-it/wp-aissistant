import os
import secrets

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from .db import Chunk, Client, Conversation, Message, Ticket, get_session, init_db
from .llm import chat as llm_chat
from .rag import extract_text, ingest, ingest_product, retrieve, retrieve_products
from .ratelimit import FixedWindowLimiter

app = FastAPI(title="wp-aissistant backend")

# admin token for client onboarding endpoints; unset => the /admin surface is disabled (fail closed)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")

# /chat hits the LLM on every call, so it's the main abuse/cost surface — limit per client+IP.
# Ingest is limited per client. Windows are 60s; override the counts via env.
chat_limiter = FixedWindowLimiter(int(os.getenv("CHAT_RATE_LIMIT", "30")), 60)
ingest_limiter = FixedWindowLimiter(int(os.getenv("INGEST_RATE_LIMIT", "60")), 60)

# ponytail: deterministic safety net for categories that must always reach a human —
# small local LLMs don't reliably follow "always escalate refunds" instructions
ALWAYS_ESCALATE_KEYWORDS = [
    "rimborso", "refund", "reclamo", "complaint", "denuncia",
    "cambio password account", "eliminare il mio account", "delete my account",
]

# ponytail: wide open for now (the chat widget runs on arbitrary client sites and
# the api_key is the real auth boundary); tighten to a per-client allowed origin if abused
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


def get_client(api_key: str, session: Session) -> Client:
    client = session.exec(select(Client).where(Client.api_key == api_key)).first()
    if not client:
        raise HTTPException(401, "invalid api key")
    return client


def require_client(
    authorization: str = Header(None),
    session: Session = Depends(get_session),
) -> Client:
    """Auth dependency: reads the client api_key from the `Authorization: Bearer <key>`
    header instead of a query param, so keys don't leak into server/proxy access logs.
    FastAPI caches get_session within a request, so the endpoint shares this session."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return get_client(authorization[7:].strip(), session)


def require_admin(authorization: str = Header(None)) -> None:
    """Gates the client-onboarding endpoints behind the ADMIN_API_KEY env var.
    Fails closed: if no admin key is configured the whole /admin surface is disabled."""
    if not ADMIN_API_KEY:
        raise HTTPException(503, "admin api not configured")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    if not secrets.compare_digest(authorization[7:].strip(), ADMIN_API_KEY):
        raise HTTPException(401, "invalid admin key")


def rate_limit_chat(request: Request, client: Client = Depends(require_client)) -> Client:
    ip = request.client.host if request.client else "unknown"
    chat_limiter.check(f"chat:{client.id}:{ip}")
    return client


def rate_limit_ingest(client: Client = Depends(require_client)) -> Client:
    ingest_limiter.check(f"ingest:{client.id}")
    return client


@app.post("/ingest/document")
async def ingest_document(file: UploadFile, client: Client = Depends(rate_limit_ingest), session: Session = Depends(get_session)):
    data = await file.read()
    text = extract_text(file.filename, data)
    ingest(session, client.id, "document", file.filename, text)
    return {"ok": True, "chars": len(text)}


@app.post("/ingest/site-page")
def ingest_site_page(url: str = Body(...), text: str = Body(...), client: Client = Depends(rate_limit_ingest), session: Session = Depends(get_session)):
    """Called by the WP plugin on publish/update to push page/product content."""
    # replace previous chunks for this URL so edits don't duplicate
    old = session.exec(select(Chunk).where(Chunk.client_id == client.id, Chunk.source_ref == url)).all()
    for c in old:
        session.delete(c)
    session.commit()
    ingest(session, client.id, "site", url, text)
    return {"ok": True}


@app.post("/ingest/product")
def ingest_product_endpoint(
    url: str = Body(...),
    title: str = Body(...),
    price: str = Body(""),
    image_url: str = Body(""),
    description: str = Body(""),
    client: Client = Depends(rate_limit_ingest),
    session: Session = Depends(get_session),
):
    """Called by the WP plugin for WooCommerce products, in addition to /ingest/site-page."""
    text = f"{title}\n{description}\nPrezzo: {price}" if price else f"{title}\n{description}"
    ingest_product(session, client.id, url, title, price, image_url, text)
    return {"ok": True}


@app.post("/chat")
def chat_endpoint(
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    client: Client = Depends(rate_limit_chat),
    session: Session = Depends(get_session),
):
    if conversation_id:
        conv = session.get(Conversation, conversation_id)
        if not conv or conv.client_id != client.id:
            raise HTTPException(404, "conversation not found")
    else:
        conv = Conversation(client_id=client.id, visitor_id=visitor_id)
        session.add(conv)
        session.commit()
        session.refresh(conv)

    history = [
        {"role": m.role if m.role != "operator" else "assistant", "content": m.content}
        for m in session.exec(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    ]
    session.add(Message(conversation_id=conv.id, role="user", content=message))
    session.commit()

    if conv.status == "escalated":
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    lowered = message.lower()
    keyword_hit = next((k for k in ALWAYS_ESCALATE_KEYWORDS if k in lowered), None)
    if keyword_hit:
        conv.status = "escalated"
        session.add(conv)
        session.add(Ticket(conversation_id=conv.id, reason=f"richiede intervento umano ({keyword_hit})"))
        session.commit()
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    context = retrieve(session, client.id, message)
    system = (
        "You are a customer support assistant. Handle greetings and small talk yourself, "
        "normally, without calling any tool. For substantive questions, answer only using "
        "the context below. Call escalate_to_human ONLY when: the answer to a substantive "
        "question isn't in the context, or the request needs human authority (refunds, "
        "complaints, account changes). Do not escalate greetings or vague messages — ask "
        "the user to clarify instead.\n\nContext:\n" + "\n---\n".join(context)
    )
    result = llm_chat(system, history, message)

    if "escalate" in result:
        conv.status = "escalated"
        session.add(conv)
        session.add(Ticket(conversation_id=conv.id, reason=result["escalate"]))
        session.commit()
        return {"conversation_id": conv.id, "status": "escalated", "reply": None}

    session.add(Message(conversation_id=conv.id, role="assistant", content=result["reply"]))
    session.commit()
    products = retrieve_products(session, client.id, message)
    return {"conversation_id": conv.id, "status": "open", "reply": result["reply"], "products": products}


@app.get("/conversations/{conversation_id}/messages")
def conversation_messages(conversation_id: int, after_id: int = 0, client: Client = Depends(require_client), session: Session = Depends(get_session)):
    """Polled by the chat widget to pick up operator replies while a conversation is escalated."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation_id, Message.id > after_id).order_by(Message.id)
    ).all()
    return {"status": conv.status, "messages": [{"id": m.id, "role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations")
def list_conversations(client: Client = Depends(require_client), session: Session = Depends(get_session)):
    convs = session.exec(
        select(Conversation).where(Conversation.client_id == client.id).order_by(Conversation.created_at.desc())
    ).all()
    result = []
    for c in convs:
        last = session.exec(
            select(Message).where(Message.conversation_id == c.id).order_by(Message.id.desc())
        ).first()
        result.append({"conversation": c, "last_message": last.content if last else None})
    return result


@app.get("/tickets")
def list_tickets(status: str = "open", client: Client = Depends(require_client), session: Session = Depends(get_session)):
    tickets = session.exec(
        select(Ticket, Conversation)
        .join(Conversation, Ticket.conversation_id == Conversation.id)
        .where(Conversation.client_id == client.id, Ticket.status == status)
    ).all()
    return [{"ticket": t, "conversation": c} for t, c in tickets]


@app.post("/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, reply: str, client: Client = Depends(require_client), session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    conv = session.get(Conversation, ticket.conversation_id) if ticket else None
    # verify the ticket belongs to this client before letting anyone reply as the operator
    if not ticket or not conv or conv.client_id != client.id:
        raise HTTPException(404, "ticket not found")
    session.add(Message(conversation_id=ticket.conversation_id, role="operator", content=reply))
    ticket.status = "answered"
    conv.status = "open"
    session.add(ticket)
    session.add(conv)
    session.commit()
    return {"ok": True}


@app.get("/stats")
def stats(client: Client = Depends(require_client), session: Session = Depends(get_session)):
    convs = session.exec(select(Conversation).where(Conversation.client_id == client.id)).all()
    return {
        "total_conversations": len(convs),
        "escalated": sum(1 for c in convs if c.status == "escalated"),
        "closed": sum(1 for c in convs if c.status == "closed"),
    }


# ---- Admin: client onboarding (guarded by ADMIN_API_KEY) ----


@app.post("/admin/clients", dependencies=[Depends(require_admin)])
def create_client(name: str = Body(..., embed=True), session: Session = Depends(get_session)):
    """Provision a new client and return its generated api_key. The key is shown only here —
    it's not stored in a recoverable form for listing, so capture it now."""
    client = Client(name=name, api_key=secrets.token_urlsafe(32))
    session.add(client)
    session.commit()
    session.refresh(client)
    return {"id": client.id, "name": client.name, "api_key": client.api_key}


@app.get("/admin/clients", dependencies=[Depends(require_admin)])
def list_clients(session: Session = Depends(get_session)):
    # deliberately omit api_key so a leaked admin listing doesn't hand out client keys
    return [{"id": c.id, "name": c.name} for c in session.exec(select(Client)).all()]


@app.post("/admin/clients/{client_id}/rotate-key", dependencies=[Depends(require_admin)])
def rotate_client_key(client_id: int, session: Session = Depends(get_session)):
    client = session.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    client.api_key = secrets.token_urlsafe(32)
    session.add(client)
    session.commit()
    return {"id": client.id, "name": client.name, "api_key": client.api_key}

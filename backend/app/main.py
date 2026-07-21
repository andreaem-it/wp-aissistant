from fastapi import Body, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from .db import Chunk, Client, Conversation, Message, Ticket, get_session, init_db
from .llm import chat as llm_chat
from .rag import extract_text, ingest, ingest_product, retrieve, retrieve_products

app = FastAPI(title="wp-aissistant backend")

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


@app.post("/ingest/document")
async def ingest_document(api_key: str, file: UploadFile, session: Session = Depends(get_session)):
    client = get_client(api_key, session)
    data = await file.read()
    text = extract_text(file.filename, data)
    ingest(session, client.id, "document", file.filename, text)
    return {"ok": True, "chars": len(text)}


@app.post("/ingest/site-page")
def ingest_site_page(api_key: str, url: str = Body(...), text: str = Body(...), session: Session = Depends(get_session)):
    """Called by the WP plugin on publish/update to push page/product content."""
    client = get_client(api_key, session)
    # replace previous chunks for this URL so edits don't duplicate
    old = session.exec(select(Chunk).where(Chunk.client_id == client.id, Chunk.source_ref == url)).all()
    for c in old:
        session.delete(c)
    session.commit()
    ingest(session, client.id, "site", url, text)
    return {"ok": True}


@app.post("/ingest/product")
def ingest_product_endpoint(
    api_key: str,
    url: str = Body(...),
    title: str = Body(...),
    price: str = Body(""),
    image_url: str = Body(""),
    description: str = Body(""),
    session: Session = Depends(get_session),
):
    """Called by the WP plugin for WooCommerce products, in addition to /ingest/site-page."""
    client = get_client(api_key, session)
    text = f"{title}\n{description}\nPrezzo: {price}" if price else f"{title}\n{description}"
    ingest_product(session, client.id, url, title, price, image_url, text)
    return {"ok": True}


@app.post("/chat")
def chat_endpoint(
    api_key: str,
    visitor_id: str = Body(...),
    message: str = Body(...),
    conversation_id: int | None = Body(None),
    session: Session = Depends(get_session),
):
    client = get_client(api_key, session)

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
def conversation_messages(conversation_id: int, api_key: str, after_id: int = 0, session: Session = Depends(get_session)):
    """Polled by the chat widget to pick up operator replies while a conversation is escalated."""
    client = get_client(api_key, session)
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != client.id:
        raise HTTPException(404, "conversation not found")
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation_id, Message.id > after_id).order_by(Message.id)
    ).all()
    return {"status": conv.status, "messages": [{"id": m.id, "role": m.role, "content": m.content} for m in messages]}


@app.get("/conversations")
def list_conversations(api_key: str, session: Session = Depends(get_session)):
    client = get_client(api_key, session)
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
def list_tickets(api_key: str, status: str = "open", session: Session = Depends(get_session)):
    client = get_client(api_key, session)
    tickets = session.exec(
        select(Ticket, Conversation)
        .join(Conversation, Ticket.conversation_id == Conversation.id)
        .where(Conversation.client_id == client.id, Ticket.status == status)
    ).all()
    return [{"ticket": t, "conversation": c} for t, c in tickets]


@app.post("/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, reply: str, session: Session = Depends(get_session)):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "ticket not found")
    session.add(Message(conversation_id=ticket.conversation_id, role="operator", content=reply))
    ticket.status = "answered"
    conv = session.get(Conversation, ticket.conversation_id)
    conv.status = "open"
    session.add(ticket)
    session.add(conv)
    session.commit()
    return {"ok": True}


@app.get("/stats")
def stats(api_key: str, session: Session = Depends(get_session)):
    client = get_client(api_key, session)
    convs = session.exec(select(Conversation).where(Conversation.client_id == client.id)).all()
    return {
        "total_conversations": len(convs),
        "escalated": sum(1 for c in convs if c.status == "escalated"),
        "closed": sum(1 for c in convs if c.status == "closed"),
    }

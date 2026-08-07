"""Inbound channels and conversation attachments.

Where a message that did not come from the web widget enters the product — email, WhatsApp,
Messenger/Instagram — and where the files exchanged in a conversation are stored and served.

Every adapter posts a **normalised** payload authenticated by a server-side key: provider
credentials and signature checks live in the Cloudflare workers, never here. Delivery is
deduplicated on the provider's own message id, so a webhook retry cannot double-post.

Fourth area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session, select

from .. import attachments as attachment_service
from .. import events
from .. import push as push_service
from .. import whatsapp as whatsapp_service
from ..conversations import (
    emit_visitor_message as _emit_visitor_message,
    get_or_create_contact as _get_or_create_contact,
    whatsapp_channel_status as _whatsapp_channel_status,
)
from ..db import (
    ApiKey, Attachment, Client, Contact, Conversation, Message, Operator, Ticket,
    WhatsAppConsent, get_session,
)
from ..deps import audit as _audit, require_channel_write_key, require_operator
from ..limits import MAX_CHAT_MESSAGE_CHARS
from ..logging_config import log
from ..notify import notify_new_ticket
from ..routing import apply_sla as _apply_sla, auto_assign as _auto_assign
from ..util import iso as _iso

logger = logging.getLogger("wpai")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

router = APIRouter()


def _safe_attachment_filename(filename: str | None) -> str:
    """Strip paths/control characters before storing or placing a name in a header."""
    clean = Path(filename or "allegato").name
    clean = re.sub(r"[\x00-\x1f\x7f\r\n\"\\]", "_", clean).strip(" .")
    return clean[:180] or "allegato"


def _attachment_payload(attachment: Attachment) -> dict:
    return {
        "id": attachment.id,
        "message_id": attachment.message_id,
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "created_at": _iso(attachment.created_at),
    }


def _decode_inbound_media(attachments) -> list[tuple[str, str, bytes]]:
    """Adapter payloads are validated whole: a bad attachment fails the call, it is not dropped."""
    try:
        return attachment_service.decode_inbound(attachments)
    except attachment_service.InboundMediaError as exc:
        raise HTTPException(exc.status, str(exc)) from None


def _store_inbound_media(
    session: Session, *, client_id: int, conv: Conversation, message: Message,
    media: list[tuple[str, str, bytes]],
) -> tuple[list[str], int, list[str]]:
    """Store media forwarded by a channel adapter as private attachments of `message`.

    Returns (stored names, failed count, object keys). A storage outage must never cost us the
    customer's message: the text is kept and the loss stays visible in the thread.
    """
    if not media:
        return [], 0, []
    if not attachment_service.configured():
        log(logger, logging.WARNING, "attachment.inbound_storage_missing", client_id=client_id, count=len(media))
        return [], len(media), []
    session.flush()  # the attachment rows need the message id
    names, failed, keys = [], 0, []
    for filename, content_type, data in media:
        safe = _safe_attachment_filename(filename)
        object_key = f"tenant/{client_id}/conversation/{conv.id}/{uuid.uuid4().hex}{Path(safe).suffix.lower()[:12]}"
        if not attachment_service.put(object_key, data, content_type):
            log(logger, logging.WARNING, "attachment.inbound_store_failed",
                client_id=client_id, conversation_id=conv.id, content_type=content_type)
            failed += 1
            continue
        keys.append(object_key)
        session.add(Attachment(
            client_id=client_id, conversation_id=conv.id, message_id=message.id,
            object_key=object_key, filename=safe, content_type=content_type, size_bytes=len(data),
        ))
        names.append(safe)
    return names, failed, keys


def _commit_with_media(session: Session, object_keys: list[str]) -> None:
    """Commit, removing the objects just stored if the transaction cannot be saved: private
    bytes must never outlive the row that owns them."""
    try:
        session.commit()
    except Exception:
        session.rollback()
        for key in object_keys:
            attachment_service.delete(key)
        raise


def _inbound_message_content(body: str, stored: list[str], failed: int) -> str:
    """What the operator reads in the thread: the text, the media names and any media lost."""
    parts = [body] if body else []
    if stored:
        parts.append(("Allegato: " if len(stored) == 1 else "Allegati: ") + ", ".join(stored))
    if failed:
        parts.append(f"[{failed} allegato non salvato]" if failed == 1 else f"[{failed} allegati non salvati]")
    return "\n".join(parts)[:MAX_CHAT_MESSAGE_CHARS]


@router.post("/channels/email/inbound")
def email_inbound(
    from_email: str = Body(...),
    subject: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    thread_id: str = Body(""),
    in_reply_to: str = Body(""),
    from_name: str = Body(""),
    attachments: list | None = Body(None),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Provider-neutral inbound email adapter.

    An email provider (or a tiny provider-specific adapter) posts normalized fields here using
    a server-side key scoped to channels:write. Provider message ids make retries idempotent;
    thread ids keep replies in the same inbox conversation. Attachments arrive as base64 bytes
    the adapter already fetched, so no provider credential ever reaches the backend.
    """
    address = (from_email or "").strip().lower()[:320]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    root_thread_id = (thread_id or in_reply_to or provider_message_id).strip()[:500]
    clean_subject = (subject or "").strip()[:500]
    media = _decode_inbound_media(attachments)
    if not address or not _EMAIL_RE.fullmatch(address):
        raise HTTPException(400, "valid from_email required")
    if not body and not media:
        raise HTTPException(400, "text or attachments required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")
    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "email",
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    thread_candidates = [value for value in {root_thread_id, (in_reply_to or "").strip()[:500]} if value]
    conv = None
    if thread_candidates:
        conv = session.exec(
            select(Conversation).where(
                Conversation.client_id == key.client_id,
                Conversation.channel == "email",
                Conversation.external_thread_id.in_(thread_candidates),
            )
        ).first()

    contact = _get_or_create_contact(
        session,
        key.client_id,
        "email",
        address,
        email=address,
        name=(from_name or "").strip()[:255],
    )
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"email:{address}",
            channel="email",
            contact_id=contact.id,
            external_thread_id=root_thread_id,
            channel_subject=clean_subject,
            visitor_email=address,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.contact_id = contact.id
        conv.visitor_email = address
        conv.channel_subject = clean_subject or conv.channel_subject
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    inbound_message = Message(
        conversation_id=conv.id,
        role="user",
        content=body,
        external_id=provider_message_id,
    )
    session.add(inbound_message)
    stored_media, failed_media, media_keys = _store_inbound_media(
        session, client_id=key.client_id, conv=conv, message=inbound_message, media=media,
    )
    inbound_message.content = _inbound_message_content(body, stored_media, failed_media)
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    if not open_ticket:
        open_ticket = Ticket(conversation_id=conv.id, reason=f"Email: {clean_subject or 'senza oggetto'}")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    _commit_with_media(session, media_keys)
    session.refresh(conv)
    session.refresh(inbound_message)
    _emit_visitor_message(session, conv, inbound_message)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title="Nuova email assegnata" if assignee else "Nuova email di supporto",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": "email",
            "channel": "email",
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@router.post("/channels/whatsapp/inbound")
def whatsapp_inbound(
    from_number: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    from_name: str = Body(""),
    consent: bool | None = Body(None),
    consent_source: str = Body(""),
    attachments: list | None = Body(None),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Accept a normalized inbound WhatsApp message from a provider adapter.

    Media is forwarded as base64 bytes the adapter already downloaded from the provider: the
    backend keeps no Meta token and resolves no remote media URL.
    """
    number = re.sub(r"[^0-9+]", "", (from_number or "").strip())[:32]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    media = _decode_inbound_media(attachments)
    if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
        raise HTTPException(400, "valid from_number required")
    if not body and not media:
        raise HTTPException(400, "text or attachments required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")
    clean_consent_source = (consent_source or "").strip()[:255]
    if consent is True and not clean_consent_source:
        raise HTTPException(400, "consent_source required when consent is granted")

    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "whatsapp",
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    contact = _get_or_create_contact(
        session, key.client_id, "whatsapp", number, name=(from_name or "").strip()[:255]
    )
    if consent is not None:
        consent_row = session.exec(
            select(WhatsAppConsent).where(
                WhatsAppConsent.client_id == key.client_id,
                WhatsAppConsent.contact_id == contact.id,
            )
        ).first()
        now_consent = datetime.utcnow()
        if consent_row is None:
            consent_row = WhatsAppConsent(client_id=key.client_id, contact_id=contact.id)
        consent_row.granted = consent
        consent_row.source = clean_consent_source or consent_row.source
        consent_row.granted_at = now_consent if consent else consent_row.granted_at
        consent_row.revoked_at = None if consent else now_consent
        consent_row.updated_at = now_consent
        session.add(consent_row)
    conv = session.exec(
        select(Conversation).where(
            Conversation.client_id == key.client_id,
            Conversation.channel == "whatsapp",
            Conversation.contact_id == contact.id,
            Conversation.status != "closed",
        ).order_by(Conversation.id.desc())
    ).first()
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"whatsapp:{number}",
            channel="whatsapp",
            contact_id=contact.id,
            external_thread_id=number,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    inbound_message = Message(
        conversation_id=conv.id, role="user", content=body, external_id=provider_message_id,
    )
    session.add(inbound_message)
    stored_media, failed_media, media_keys = _store_inbound_media(
        session, client_id=key.client_id, conv=conv, message=inbound_message, media=media,
    )
    inbound_message.content = _inbound_message_content(body, stored_media, failed_media)
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    if open_ticket is None:
        open_ticket = Ticket(conversation_id=conv.id, reason="Messaggio WhatsApp")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    _commit_with_media(session, media_keys)
    session.refresh(conv)
    session.refresh(inbound_message)
    _emit_visitor_message(session, conv, inbound_message)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title="Nuovo WhatsApp assegnato" if assignee else "Nuovo messaggio WhatsApp",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": "whatsapp",
            "channel": "whatsapp",
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@router.post("/channels/meta/inbound")
def meta_messaging_inbound(
    platform: str = Body(...),
    sender_id: str = Body(...),
    text: str = Body(...),
    message_id: str = Body(...),
    thread_id: str = Body(""),
    sender_name: str = Body(""),
    attachments: list | None = Body(None),
    key: ApiKey = Depends(require_channel_write_key),
    session: Session = Depends(get_session),
):
    """Normalized inbound adapter shared by Messenger and Instagram Direct.

    As on the other channels, media arrives as base64 bytes already fetched by the adapter.
    """
    clean_platform = (platform or "").strip().lower()
    external_sender = (sender_id or "").strip()[:255]
    body = (text or "").strip()[:MAX_CHAT_MESSAGE_CHARS]
    provider_message_id = (message_id or "").strip()[:500]
    provider_thread_id = (thread_id or external_sender).strip()[:500]
    media = _decode_inbound_media(attachments)
    if clean_platform not in {"messenger", "instagram"}:
        raise HTTPException(400, "platform must be messenger or instagram")
    if not external_sender or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", external_sender):
        raise HTTPException(400, "valid sender_id required")
    if not body and not media:
        raise HTTPException(400, "text or attachments required")
    if not provider_message_id:
        raise HTTPException(400, "message_id required")

    duplicate = session.exec(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.client_id == key.client_id,
            Conversation.channel == clean_platform,
            Message.external_id == provider_message_id,
        )
    ).first()
    if duplicate:
        return {"ok": True, "created": False, "conversation_id": duplicate.conversation_id}

    contact = _get_or_create_contact(
        session, key.client_id, clean_platform, external_sender,
        name=(sender_name or "").strip()[:255],
    )
    conv = session.exec(
        select(Conversation).where(
            Conversation.client_id == key.client_id,
            Conversation.channel == clean_platform,
            Conversation.external_thread_id == provider_thread_id,
            Conversation.status != "closed",
        ).order_by(Conversation.id.desc())
    ).first()
    now = datetime.utcnow()
    if conv is None:
        conv = Conversation(
            client_id=key.client_id,
            visitor_id=f"{clean_platform}:{external_sender}",
            channel=clean_platform,
            contact_id=contact.id,
            external_thread_id=provider_thread_id,
            status="escalated",
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
        session.flush()
    else:
        conv.contact_id = contact.id
        conv.status = "escalated"
        conv.closed_at = None
        conv.updated_at = now
        session.add(conv)

    inbound_message = Message(
        conversation_id=conv.id, role="user", content=body, external_id=provider_message_id,
    )
    session.add(inbound_message)
    stored_media, failed_media, media_keys = _store_inbound_media(
        session, client_id=key.client_id, conv=conv, message=inbound_message, media=media,
    )
    inbound_message.content = _inbound_message_content(body, stored_media, failed_media)
    open_ticket = session.exec(
        select(Ticket).where(Ticket.conversation_id == conv.id, Ticket.status == "open")
    ).first()
    ticket_created = open_ticket is None
    channel_label = "Messenger" if clean_platform == "messenger" else "Instagram"
    if open_ticket is None:
        open_ticket = Ticket(conversation_id=conv.id, reason=f"Messaggio {channel_label}")
        session.add(open_ticket)
    assignee = _auto_assign(session, conv)
    _apply_sla(session, conv, start=True)
    _commit_with_media(session, media_keys)
    session.refresh(conv)
    session.refresh(inbound_message)
    _emit_visitor_message(session, conv, inbound_message)
    session.refresh(open_ticket)
    if ticket_created:
        tenant = session.get(Client, key.client_id)
        notify_new_ticket(tenant.name if tenant else "Supporto", conv.id, open_ticket.id, open_ticket.reason)
        push_service.send(
            session, key.client_id, "assignment" if assignee else "escalation",
            title=f"Nuovo {channel_label} assegnato" if assignee else f"Nuovo messaggio {channel_label}",
            body=open_ticket.reason, conversation_id=conv.id,
            operator_ids=[assignee.id] if assignee else None,
        )
        events.emit(session, key.client_id, "conversation.escalated", {
            "conversation_id": conv.id,
            "ticket_id": open_ticket.id,
            "reason": open_ticket.reason,
            "trigger": clean_platform,
            "channel": clean_platform,
        }, conv=conv)
    return {"ok": True, "created": True, "conversation_id": conv.id}


@router.get("/conversations/{conversation_id}/whatsapp/status")
def whatsapp_status(
    conversation_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id or conv.channel != "whatsapp":
        raise HTTPException(404, "conversation not found")
    return _whatsapp_channel_status(session, conv)


@router.post("/conversations/{conversation_id}/whatsapp/template")
def send_whatsapp_template(
    conversation_id: int,
    template: str = Body(...),
    language_code: str = Body("it"),
    parameters: list[str] = Body(default=[]),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Send an approved template after explicit opt-in, including outside the 24-hour window."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id or conv.channel != "whatsapp":
        raise HTTPException(404, "conversation not found")
    contact = session.get(Contact, conv.contact_id) if conv.contact_id else None
    status = _whatsapp_channel_status(session, conv)
    template_name = (template or "").strip()
    locale = (language_code or "").strip()
    clean_parameters = [(value or "").strip()[:500] for value in parameters[:10]]
    if not re.fullmatch(r"[a-z0-9_]{1,128}", template_name):
        raise HTTPException(400, "invalid template")
    if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", locale):
        raise HTTPException(400, "invalid language_code")
    if not status["consent_granted"]:
        raise HTTPException(409, "WhatsApp consent required")
    if not contact:
        raise HTTPException(409, "WhatsApp contact unavailable")
    delivered = whatsapp_service.send_template(
        client_id=operator.client_id,
        to=contact.external_id,
        template=template_name,
        language=locale,
        parameters=clean_parameters,
    )
    if not delivered:
        return {"ok": False, "delivered": False}
    label = f"Template WhatsApp: {template_name}"
    if clean_parameters:
        label += " · " + " · ".join(clean_parameters)
    session.add(Message(conversation_id=conv.id, role="operator", content=label[:MAX_CHAT_MESSAGE_CHARS]))
    conv.updated_at = datetime.utcnow()
    conv.status = "open"
    session.add(conv)
    session.commit()
    _audit(
        session, "operator", operator.email, "whatsapp.template.send",
        target=f"conversation:{conv.id}", client_id=operator.client_id,
        detail={"template": template_name, "language": locale},
    )
    return {"ok": True, "delivered": True}


@router.post("/conversations/{conversation_id}/attachments", status_code=201)
async def upload_conversation_attachment(
    conversation_id: int,
    file: UploadFile,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Store a private operator attachment and add it to the conversation atomically."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    if not attachment_service.configured():
        raise HTTPException(503, "attachment storage unavailable")
    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    if content_type not in attachment_service.ALLOWED_TYPES:
        raise HTTPException(415, "file type not allowed")
    data = await file.read(attachment_service.MAX_BYTES + 1)
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > attachment_service.MAX_BYTES:
        raise HTTPException(413, "file too large")
    filename = _safe_attachment_filename(file.filename)
    suffix = Path(filename).suffix.lower()[:12]
    object_key = f"tenant/{operator.client_id}/conversation/{conversation_id}/{uuid.uuid4().hex}{suffix}"
    stored = await run_in_threadpool(attachment_service.put, object_key, data, content_type)
    if not stored:
        raise HTTPException(502, "attachment upload failed")
    try:
        message = Message(conversation_id=conversation_id, role="operator", content=f"Allegato: {filename}")
        session.add(message)
        conv.updated_at = datetime.utcnow()
        session.add(conv)
        session.flush()
        attachment = Attachment(
            client_id=operator.client_id,
            conversation_id=conversation_id,
            message_id=message.id,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(data),
        )
        session.add(attachment)
        session.commit()
        session.refresh(attachment)
    except Exception:
        session.rollback()
        await run_in_threadpool(attachment_service.delete, object_key)
        raise
    _audit(
        session, "operator", operator.email, "conversation.attachment.upload",
        target=f"conversation:{conversation_id}", client_id=operator.client_id,
        detail={"attachment_id": attachment.id, "content_type": content_type, "size_bytes": len(data)},
    )
    return _attachment_payload(attachment)


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.client_id != operator.client_id:
        raise HTTPException(404, "attachment not found")
    stored = await run_in_threadpool(attachment_service.get, attachment.object_key)
    if not stored:
        raise HTTPException(502, "attachment unavailable")
    data, _stored_type = stored
    if len(data) > attachment_service.MAX_BYTES:
        raise HTTPException(502, "invalid stored attachment")
    filename = _safe_attachment_filename(attachment.filename)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.client_id != operator.client_id:
        raise HTTPException(404, "attachment not found")
    if not await run_in_threadpool(attachment_service.delete, attachment.object_key):
        raise HTTPException(502, "attachment deletion failed")
    message_id = attachment.message_id
    session.delete(attachment)
    session.flush()
    message = session.get(Message, message_id)
    if message:
        session.delete(message)
    session.commit()
    _audit(
        session, "operator", operator.email, "conversation.attachment.delete",
        target=f"attachment:{attachment_id}", client_id=operator.client_id,
    )
    return {"ok": True}

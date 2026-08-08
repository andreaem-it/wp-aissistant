"""Provider-neutral outbound WhatsApp adapter.

The backend never stores Meta access tokens. A tenant-aware adapter receives the normalized
payload and owns provider credentials, phone-number mapping and Graph API versioning.
"""

import json
import logging
import os
import urllib.error
import urllib.request

from .logging_config import log
from .usage import record_message


logger = logging.getLogger(__name__)

WHATSAPP_OUTBOUND_URL = os.getenv("WHATSAPP_OUTBOUND_URL", "").strip()
WHATSAPP_OUTBOUND_TOKEN = os.getenv("WHATSAPP_OUTBOUND_TOKEN", "").strip()
WHATSAPP_OUTBOUND_TIMEOUT = float(os.getenv("WHATSAPP_OUTBOUND_TIMEOUT", "10"))


def send_message(*, client_id: int, to: str, body: str, reply_to_message_id: str = "") -> bool:
    """Send a free-form message through the configured provider adapter.

    Callers enforce the WhatsApp 24-hour customer-service window. Failures are best effort:
    the operator reply remains stored, while the API reports ``delivered: false``.
    """
    if not WHATSAPP_OUTBOUND_URL or not WHATSAPP_OUTBOUND_TOKEN:
        log(logger, logging.WARNING, "whatsapp.outbound_not_configured", client_id=client_id)
        return False
    payload = json.dumps({
        "client_id": client_id,
        "to": to,
        "type": "text",
        "text": body,
        "reply_to_message_id": reply_to_message_id,
    }).encode()
    request = urllib.request.Request(
        WHATSAPP_OUTBOUND_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {WHATSAPP_OUTBOUND_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=WHATSAPP_OUTBOUND_TIMEOUT) as response:
            ok = 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log(logger, logging.WARNING, "whatsapp.outbound_failed", client_id=client_id, error=type(exc).__name__)
        record_message(client_id, "whatsapp", ok=False)
        return False
    if not ok:
        log(logger, logging.WARNING, "whatsapp.outbound_failed", client_id=client_id, status=response.status)
    # contato qui e non prima: un provider non configurato non ha inviato nulla e non costa nulla
    record_message(client_id, "whatsapp", ok=ok)
    return ok


def send_template(*, client_id: int, to: str, template: str, language: str, parameters: list[str]) -> bool:
    """Send an approved provider template, including outside the 24-hour service window."""
    if not WHATSAPP_OUTBOUND_URL or not WHATSAPP_OUTBOUND_TOKEN:
        log(logger, logging.WARNING, "whatsapp.outbound_not_configured", client_id=client_id)
        return False
    payload = json.dumps({
        "client_id": client_id,
        "to": to,
        "type": "template",
        "template": template,
        "language": language,
        "parameters": parameters,
    }).encode()
    request = urllib.request.Request(
        WHATSAPP_OUTBOUND_URL,
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {WHATSAPP_OUTBOUND_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=WHATSAPP_OUTBOUND_TIMEOUT) as response:
            ok = 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log(logger, logging.WARNING, "whatsapp.template_failed", client_id=client_id, error=type(exc).__name__)
        record_message(client_id, "whatsapp", ok=False)
        return False
    record_message(client_id, "whatsapp", ok=ok)
    return ok


def config_status() -> dict:
    """Return only non-secret configuration state."""
    return {"configured": bool(WHATSAPP_OUTBOUND_URL and WHATSAPP_OUTBOUND_TOKEN)}

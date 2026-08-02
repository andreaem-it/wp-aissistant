"""Provider-neutral outbound adapter for Facebook Messenger and Instagram Direct.

Provider credentials and page/account mapping stay outside the backend. A tenant-aware
adapter receives normalized payloads and owns Meta Graph API details.
"""

import json
import logging
import os
import urllib.error
import urllib.request

from .logging_config import log


logger = logging.getLogger(__name__)

META_MESSAGING_OUTBOUND_URL = os.getenv("META_MESSAGING_OUTBOUND_URL", "").strip()
META_MESSAGING_OUTBOUND_TOKEN = os.getenv("META_MESSAGING_OUTBOUND_TOKEN", "").strip()
META_MESSAGING_OUTBOUND_TIMEOUT = float(os.getenv("META_MESSAGING_OUTBOUND_TIMEOUT", "10"))


def send_message(
    *, client_id: int, platform: str, recipient_id: str, body: str,
    reply_to_message_id: str = "",
) -> bool:
    if platform not in {"messenger", "instagram"}:
        return False
    if not META_MESSAGING_OUTBOUND_URL or not META_MESSAGING_OUTBOUND_TOKEN:
        log(logger, logging.WARNING, "meta_messaging.outbound_not_configured", client_id=client_id, platform=platform)
        return False
    payload = json.dumps({
        "client_id": client_id,
        "platform": platform,
        "recipient_id": recipient_id,
        "text": body,
        "reply_to_message_id": reply_to_message_id,
    }).encode()
    request = urllib.request.Request(
        META_MESSAGING_OUTBOUND_URL,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {META_MESSAGING_OUTBOUND_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=META_MESSAGING_OUTBOUND_TIMEOUT) as response:
            ok = 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        log(logger, logging.WARNING, "meta_messaging.outbound_failed", client_id=client_id, platform=platform, error=type(exc).__name__)
        return False
    if not ok:
        log(logger, logging.WARNING, "meta_messaging.outbound_failed", client_id=client_id, platform=platform, status=response.status)
    return ok


def config_status() -> dict:
    return {"configured": bool(META_MESSAGING_OUTBOUND_URL and META_MESSAGING_OUTBOUND_TOKEN)}

"""Private attachment storage adapter backed by an authenticated Cloudflare Worker."""
import base64
import binascii
import os
import urllib.error
import urllib.parse
import urllib.request

STORAGE_URL = os.getenv("ATTACHMENT_STORAGE_URL", "").rstrip("/")
STORAGE_TOKEN = os.getenv("ATTACHMENT_STORAGE_TOKEN", "")
TIMEOUT = float(os.getenv("ATTACHMENT_STORAGE_TIMEOUT", "15"))
MAX_BYTES = int(os.getenv("ATTACHMENT_MAX_BYTES", str(10 * 1024 * 1024)))
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf", "text/plain", "audio/mpeg", "audio/ogg", "video/mp4"}
# Channel adapters forward the bytes they already downloaded: the backend never holds provider
# tokens and never fetches a remote URL, so there is no SSRF surface on the inbound path.
MAX_INBOUND_FILES = int(os.getenv("ATTACHMENT_MAX_INBOUND_FILES", "5"))
MAX_INBOUND_TOTAL_BYTES = int(os.getenv("ATTACHMENT_MAX_INBOUND_TOTAL_BYTES", str(MAX_BYTES)))
# Only formats a browser renders as an image and never as script: no SVG, ever.
INLINE_TYPES = {"image/jpeg", "image/png", "image/webp"}

def configured() -> bool:
    return bool(STORAGE_URL and STORAGE_TOKEN)


class InboundMediaError(ValueError):
    """Rejected media from a channel adapter. `status` is the HTTP status to answer with."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def decode_inbound(items) -> list[tuple[str, str, bytes]]:
    """Validate media forwarded by a channel adapter, returning (filename, type, bytes).

    A malformed payload is an adapter bug and is refused whole: storing half a message would
    leave the operator guessing what the customer actually sent.
    """
    if not items:
        return []
    if not isinstance(items, list):
        raise InboundMediaError("attachments must be a list")
    if len(items) > MAX_INBOUND_FILES:
        raise InboundMediaError(f"at most {MAX_INBOUND_FILES} attachments per message")
    decoded, total = [], 0
    for item in items:
        if not isinstance(item, dict):
            raise InboundMediaError("each attachment must be an object")
        content_type = str(item.get("content_type") or "").lower().split(";", 1)[0].strip()
        if content_type not in ALLOWED_TYPES:
            raise InboundMediaError(f"attachment type not allowed: {content_type or 'missing'}", status=415)
        raw = item.get("data")
        if not isinstance(raw, str) or not raw:
            raise InboundMediaError("attachment data must be base64 text")
        try:
            data = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise InboundMediaError("attachment data must be valid base64") from None
        if not data:
            raise InboundMediaError("empty attachment")
        if len(data) > MAX_BYTES:
            raise InboundMediaError("attachment too large", status=413)
        total += len(data)
        if total > MAX_INBOUND_TOTAL_BYTES:
            raise InboundMediaError("attachments too large", status=413)
        decoded.append((str(item.get("filename") or "allegato")[:180], content_type, data))
    return decoded

def _url(key: str) -> str:
    return f"{STORAGE_URL}/objects/{urllib.parse.quote(key, safe='/')}"

def put(key: str, data: bytes, content_type: str) -> bool:
    if not configured(): return False
    req = urllib.request.Request(_url(key), data=data, method="PUT", headers={"Authorization": f"Bearer {STORAGE_TOKEN}", "Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response: return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError): return False

def get(key: str) -> tuple[bytes, str] | None:
    if not configured(): return None
    req = urllib.request.Request(_url(key), headers={"Authorization": f"Bearer {STORAGE_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response: return response.read(MAX_BYTES + 1), response.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError): return None

def delete(key: str) -> bool:
    if not configured(): return False
    req = urllib.request.Request(_url(key), method="DELETE", headers={"Authorization": f"Bearer {STORAGE_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response: return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError): return False

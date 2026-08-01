"""Private attachment storage adapter backed by an authenticated Cloudflare Worker."""
import os
import urllib.error
import urllib.parse
import urllib.request

STORAGE_URL = os.getenv("ATTACHMENT_STORAGE_URL", "").rstrip("/")
STORAGE_TOKEN = os.getenv("ATTACHMENT_STORAGE_TOKEN", "")
TIMEOUT = float(os.getenv("ATTACHMENT_STORAGE_TIMEOUT", "15"))
MAX_BYTES = int(os.getenv("ATTACHMENT_MAX_BYTES", str(10 * 1024 * 1024)))
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf", "text/plain", "audio/mpeg", "audio/ogg", "video/mp4"}

def configured() -> bool:
    return bool(STORAGE_URL and STORAGE_TOKEN)

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

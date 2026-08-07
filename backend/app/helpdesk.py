"""Provider-neutral outbound helpdesk adapter client."""
import json
import os
import urllib.error
import urllib.request

from .db import HelpdeskExport

HELPDESK_ADAPTER_URL = os.getenv("HELPDESK_ADAPTER_URL", "").strip()
HELPDESK_ADAPTER_TOKEN = os.getenv("HELPDESK_ADAPTER_TOKEN", "").strip()
HELPDESK_ADAPTER_TIMEOUT = float(os.getenv("HELPDESK_ADAPTER_TIMEOUT", "10"))


def export_ticket(*, client_id: int, provider: str, external_account_id: str, ticket: dict) -> tuple[bool, str, str, str]:
    """Return (delivered, external_id, external_url, safe_error)."""
    if not HELPDESK_ADAPTER_URL:
        return False, "", "", "Adapter helpdesk non configurato"
    payload = json.dumps({
        "client_id": client_id,
        "provider": provider,
        "external_account_id": external_account_id,
        "ticket": ticket,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if HELPDESK_ADAPTER_TOKEN:
        headers["Authorization"] = f"Bearer {HELPDESK_ADAPTER_TOKEN}"
    request = urllib.request.Request(HELPDESK_ADAPTER_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=HELPDESK_ADAPTER_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
            if 200 <= response.status < 300 and result.get("ok", True):
                return (
                    True,
                    str(result.get("external_id", ""))[:255],
                    str(result.get("external_url", ""))[:1000],
                    "",
                )
            return False, "", "", "Il sistema helpdesk ha rifiutato il ticket"
    except urllib.error.HTTPError:
        return False, "", "", "Il sistema helpdesk ha rifiutato il ticket"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, "", "", "Helpdesk temporaneamente non raggiungibile"


HELPDESK_PROVIDERS = ("zendesk", "freshdesk")


def export_payload(row: HelpdeskExport) -> dict:
    return {
        "status": row.status,
        "external_id": row.external_id,
        "external_url": row.external_url,
        "error": row.error,
    }

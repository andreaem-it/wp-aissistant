"""Provider-neutral CRM adapter client.

The app sends tenant-scoped lead data to one trusted adapter. OAuth/API credentials and the
provider-specific Brevo/Zoho/Pipedrive calls belong to that adapter and never enter this database.
"""
import json
import os
import urllib.error
import urllib.request

CRM_ADAPTER_URL = os.getenv("CRM_ADAPTER_URL", "").strip()
CRM_ADAPTER_TOKEN = os.getenv("CRM_ADAPTER_TOKEN", "").strip()
CRM_ADAPTER_TIMEOUT = float(os.getenv("CRM_ADAPTER_TIMEOUT", "10"))


def sync_lead(*, client_id: int, provider: str, external_account_id: str, lead: dict) -> tuple[bool, str, str]:
    """Return (delivered, external_id, safe_error). Missing config is an explicit failure."""
    if not CRM_ADAPTER_URL:
        return False, "", "Adapter CRM non configurato"
    payload = json.dumps({
        "client_id": client_id,
        "provider": provider,
        "external_account_id": external_account_id,
        "lead": lead,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if CRM_ADAPTER_TOKEN:
        headers["Authorization"] = f"Bearer {CRM_ADAPTER_TOKEN}"
    request = urllib.request.Request(CRM_ADAPTER_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=CRM_ADAPTER_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
            if 200 <= response.status < 300 and result.get("ok", True):
                return True, str(result.get("external_id", ""))[:255], ""
            return False, "", "Il CRM ha rifiutato il lead"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, "", "CRM temporaneamente non raggiungibile"

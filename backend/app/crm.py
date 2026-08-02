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


def configure_brevo(*, client_id: int, api_key: str) -> tuple[bool, str, str]:
    if not CRM_ADAPTER_URL:
        return False, "", "Adapter CRM non configurato"
    url = CRM_ADAPTER_URL.rsplit("/", 1)[0] + "/configure"
    payload = json.dumps({"client_id": client_id, "provider": "brevo", "api_key": api_key}).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {CRM_ADAPTER_TOKEN}",
    }, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=CRM_ADAPTER_TIMEOUT) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
            account_id = str(result.get("external_account_id", ""))[:255]
            return bool(result.get("ok") and account_id), account_id, "" if account_id else "Account Brevo non valido"
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8") or "{}")
            return False, "", str(result.get("error", "Chiave Brevo non valida"))[:255]
        except ValueError:
            return False, "", "Chiave Brevo non valida"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False, "", "CRM temporaneamente non raggiungibile"


def disconnect(*, client_id: int, provider: str) -> bool:
    if not CRM_ADAPTER_URL:
        return False
    url = CRM_ADAPTER_URL.rsplit("/", 1)[0] + "/configure"
    request = urllib.request.Request(url, data=json.dumps({
        "client_id": client_id, "provider": provider,
    }).encode("utf-8"), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {CRM_ADAPTER_TOKEN}",
    }, method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=CRM_ADAPTER_TIMEOUT) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError):
        return False


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

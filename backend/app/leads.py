"""Lead capture: the vocabulary of a form and how one is described to a caller.

Shared by the automations (which manage forms) and the widget (which renders them), so neither
owns it. The field types are a closed set: a form the widget cannot render is rejected at save
time rather than failing in front of a visitor.
"""
import json

from .db import LeadForm
from .util import iso as _iso

LEAD_FIELD_TYPES = ("text", "email", "tel", "select")
LEAD_TRIGGERS = ("escalation", "chat_start")
MAX_LEAD_FIELDS = 8
MAX_LEAD_VALUE_CHARS = 500


def form_payload(form: LeadForm, *, public: bool = False) -> dict:
    fields = json.loads(form.fields or "[]")
    if public:
        # the visitor never sees the scoring weights
        fields = [{k: v for k, v in field.items() if k != "points"} for field in fields]
        return {
            "id": form.id,
            "intro": form.intro,
            "consent_text": form.consent_text,
            "fields": fields,
            "trigger": form.trigger,
        }
    return {
        "id": form.id,
        "name": form.name,
        "trigger": form.trigger,
        "intro": form.intro,
        "consent_text": form.consent_text,
        "fields": fields,
        "active": form.active,
        "created_at": _iso(form.created_at),
    }

"""The routing table is a contract with every client already in the wild.

main.py is being split into routers one area at a time. A move must change nothing a caller can
observe, so these tests pin the paths and methods of the areas already moved: if a router stops
being registered, or a path drifts while being relocated, this fails before the feature tests do
and says exactly what went missing.
"""
from app.main import app

# path -> methods, as served before the split. Extend this when an area moves out.
COMMERCIAL_ROUTES = {
    "/billing/checkout": {"POST"},
    "/billing/portal": {"POST"},
    "/billing/webhook": {"POST"},
    "/billing/plans": {"GET"},
    "/admin/revenue": {"GET"},
    "/admin/costs": {"GET"},
    "/admin/activation": {"GET"},
    "/admin/at-risk": {"GET"},
    "/admin/model-prices": {"GET", "PUT"},
    "/admin/model-prices/{price_id}": {"DELETE"},
    "/admin/clients/{client_id}/plan": {"POST"},
    "/admin/clients/{client_id}/subscription/trial": {"POST"},
    "/admin/clients/{client_id}/subscription/discount": {"POST", "DELETE"},
    "/admin/clients/{client_id}/subscription/pause": {"POST"},
    "/admin/clients/{client_id}/subscription/cancel": {"POST"},
}


DEVELOPER_ROUTES = {
    "/api-keys": {"GET", "POST"},
    "/api-keys/{key_id}": {"DELETE"},
    "/webhooks": {"GET", "POST"},
    "/webhooks/{endpoint_id}": {"PATCH", "DELETE"},
    "/webhooks/{endpoint_id}/test": {"POST"},
    "/webhooks/{endpoint_id}/deliveries": {"GET"},
    "/webhooks/{endpoint_id}/stats": {"GET"},
    "/webhooks/{endpoint_id}/deliveries/{delivery_id}/replay": {"POST"},
}


PUBLIC_API_ROUTES = {
    "/v1/conversations": {"GET"},
    "/v1/conversations/{conversation_id}": {"GET"},
    "/v1/conversations/{conversation_id}/reply": {"POST"},
    "/v1/conversations/{conversation_id}/status": {"POST"},
    "/v1/conversations/{conversation_id}/tags": {"POST"},
    "/v1/stats": {"GET"},
    "/v1/knowledge/documents": {"POST"},
}


CHANNEL_ROUTES = {
    "/channels/email/inbound": {"POST"},
    "/channels/whatsapp/inbound": {"POST"},
    "/channels/meta/inbound": {"POST"},
    "/conversations/{conversation_id}/whatsapp/status": {"GET"},
    "/conversations/{conversation_id}/whatsapp/template": {"POST"},
    "/conversations/{conversation_id}/attachments": {"POST"},
    "/attachments/{attachment_id}": {"GET", "DELETE"},
}


INSIGHT_ROUTES = {
    "/stats": {"GET"},
    "/csat": {"GET"},
    "/analytics/overview": {"GET"},
    "/analytics/knowledge-gaps": {"GET"},
    "/analytics/knowledge-gaps/review": {"POST"},
    "/analytics/knowledge-gaps/draft": {"POST"},
    "/analytics/knowledge-drafts": {"GET"},
    "/analytics/knowledge-drafts/{draft_id}/publish": {"POST"},
}


AUTOMATION_ROUTES = {
    "/workflows": {"GET", "POST"},
    "/workflows/{workflow_id}": {"PATCH", "DELETE"},
    "/workflows/{workflow_id}/preview": {"POST"},
    "/workflows/{workflow_id}/runs": {"GET"},
    "/workflows/{workflow_id}/scheduled": {"GET"},
    "/proactive-rules": {"GET", "POST"},
    "/proactive-rules/{rule_id}": {"PATCH", "DELETE"},
    "/proactive-rules/{rule_id}/experiment": {"POST"},
    "/lead-forms": {"GET", "POST"},
    "/lead-forms/{form_id}": {"PATCH", "DELETE"},
    "/leads": {"GET"},
    "/leads/export": {"GET"},
    "/leads/{lead_id}/crm-sync": {"POST"},
}


HELPDESK_CONFIG_ROUTES = {
    "/routing-settings": {"GET", "PUT"},
    "/departments": {"GET", "POST"},
    "/departments/{department_id}": {"DELETE"},
    "/departments/{department_id}/members": {"GET", "POST"},
    "/departments/{department_id}/members/{operator_id}": {"DELETE"},
    "/support-schedule": {"GET", "PUT"},
    "/sla-policies": {"GET", "POST"},
    "/sla-policies/{policy_id}": {"PATCH", "DELETE"},
    "/canned-responses": {"GET", "POST"},
    "/canned-responses/{canned_id}": {"DELETE"},
    "/info-fields": {"GET", "POST"},
    "/info-fields/{field_id}": {"DELETE"},
    "/conversations/{conversation_id}/info": {"GET", "PUT"},
    "/crm/connections": {"GET"},
    "/crm/connections/{provider}": {"PUT", "DELETE"},
    "/crm/connect/brevo": {"POST"},
    "/helpdesk/connections": {"GET"},
    "/helpdesk/connections/{provider}": {"PUT", "DELETE"},
    "/tickets/{ticket_id}/helpdesk-export": {"POST"},
    "/push/config": {"GET"},
    "/push/subscriptions": {"POST", "DELETE"},
    "/push/preferences": {"PATCH"},
}


INBOX_ROUTES = {
    "/conversations": {"GET"},
    "/conversations/{conversation_id}": {"DELETE"},
    "/conversations/{conversation_id}/messages": {"GET"},
    "/conversations/{conversation_id}/reply": {"POST"},
    "/conversations/{conversation_id}/status": {"POST"},
    "/conversations/{conversation_id}/routing": {"PATCH"},
    "/conversations/{conversation_id}/typing": {"POST"},
    "/conversations/{conversation_id}/presence": {"POST"},
    "/conversations/{conversation_id}/activity": {"GET"},
    "/conversations/{conversation_id}/classify": {"POST"},
    "/conversations/{conversation_id}/tags": {"POST"},
    "/conversations/{conversation_id}/tags/{tag_id}": {"DELETE"},
    "/conversations/{conversation_id}/notes": {"GET", "POST"},
    "/conversations/{conversation_id}/notes/{note_id}": {"DELETE"},
    "/tickets": {"GET"},
    "/tickets/{ticket_id}/reply": {"POST"},
    "/tags": {"GET", "POST"},
    "/tags/{tag_id}": {"DELETE"},
    "/mentions": {"GET"},
    "/mentions/read": {"POST"},
    "/saved-views": {"GET", "POST"},
    "/saved-views/{view_id}": {"PATCH", "DELETE"},
    "/gdpr/erase": {"POST"},
    "/gdpr/export": {"POST"},
}


WIDGET_ROUTES = {
    "/chat": {"POST"},
    "/chat/stream": {"POST"},
    "/chat/feedback": {"POST"},
    "/chat/contact": {"POST"},
    "/chat/ticket": {"POST"},
    "/chat/rating": {"POST"},
    "/usage": {"GET"},
    "/team/operators": {"GET"},
    "/plugin/register": {"POST"},
    "/plugin/support-schedule": {"PUT"},
    "/widget/lead-form": {"GET"},
    "/widget/leads": {"POST"},
    "/widget/proactive": {"GET"},
    "/widget/proactive/{rule_id}/event": {"POST"},
}


ADMIN_ROUTES = {
    "/admin/stats": {"GET"},
    "/admin/health": {"GET"},
    "/admin/test-email": {"POST"},
    "/admin/problematic": {"GET"},
    "/admin/clients": {"GET", "POST"},
    "/admin/clients/{client_id}/operators": {"GET", "POST"},
    "/admin/clients/{client_id}/origins": {"POST"},
    "/admin/clients/{client_id}/rotate-key": {"POST"},
    "/admin/operators/{operator_id}": {"DELETE"},
    "/admin/conversations/{conversation_id}/debug": {"GET"},
    "/admin/audit": {"GET"},
    "/admin/plans": {"GET", "POST"},
    "/admin/plans/{plan_id}": {"POST"},
    "/admin/reembed": {"POST"},
}

ACCOUNT_ROUTES = {
    "/public/plans": {"GET"},
    "/signup": {"POST"},
    "/me": {"GET"},
    "/me/name": {"POST"},
    "/me/password": {"POST"},
    "/me/rotate-key": {"POST"},
    "/onboarding/status": {"GET"},
    "/auth/verify-email": {"POST"},
    "/auth/resend-verification": {"POST"},
    "/auth/forgot": {"POST"},
    "/auth/reset": {"POST"},
    "/operator/login": {"POST"},
    "/operator/logout": {"POST"},
}

KNOWLEDGE_ROUTES = {
    "/ingest/document": {"POST"},
    "/ingest/site-page": {"POST"},
    "/ingest/product": {"POST"},
    "/ingest/jobs/{job_id}": {"GET"},
    "/ingest/woocommerce": {"POST"},
    "/knowledge/teach": {"POST"},
    "/knowledge-base": {"GET", "DELETE"},
    "/plugin/knowledge-base": {"DELETE"},
}


def _iter_routes(routes):
    """Walk the routing table, expanding included routers.

    FastAPI keeps an included router as a single lazy entry in `app.routes` rather than
    flattening its routes into the list, so anything that inspects `app.routes` directly sees
    the router disappear and concludes the paths were lost. They are served correctly; only a
    naive walk misses them.
    """
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _iter_routes(nested.routes)
        else:
            yield route


def _table() -> dict[str, set[str]]:
    table: dict[str, set[str]] = {}
    for route in _iter_routes(app.routes):
        methods = getattr(route, "methods", None)
        if methods:
            table.setdefault(route.path, set()).update(methods - {"HEAD"})
    return table


def test_extracted_area_is_still_served():
    """Every path moved into app/routers/commercial.py must still answer on the same method."""
    table = _table()
    expected = {**COMMERCIAL_ROUTES, **DEVELOPER_ROUTES, **PUBLIC_API_ROUTES, **CHANNEL_ROUTES, **INSIGHT_ROUTES, **AUTOMATION_ROUTES, **HELPDESK_CONFIG_ROUTES, **INBOX_ROUTES, **WIDGET_ROUTES,
        **ADMIN_ROUTES, **ACCOUNT_ROUTES, **KNOWLEDGE_ROUTES}
    missing = {p: m for p, m in expected.items() if not m <= table.get(p, set())}
    assert not missing, f"rotte perse nello spostamento: {missing}"


def test_extracted_area_comes_from_the_router():
    """Guards against a path being quietly re-added to main.py, leaving two definitions."""
    from app.routers import (
        automations, channels, commercial, developers, helpdesk_config, inbox, insights,
        accounts, admin, public_api, knowledge, widget,
    )

    assert set(COMMERCIAL_ROUTES) == {r.path for r in commercial.router.routes}
    assert set(DEVELOPER_ROUTES) == {r.path for r in developers.router.routes}
    assert set(PUBLIC_API_ROUTES) == {r.path for r in public_api.router.routes}
    assert set(CHANNEL_ROUTES) == {r.path for r in channels.router.routes}
    assert set(INSIGHT_ROUTES) == {r.path for r in insights.router.routes}
    assert set(AUTOMATION_ROUTES) == {r.path for r in automations.router.routes}
    assert set(HELPDESK_CONFIG_ROUTES) == {r.path for r in helpdesk_config.router.routes}
    assert set(INBOX_ROUTES) == {r.path for r in inbox.router.routes}
    assert set(WIDGET_ROUTES) == {r.path for r in widget.router.routes}
    assert set(ADMIN_ROUTES) == {r.path for r in admin.router.routes}
    assert set(ACCOUNT_ROUTES) == {r.path for r in accounts.router.routes}
    assert set(KNOWLEDGE_ROUTES) == {r.path for r in knowledge.router.routes}


def test_no_path_is_registered_twice_with_the_same_method():
    """A duplicate registration is silently shadowed by whichever came first — never useful."""
    seen: dict[tuple[str, str], int] = {}
    for route in _iter_routes(app.routes):
        for method in getattr(route, "methods", set()) - {"HEAD"}:
            seen[(route.path, method)] = seen.get((route.path, method), 0) + 1
    duplicates = {k: n for k, n in seen.items() if n > 1}
    assert not duplicates, f"rotte duplicate: {duplicates}"

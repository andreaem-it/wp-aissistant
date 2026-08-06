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
    expected = {**COMMERCIAL_ROUTES, **DEVELOPER_ROUTES, **PUBLIC_API_ROUTES}
    missing = {p: m for p, m in expected.items() if not m <= table.get(p, set())}
    assert not missing, f"rotte perse nello spostamento: {missing}"


def test_extracted_area_comes_from_the_router():
    """Guards against a path being quietly re-added to main.py, leaving two definitions."""
    from app.routers import commercial, developers, public_api

    assert set(COMMERCIAL_ROUTES) == {r.path for r in commercial.router.routes}
    assert set(DEVELOPER_ROUTES) == {r.path for r in developers.router.routes}
    assert set(PUBLIC_API_ROUTES) == {r.path for r in public_api.router.routes}


def test_no_path_is_registered_twice_with_the_same_method():
    """A duplicate registration is silently shadowed by whichever came first — never useful."""
    seen: dict[tuple[str, str], int] = {}
    for route in _iter_routes(app.routes):
        for method in getattr(route, "methods", set()) - {"HEAD"}:
            seen[(route.path, method)] = seen.get((route.path, method), 0) + 1
    duplicates = {k: n for k, n in seen.items() if n > 1}
    assert not duplicates, f"rotte duplicate: {duplicates}"

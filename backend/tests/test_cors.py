"""CORS preflight. These are browser-facing contracts: when they are wrong the request never
reaches the server, so nothing shows up in the logs and the API looks perfectly healthy."""
from app import cors
from app.main import app

PANEL_ORIGIN = "http://localhost:5173"
PREFLIGHT = {
    "Origin": PANEL_ORIGIN,
    "Access-Control-Request-Method": "PUT",
    "Access-Control-Request-Headers": "authorization,content-type",
}


def _allowed_methods(response) -> set[str]:
    return {m.strip() for m in response.headers.get("access-control-allow-methods", "").split(",")}


def test_preflight_allows_every_method_the_app_routes(client):
    """The panel saves with PUT and removes with DELETE: advertising only GET/POST silently
    disabled 36 routes in the browser while curl kept working."""
    response = client.options("/admin/model-prices", headers=PREFLIGHT)

    assert response.status_code == 204
    allowed = _allowed_methods(response)
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        assert method in allowed, f"{method} missing from the CORS preflight"


def test_advertised_methods_cover_the_routing_table(client):
    """Guards against the same drift returning: whatever the app routes must be advertised."""
    routed = {
        method
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method not in ("HEAD",)
    }
    allowed = _allowed_methods(client.options("/admin/model-prices", headers=PREFLIGHT))

    assert routed <= allowed, f"non annunciati: {sorted(routed - allowed)}"


def test_preflight_still_refuses_an_unknown_origin(client, monkeypatch):
    """Widening the methods must not widen who may call them."""
    monkeypatch.setattr(cors, "CORS_ALLOW_ALL", False)
    monkeypatch.setattr(cors, "_ALLOWED_ORIGINS", {PANEL_ORIGIN})

    refused = client.options("/admin/model-prices", headers={**PREFLIGHT, "Origin": "https://evil.example"})
    accepted = client.options("/admin/model-prices", headers=PREFLIGHT)

    assert refused.status_code == 403
    assert "access-control-allow-origin" not in refused.headers
    assert accepted.status_code == 204

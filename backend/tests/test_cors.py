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


def test_www_and_apex_are_the_same_site(client, tenant, monkeypatch):
    """Una regola sola, scritta in due modi, non era d'accordo con sé stessa.

    Il controllo della licenza normalizza già `www.` (`origins.host_of`), perché `esempio.it` e
    `www.esempio.it` sono lo stesso sito e devono costare uno slot solo. L'allowlist CORS invece
    confrontava la stringa esatta: chi registrava l'apex e riceveva visitatori su `www` si
    prendeva un `403` al **preflight**, cioè prima che la richiesta arrivasse al server.

    Il sintomo è il peggiore possibile: nessuna riga nei nostri log che parli di licenza — il
    rifiuto viene da un livello più in alto — e un cliente che vede la chat non partire su metà
    del proprio traffico. Ce l'avevamo in produzione sul nostro stesso sito.
    """
    from sqlmodel import Session
    from app import db

    with Session(db.engine) as session:
        session.add(db.ClientOrigin(
            client_id=tenant["cid"], origin="https://esempio.it", host="esempio.it",
            kind="live", source="panel",
        ))
        session.commit()
        cors.rebuild_allowed_origins(session)
    monkeypatch.setattr(cors, "CORS_ALLOW_ALL", False)

    for origin in ("https://esempio.it", "https://www.esempio.it"):
        response = client.options("/chat", headers={**PREFLIGHT, "Origin": origin})
        assert response.status_code == 204, origin
        assert response.headers["access-control-allow-origin"] == origin


def test_a_registered_www_also_admits_its_apex(client, tenant, monkeypatch):
    """Vale nei due versi: chi registra la forma con `www` non deve perdere l'apex."""
    from sqlmodel import Session
    from app import db

    with Session(db.engine) as session:
        session.add(db.ClientOrigin(
            client_id=tenant["cid"], origin="https://www.esempio.it", host="esempio.it",
            kind="live", source="panel",
        ))
        session.commit()
        cors.rebuild_allowed_origins(session)
    monkeypatch.setattr(cors, "CORS_ALLOW_ALL", False)

    response = client.options("/chat", headers={**PREFLIGHT, "Origin": "https://esempio.it"})

    assert response.status_code == 204


def test_only_www_is_treated_as_the_same_site(client, tenant, monkeypatch):
    """`www` è convenzione universale per «lo stesso sito»; un sottodominio qualunque no.
    Trattarli allo stesso modo regalerebbe domini a chi ne ha pagato uno."""
    from sqlmodel import Session
    from app import db

    with Session(db.engine) as session:
        session.add(db.ClientOrigin(
            client_id=tenant["cid"], origin="https://esempio.it", host="esempio.it",
            kind="live", source="panel",
        ))
        session.commit()
        cors.rebuild_allowed_origins(session)
    monkeypatch.setattr(cors, "CORS_ALLOW_ALL", False)

    response = client.options("/chat", headers={**PREFLIGHT, "Origin": "https://app.esempio.it"})

    assert response.status_code == 403

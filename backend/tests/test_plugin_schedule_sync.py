import hashlib
import hmac
import io

from sqlmodel import Session, select

from app import db, origins
# plugin verification moved with the widget router when main.py was split
from app.routers import widget as main
from test_leads import _other_tenant


SECRET = "wordpress-installation-secret-abcdefghijklmnopqrstuvwxyz"
SCHEDULE = {
    "enabled": True,
    "weekdays": [1, 2, 3, 4, 5],
    "start_time": "09:00",
    "end_time": "18:00",
    "timezone": "Europe/Rome",
}


def _allow_site(tenant):
    """Il sito coperto dalla licenza del tenant. Passa dalla tabella `ClientOrigin`, che è la
    sorgente di verità: scrivere la vecchia colonna di testo non autorizzerebbe più nulla."""
    with Session(db.engine) as session:
        client = session.get(db.Client, tenant["cid"])
        for row in origins.registered_rows(session, tenant["cid"]):
            session.delete(row)
        session.flush()
        origins.register(session, client, "https://shop.example.it", "live",
                         source="admin", enforce_cooldown=False)
        session.commit()


def test_verified_plugin_registration_syncs_wordpress_schedule(client, tenant, monkeypatch):
    _allow_site(tenant)
    checked = []
    monkeypatch.setattr(main, "_verify_plugin_site", lambda url, secret: checked.append((url, secret)) or True)
    response = client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://shop.example.it/path",
        "proof_url": "https://shop.example.it/wordpress/wp-json/wpai/v1/site-proof",
        "secret": SECRET,
        "plugin_version": "1.1.8",
        "support_schedule": SCHEDULE,
    })
    assert response.status_code == 200
    assert checked == [("https://shop.example.it/wordpress/wp-json/wpai/v1/site-proof", SECRET)]
    assert response.json()["schedule"]["source"] == "wordpress"
    with Session(db.engine) as session:
        installation = session.exec(select(db.PluginInstallation)).one()
        assert installation.secret_hash == hashlib.sha256(SECRET.encode()).hexdigest()
        assert SECRET not in str(installation)

    updated = client.put("/plugin/support-schedule", headers={"Authorization": f"Bearer {SECRET}"}, json={
        **SCHEDULE, "timezone": "+02:00", "start_time": "08:30",
    })
    assert updated.status_code == 200
    assert updated.json()["schedule"]["timezone"] == "+02:00"
    assert client.put("/plugin/support-schedule", headers=tenant["key"], json=SCHEDULE).status_code == 401


def test_wordpress_sync_preserves_panel_managed_closures(client, tenant, monkeypatch):
    _allow_site(tenant)
    monkeypatch.setattr(main, "_verify_plugin_site", lambda origin, secret: True)
    assert client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://shop.example.it", "proof_url": "https://shop.example.it/wp-json/wpai/v1/site-proof",
        "secret": SECRET, "support_schedule": SCHEDULE,
    }).status_code == 200
    assert client.put("/support-schedule", headers=tenant["op"], json={
        **SCHEDULE, "closed_dates": ["2026-12-25"], "include_italian_holidays": True,
    }).status_code == 200
    synced = client.put(
        "/plugin/support-schedule", headers={"Authorization": f"Bearer {SECRET}"}, json=SCHEDULE,
    )
    assert synced.status_code == 200
    assert synced.json()["schedule"]["closed_dates"] == ["2026-12-25"]
    assert synced.json()["schedule"]["include_italian_holidays"] is True


def test_public_widget_key_cannot_register_unverified_or_unapproved_site(client, tenant, monkeypatch):
    monkeypatch.setattr(main, "_verify_plugin_site", lambda origin, secret: False)
    assert client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://evil.example", "proof_url": "https://evil.example/wp-json/wpai/v1/site-proof", "secret": SECRET, "support_schedule": SCHEDULE,
    }).status_code == 403
    _allow_site(tenant)
    assert client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://shop.example.it", "proof_url": "https://shop.example.it/wp-json/wpai/v1/site-proof", "secret": SECRET, "support_schedule": SCHEDULE,
    }).status_code == 422


def test_plugin_credentials_and_schedule_are_tenant_isolated(client, tenant, monkeypatch):
    _allow_site(tenant)
    monkeypatch.setattr(main, "_verify_plugin_site", lambda origin, secret: True)
    assert client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://shop.example.it", "proof_url": "https://shop.example.it/wp-json/wpai/v1/site-proof", "secret": SECRET, "support_schedule": SCHEDULE,
    }).status_code == 200
    other = _other_tenant(client, "Plugin Other")
    result = client.put("/plugin/support-schedule", headers={"Authorization": f"Bearer {SECRET}"}, json={
        **SCHEDULE, "enabled": False,
    })
    assert result.status_code == 200
    assert client.get("/support-schedule", headers=other["op"]).json()["enabled"] is False


def test_site_challenge_verification_uses_hmac_and_public_address(monkeypatch):
    challenge = "fixed-challenge-value-for-tests"
    proof = hmac.new(SECRET.encode(), challenge.encode(), hashlib.sha256).hexdigest()

    class Response(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *args): return False

    monkeypatch.setattr(main.secrets, "token_urlsafe", lambda size: challenge)
    monkeypatch.setattr(main.webhooks, "_resolves_to_public_address", lambda url: True)
    monkeypatch.setattr(main.urllib.request, "urlopen", lambda request, timeout: Response(
        ('{"proof":"' + proof + '"}').encode()
    ))
    assert main._verify_plugin_site("https://shop.example.it/wp-json/wpai/v1/site-proof", SECRET) is True


def test_proof_url_must_use_allowlisted_origin_and_expected_rest_route(monkeypatch):
    monkeypatch.setattr(main.webhooks, "ALLOW_PRIVATE", True)
    allowed = ["https://shop.example.it"]
    assert main._trusted_plugin_proof_url(
        allowed, "https://shop.example.it/testfb/wp-json/wpai/v1/site-proof",
    ).endswith("/testfb/wp-json/wpai/v1/site-proof")
    assert main._trusted_plugin_proof_url(
        allowed, "https://evil.example/wp-json/wpai/v1/site-proof",
    ) == ""
    assert main._trusted_plugin_proof_url(allowed, "https://shop.example.it/admin") == ""


# ---- bootstrap dell'onboarding ----------------------------------------------------------------
#
# Con la licenza legata al dominio un cliente nuovo non ha registrato nulla, e senza questo ramo
# installare il plugin — il primo passo di ogni cliente WordPress — richiederebbe un intervento
# del superadmin. La fiducia non viene dall'elenco ma dal challenge, che prova il possesso.


def _fresh_tenant(client):
    """Un tenant appena creato: nessun dominio, come dopo un signup."""
    admin = {"Authorization": "Bearer test-admin"}
    return client.post("/admin/clients", headers=admin, json={"name": "Appena nato"}).json()


def test_a_new_tenant_registers_its_domain_by_installing_the_plugin(client, monkeypatch):
    fresh = _fresh_tenant(client)
    monkeypatch.setattr(main, "_verify_plugin_site", lambda url, secret: True)
    key = {"Authorization": f"Bearer {fresh['api_key']}"}

    response = client.post("/plugin/register", headers=key, json={
        "site_url": "https://nuovo-negozio.it",
        "proof_url": "https://nuovo-negozio.it/wp-json/wpai/v1/site-proof",
        "secret": SECRET,
    })

    assert response.status_code == 200
    with Session(db.engine) as session:
        rows = origins.registered_rows(session, fresh["id"])
    assert [(r.host, r.kind, r.source) for r in rows] == [("nuovo-negozio.it", "live", "plugin")]


def test_the_widget_works_right_after_the_plugin_registered_the_domain(client, monkeypatch):
    """La prova che il bootstrap chiude davvero l'onboarding: prima di questa chiamata il
    widget di quel sito riceveva 403."""
    fresh = _fresh_tenant(client)
    monkeypatch.setattr(main, "_verify_plugin_site", lambda url, secret: True)
    key = {"Authorization": f"Bearer {fresh['api_key']}"}
    client.post("/plugin/register", headers=key, json={
        "site_url": "https://nuovo-negozio.it",
        "proof_url": "https://nuovo-negozio.it/wp-json/wpai/v1/site-proof",
        "secret": SECRET,
    })

    chat = client.post("/chat", headers={**key, "Origin": "https://nuovo-negozio.it"},
                       json={"message": "ciao", "visitor_id": "v-appena-installato"})

    assert chat.status_code == 200


def test_a_failed_challenge_registers_no_domain(client, monkeypatch):
    """Il challenge è l'unica cosa che regge il bootstrap: se non passa, non deve restare
    nulla — altrimenti chiunque si registrerebbe il dominio di un altro."""
    fresh = _fresh_tenant(client)
    monkeypatch.setattr(main, "_verify_plugin_site", lambda url, secret: False)
    key = {"Authorization": f"Bearer {fresh['api_key']}"}

    response = client.post("/plugin/register", headers=key, json={
        "site_url": "https://non-mio.it",
        "proof_url": "https://non-mio.it/wp-json/wpai/v1/site-proof",
        "secret": SECRET,
    })

    assert response.status_code == 422
    with Session(db.engine) as session:
        assert origins.registered_rows(session, fresh["id"]) == []


def test_bootstrap_does_not_silently_replace_an_existing_domain(client, tenant, monkeypatch):
    """A slot pieno il dominio registrato non viene sostituito di nascosto da un'installazione
    su un altro sito: il cliente deve cambiarlo di proposito dal pannello."""
    monkeypatch.setattr(main, "_verify_plugin_site", lambda url, secret: True)

    response = client.post("/plugin/register", headers=tenant["key"], json={
        "site_url": "https://altro-sito.it",
        "proof_url": "https://altro-sito.it/wp-json/wpai/v1/site-proof",
        "secret": SECRET,
    })

    assert response.status_code == 403
    with Session(db.engine) as session:
        assert [r.host for r in origins.registered_rows(session, tenant["cid"])] == ["acme.example"]

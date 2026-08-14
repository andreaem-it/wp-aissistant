import json

from sqlmodel import Session, select

from app import db, push
from conftest import TENANT_ORIGIN


SUBSCRIPTION = {
    "endpoint": "https://push.example.test/subscription-1",
    "keys": {"p256dh": "public-encryption-key", "auth": "auth-secret"},
}


def test_operator_can_subscribe_update_preferences_and_unsubscribe(client, tenant, monkeypatch):
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public-vapid")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private-vapid")
    config = client.get("/push/config", headers=tenant["op"])
    assert config.status_code == 200
    assert config.json()["configured"] is True
    assert config.json()["subscriptions"] == 0

    created = client.post(
        "/push/subscriptions", headers=tenant["op"],
        json={**SUBSCRIPTION, "preferences": {"sla_breaches": False}},
    )
    assert created.json() == {"ok": True}
    assert client.patch(
        "/push/preferences", headers=tenant["op"],
        json={"preferences": {"mentions": False, "sla_breaches": True}},
    ).status_code == 200
    with Session(db.engine) as session:
        row = session.exec(select(db.PushSubscription)).one()
        assert row.client_id == tenant["cid"]
        assert row.mentions is False
        assert row.sla_breaches is True
    assert client.request(
        "DELETE", "/push/subscriptions", headers=tenant["op"],
        json={"endpoint": SUBSCRIPTION["endpoint"]},
    ).json() == {"ok": True}


def test_push_subscription_is_operator_and_tenant_scoped(client, tenant):
    assert client.post("/push/subscriptions", headers=tenant["op"], json=SUBSCRIPTION).status_code == 200
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Push Other", "allowed_origins": TENANT_ORIGIN}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=admin,
        json={"email": "push-other@example.it", "password": "password1"},
    )
    token = client.post(
        "/operator/login", json={"email": "push-other@example.it", "password": "password1"}
    ).json()["token"]
    response = client.post(
        "/push/subscriptions", headers={"Authorization": f"Bearer {token}"}, json=SUBSCRIPTION,
    )
    assert response.status_code == 409


def test_delivery_filters_target_and_preference(client, tenant, monkeypatch):
    client.post("/push/subscriptions", headers=tenant["op"], json=SUBSCRIPTION)
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public-vapid")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private-vapid")
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kwargs: sent.append(kwargs))
    with Session(db.engine) as session:
        operator_id = session.exec(select(db.PushSubscription)).one().operator_id
        assert push.send(
            session, tenant["cid"], "mention", title="Menzione", body="Nota interna",
            conversation_id=12, operator_ids=[operator_id],
        ) == 1
    payload = json.loads(sent[0]["data"])
    assert payload["title"] == "Menzione"
    assert payload["url"].endswith("/?conversation=12")


def test_subscription_validates_https_and_keys(client, tenant):
    assert client.post(
        "/push/subscriptions", headers=tenant["op"],
        json={"endpoint": "http://insecure.test", "keys": SUBSCRIPTION["keys"]},
    ).status_code == 400
    assert client.post(
        "/push/subscriptions", headers=tenant["op"],
        json={"endpoint": SUBSCRIPTION["endpoint"], "keys": {}},
    ).status_code == 400


def _fail_with(status):
    """Un `webpush` che fallisce come farebbe il servizio push, con la sua risposta HTTP."""
    class _Response:
        status_code = status

    def _send(**kwargs):
        raise push.WebPushException("rifiutata", response=_Response())

    return _send


def test_a_subscription_made_with_an_older_key_is_dropped(client, tenant, monkeypatch):
    """Le chiavi VAPID si ruotano, e da quel momento le sottoscrizioni create con la precedente
    non riceveranno mai più niente: il servizio push risponde `403`, non `410`.

    Prima si potava solo su `404/410`, quindi quelle righe restavano in base **per sempre** e
    ogni notifica spendeva una richiesta per fallire. Nessuno se ne accorgeva: una notifica non
    consegnata non ha nessuno che la reclami.
    """
    client.post("/push/subscriptions", headers=tenant["op"], json=SUBSCRIPTION)
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public-vapid")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private-vapid")
    monkeypatch.setattr(push, "webpush", _fail_with(403))

    with Session(db.engine) as session:
        assert push.send(session, tenant["cid"], "mention", title="x", body="y") == 0

    with Session(db.engine) as session:
        assert session.exec(select(db.PushSubscription)).all() == []


def test_a_gone_subscription_is_still_dropped(client, tenant, monkeypatch):
    """Il comportamento di prima non deve essersi perso strada facendo."""
    client.post("/push/subscriptions", headers=tenant["op"], json=SUBSCRIPTION)
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public-vapid")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private-vapid")
    monkeypatch.setattr(push, "webpush", _fail_with(410))

    with Session(db.engine) as session:
        assert push.send(session, tenant["cid"], "mention", title="x", body="y") == 0

    with Session(db.engine) as session:
        assert session.exec(select(db.PushSubscription)).all() == []


def test_a_temporary_failure_keeps_the_subscription(client, tenant, monkeypatch):
    """Un `500` del servizio push è un problema loro, non nostro: buttare la sottoscrizione
    trasformerebbe un guasto passeggero in un operatore che smette di ricevere notifiche finché
    non se ne accorge e le riattiva a mano."""
    client.post("/push/subscriptions", headers=tenant["op"], json=SUBSCRIPTION)
    monkeypatch.setattr(push, "VAPID_PUBLIC_KEY", "public-vapid")
    monkeypatch.setattr(push, "VAPID_PRIVATE_KEY", "private-vapid")
    monkeypatch.setattr(push, "webpush", _fail_with(500))

    with Session(db.engine) as session:
        assert push.send(session, tenant["cid"], "mention", title="x", body="y") == 0

    with Session(db.engine) as session:
        assert len(session.exec(select(db.PushSubscription)).all()) == 1

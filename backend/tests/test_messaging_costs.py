"""Email e canali dentro il margine.

I test passano dai **percorsi reali di invio**, non da `record_message`. È deliberato:
`record_embedding` fu spedito con un `NameError` dentro un `except` muto e non registrò nulla
per settimane, mentre una prova che lo chiamava direttamente sarebbe rimasta verde. Chi misura
va verificato da dove viene chiamato, non da dove è definito.
"""
import pytest
from sqlmodel import Session, select

from app import costs, db, email as email_service, whatsapp
from conftest import TENANT_ORIGIN


@pytest.fixture
def delivering(monkeypatch):
    """Provider configurato che consegna. Senza, `send_email` esce dal ramo «non configurato»,
    dove non è partito nulla e giustamente non si conta niente."""
    monkeypatch.setattr(email_service, "enabled", lambda: True)
    monkeypatch.setattr(email_service, "EMAIL_PROVIDER", "smtp")
    sent = []
    monkeypatch.setattr(email_service, "_send_smtp",
                        lambda to, subject, body, **kw: (sent.append(to), True)[1])
    return sent


def _usage(client_id, channel):
    with Session(db.engine) as session:
        return session.exec(
            select(db.MessagingUsage).where(
                db.MessagingUsage.client_id == client_id,
                db.MessagingUsage.channel == channel,
            )
        ).first()


# ---- rilevazione -------------------------------------------------------------------------


def test_a_reply_to_a_visitor_is_counted_against_its_tenant(tenant, delivering):
    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    row = _usage(tenant["cid"], "email")
    assert row is not None, "l'email non è stata contata: il margine la perderebbe"
    assert (row.sent, row.failed) == (1, 0)


def test_a_failed_delivery_is_counted_apart(tenant, monkeypatch, delivering):
    monkeypatch.setattr(email_service, "_send_smtp", lambda *a, **kw: False)

    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    row = _usage(tenant["cid"], "email")
    assert (row.sent, row.failed) == (0, 1)


def test_account_email_belongs_to_no_tenant(tenant, delivering):
    """Verifica indirizzo e reset password riguardano l'account, non il traffico dei visitatori:
    attribuirli gonfierebbe il costo di un cliente con spesa che non ha causato."""
    email_service.send_verification("tizio@example.com", "tok")
    email_service.send_password_reset("tizio@example.com", "tok")

    assert _usage(tenant["cid"], "email") is None


def test_nothing_is_counted_without_a_provider(tenant, monkeypatch):
    monkeypatch.setattr(email_service, "enabled", lambda: False)

    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    assert _usage(tenant["cid"], "email") is None


def test_a_whatsapp_message_is_counted(tenant, monkeypatch):
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_URL", "https://esempio.invalid/send")
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_TOKEN", "t")

    class _Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(whatsapp.urllib.request, "urlopen", lambda *a, **kw: _Response())

    whatsapp.send_message(client_id=tenant["cid"], to="+39000", body="ciao")

    row = _usage(tenant["cid"], "whatsapp")
    assert (row.sent, row.failed) == (1, 0)


def test_an_unconfigured_channel_records_nothing(tenant, monkeypatch):
    """Niente è partito, quindi niente è costato: contarlo come fallimento suggerirebbe un
    problema di consegna dove c'è solo un canale non attivato."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_OUTBOUND_URL", "")

    whatsapp.send_message(client_id=tenant["cid"], to="+39000", body="ciao")

    assert _usage(tenant["cid"], "whatsapp") is None


def test_the_day_is_utc_like_the_embedding_rollup(tenant, delivering):
    """I due riepiloghi finiscono sulla stessa riga di costo: se tagliassero la giornata in
    momenti diversi non sarebbero sommabili."""
    from datetime import datetime

    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    assert _usage(tenant["cid"], "email").day == datetime.utcnow().date()


# ---- prezzo e margine --------------------------------------------------------------------


def test_an_unpriced_channel_is_declared_not_free(client, tenant, delivering, monkeypatch):
    monkeypatch.delenv("EMAIL_PRICE_PER_MESSAGE_MILLICENTS", raising=False)
    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    with Session(db.engine) as session:
        summary = costs.cost_summary(session)

    assert "email" in summary["unpriced_channels"]
    row = next(r for r in summary["clients"] if r["client_id"] == tenant["cid"])
    assert row["messaging_priced"] is False
    assert row["fully_priced"] is False, "un costo ignoto non rende il tenant contabile"


def test_a_priced_channel_reaches_the_margin(client, tenant, delivering, monkeypatch):
    # 200 millesimi di centesimo a messaggio = 0,2 centesimi
    monkeypatch.setenv("EMAIL_PRICE_PER_MESSAGE_MILLICENTS", "200")
    for _ in range(10):
        email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    with Session(db.engine) as session:
        summary = costs.cost_summary(session, days=30)

    row = next(r for r in summary["clients"] if r["client_id"] == tenant["cid"])
    assert row["messages"] == {"email": 10}
    assert row["messaging_cost_cents"] == pytest.approx(2.0)
    assert row["cost_cents"] >= 2.0
    assert summary["unpriced_channels"] == []


def test_the_cost_is_normalised_to_a_month_like_the_others(client, tenant, delivering, monkeypatch):
    """I messaggi sono un flusso, non uno stock: su una finestra di 15 giorni il costo mensile
    è il doppio di quello osservato, altrimenti il margine sembrerebbe migliore di com'è."""
    monkeypatch.setenv("EMAIL_PRICE_PER_MESSAGE_MILLICENTS", "1000")  # 1 centesimo
    for _ in range(4):
        email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    with Session(db.engine) as session:
        summary = costs.cost_summary(session, days=15)

    row = next(r for r in summary["clients"] if r["client_id"] == tenant["cid"])
    assert row["messaging_cost_cents"] == pytest.approx(4.0)      # osservato nella finestra
    assert row["monthly_cost_cents"] == pytest.approx(8.0)        # normalizzato al mese


def test_failed_messages_are_not_billed(client, tenant, monkeypatch, delivering):
    """Si contano perché un tasso di fallimento invisibile è come non averlo; ma un messaggio
    non partito non entra nel costo."""
    monkeypatch.setenv("EMAIL_PRICE_PER_MESSAGE_MILLICENTS", "1000")  # 1 centesimo
    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])
    monkeypatch.setattr(email_service, "_send_smtp", lambda *a, **kw: False)
    for _ in range(3):
        email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    with Session(db.engine) as session:
        summary = costs.cost_summary(session)

    row = next(r for r in summary["clients"] if r["client_id"] == tenant["cid"])
    assert row["messages"] == {"email": 1}          # solo il riuscito
    assert row["messaging_cost_cents"] == pytest.approx(1.0)
    assert _usage(tenant["cid"], "email").failed == 3  # i falliti restano visibili


def test_messages_never_cross_tenants(client, tenant, delivering, monkeypatch):
    monkeypatch.setenv("EMAIL_PRICE_PER_MESSAGE_MILLICENTS", "1000")
    other = client.post("/admin/clients", headers={"Authorization": "Bearer test-admin"},
                        json={"name": "Vicino", "allowed_origins": TENANT_ORIGIN}).json()
    email_service.send_visitor_reply("v@example.com", "Negozio", None, client_id=tenant["cid"])

    with Session(db.engine) as session:
        summary = costs.cost_summary(session)

    rows = {r["client_id"]: r for r in summary["clients"]}
    assert rows[tenant["cid"]]["messages"] == {"email": 1}
    assert rows.get(other["id"], {"messages": {}})["messages"] == {}

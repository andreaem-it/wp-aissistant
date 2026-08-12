"""Il piano interno illimitato e il nostro tenant.

Due piani interni di natura opposta: «Nessun abbonamento» è il segnaposto per chi non ha ancora
pagato e non concede nulla, «Interno — Illimitato» è quello con cui serviamo noi stessi e
concede tutto. `internal` dice che nessuno dei due è un prodotto, non quanto concedono.

Il rischio che questi test presidiano non è che il piano non funzioni: è che finisca addosso a
un cliente, o che il nostro tenant renda inaffidabili le viste commerciali proprio mentre
iniziamo a fidarcene.
"""
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app import billing, costs, db, growth
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}
UNLIMITED = "Interno — Illimitato"


def _unlimited_plan():
    """Il piano che la migrazione 0055 semina in produzione. I test creano lo schema da SQLModel
    e non eseguono le migrazioni, quindi qui va creato a mano."""
    with Session(db.engine) as session:
        plan = session.exec(select(db.Plan).where(db.Plan.name == UNLIMITED)).first()
        if not plan:
            plan = db.Plan(name=UNLIMITED, code=billing.UNLIMITED_PLAN_CODE, internal=True,
                           price_cents=0, yearly_price_cents=0,
                           chat_rate_limit=600, ingest_rate_limit=600,
                           monthly_message_limit=0, max_live_origins=0)
            session.add(plan)
            session.commit()
            session.refresh(plan)
        return plan.id


def _our_tenant(client, plan_id, name="WP AIssistant"):
    created = client.post("/admin/clients", headers=ADMIN,
                          json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    with Session(db.engine) as session:
        row = session.get(db.Client, created["id"])
        row.plan_id = plan_id
        row.billing_status = "active"
        row.created_at = datetime.utcnow() - timedelta(days=1)
        session.add(row)
        session.commit()
    return created


# ---- il piano ---------------------------------------------------------------------------------


def test_the_unlimited_plan_is_internal_and_free(client):
    plan_id = _unlimited_plan()
    with Session(db.engine) as session:
        plan = session.get(db.Plan, plan_id)

    assert plan.internal is True
    assert plan.price_cents == 0 and plan.yearly_price_cents == 0
    # 0 non è "zero messaggi": è la semantica di illimitato, la stessa di monthly_message_limit
    assert plan.monthly_message_limit == 0
    assert plan.max_live_origins == 0


def test_a_free_internal_plan_is_accepted_where_a_free_product_is_not(client):
    """La validazione «niente piani gratuiti» esenta gli interni: prezzare un piano interno per
    farlo passare da un controllo è il modo di farlo sembrare acquistabile — è già successo, ed
    è la ragione della migrazione 0053."""
    _unlimited_plan()  # non solleva

    refused = client.post("/admin/plans", headers=ADMIN,
                          json={"name": "Regalo", "price_cents": 0, "yearly_price_cents": 0})
    assert refused.status_code == 400


def test_the_unlimited_plan_is_hidden_from_customers(client, tenant):
    _unlimited_plan()

    assert UNLIMITED not in [p["name"] for p in client.get("/billing/plans", headers=tenant["op"]).json()]
    assert UNLIMITED not in [p["name"] for p in client.get("/public/plans").json()]


def test_the_superadmin_still_sees_it(client):
    _unlimited_plan()

    names = [p["name"] for p in client.get("/admin/plans", headers=ADMIN).json()]
    assert UNLIMITED in names


def test_a_new_account_never_lands_on_the_unlimited_plan(client):
    """`billing.default_plan_id()` sceglie il piano con **l'id più basso**, non "quello interno".
    Oggi funziona perché il segnaposto nasce per primo, ma è una proprietà fragile: senza questo
    test un riordino dei piani regalerebbe accesso illimitato a ogni nuovo iscritto."""
    unlimited = _unlimited_plan()

    created = client.post("/admin/clients", headers=ADMIN, json={"name": "Nuovo"}).json()

    with Session(db.engine) as session:
        assert session.get(db.Client, created["id"]).plan_id != unlimited


# ---- il nostro tenant non falsa le viste commerciali -------------------------------------------


def test_our_tenant_is_not_counted_as_revenue(client, tenant):
    plan_id = _unlimited_plan()
    _our_tenant(client, plan_id)

    with Session(db.engine) as session:
        summary = billing.revenue_summary(session)

    assert "WP AIssistant" not in [row["name"] for row in summary.get("past_due", [])]
    assert all(entry.get("plan") != UNLIMITED for entry in summary.get("by_plan", {}).values()) \
        or UNLIMITED not in summary.get("by_plan", {})


def test_our_tenant_is_not_in_the_activation_funnel(client, tenant):
    """Un tenant nostro non è un cliente da attivare: contarlo falserebbe ogni tasso."""
    plan_id = _unlimited_plan()
    _our_tenant(client, plan_id)

    with Session(db.engine) as session:
        before = growth.activation_funnel(session)
        session.exec(select(db.Client)).all()

    # la coorte contiene il tenant di prova, non il nostro
    assert before["cohort"] == 1


def test_our_tenant_is_never_at_risk(client, tenant):
    plan_id = _unlimited_plan()
    ours = _our_tenant(client, plan_id)

    with Session(db.engine) as session:
        at_risk = growth.at_risk_clients(session)

    assert ours["id"] not in [row["client_id"] for row in at_risk["clients"]]


def test_our_spend_is_declared_apart_and_never_folded_into_the_margin(client, tenant):
    """La spesa esiste e non va nascosta — sostenere il widget sul nostro sito costa — ma non è
    un margine negativo del parco clienti: è costo di piattaforma."""
    plan_id = _unlimited_plan()
    ours = _our_tenant(client, plan_id)
    with Session(db.engine) as session:
        session.add(db.ModelPrice(model="test-model", input_millicents_per_million=1_000_000,
                                  output_millicents_per_million=1_000_000, currency="eur"))
        for client_id in (ours["id"], tenant["cid"]):
            conv = db.Conversation(client_id=client_id, visitor_id="v", channel="web")
            session.add(conv)
            session.commit()
            session.refresh(conv)
            session.add(db.AiResponseLog(
                client_id=client_id, conversation_id=conv.id, outcome="answered",
                model="test-model", tokens_prompt=1_000_000, tokens_completion=1_000_000,
            ))
        session.commit()
        summary = costs.cost_summary(session)

    assert ours["id"] not in [row["client_id"] for row in summary["clients"]]
    assert ours["id"] in [row["client_id"] for row in summary["internal_clients"]]
    assert summary["internal_cost_cents"] > 0
    # la nostra spesa non deve comparire nel costo del parco clienti
    assert summary["monthly_cost_cents"] < summary["monthly_cost_cents"] + summary["internal_cost_cents"]


def test_a_tenant_on_the_placeholder_plan_is_still_counted(client, tenant):
    """La controprova che conta, e la distinzione che è facile sbagliare.

    Anche il segnaposto «Nessun abbonamento» è un piano `internal`, ma sopra ci sta **chi si è
    registrato e non ha ancora pagato**: cioè esattamente la popolazione che il funnel di
    attivazione esiste per misurare. Escludere ogni piano interno svuoterebbe la vista invece di
    ripulirla — e la svuoterebbe in silenzio, mostrando zero al posto di un numero.
    """
    ours = _our_tenant(client, _unlimited_plan())

    with Session(db.engine) as session:
        placeholder = session.get(db.Client, tenant["cid"])
        plan = session.get(db.Plan, placeholder.plan_id)
        assert plan.internal is True and plan.code == billing.BOOTSTRAP_PLAN_CODE
        # gli si dà un motivo di rischio vero — registrato da dieci giorni e mai usato — così
        # comparire nell'elenco prova che viene valutato, invece di essere assente per caso
        placeholder.created_at = datetime.utcnow() - timedelta(days=10)
        session.add(placeholder)
        session.commit()
        funnel = growth.activation_funnel(session)
        at_risk = growth.at_risk_clients(session)

    assert funnel["cohort"] == 1  # il tenant di prova c'è
    assert ours["id"] not in [row["client_id"] for row in at_risk["clients"]]
    assert tenant["cid"] in [row["client_id"] for row in at_risk["clients"]]

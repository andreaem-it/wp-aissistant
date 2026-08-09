"""Il listino: nessun piano gratuito, e il segnaposto interno non è un prodotto.

Il piano seminato all'inizio serve solo a dare dei limiti a un account che esiste prima di aver
pagato: `Client.plan_id` non è nullable. Per un breve periodo gli è stato messo un prezzo di 1 €
per farlo passare dal controllo "niente piani gratuiti", lasciandogli i messaggi illimitati —
diventando così un prodotto apparente che rendeva insensato il piano vero a 19 €/500 messaggi, e
che i clienti vedevano nella loro vista di fatturazione. Questi test fissano il confine.
"""
from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _internal_plan(cid=None):
    with Session(db.engine) as session:
        return session.exec(select(db.Plan).where(db.Plan.internal.is_(True))).first()


def _make_internal(plan_id):
    with Session(db.engine) as session:
        plan = session.get(db.Plan, plan_id)
        plan.internal = True
        plan.price_cents = 0
        plan.yearly_price_cents = 0
        session.add(plan)
        session.commit()


# ---- nessun piano gratuito ---------------------------------------------------------------


def test_a_plan_free_on_both_intervals_is_refused(client):
    response = client.post("/admin/plans", headers=ADMIN,
                           json={"name": "Regalo", "price_cents": 0, "yearly_price_cents": 0})

    assert response.status_code == 400


def test_a_monthly_only_plan_is_fine(client):
    """Un piano non offerto ad anno è legittimo: è la gratuità totale a non esserlo."""
    response = client.post("/admin/plans", headers=ADMIN,
                           json={"name": "Solo mensile", "price_cents": 1900, "yearly_price_cents": 0})

    assert response.status_code == 200


def test_a_yearly_only_plan_is_fine(client):
    response = client.post("/admin/plans", headers=ADMIN,
                           json={"name": "Solo annuale", "price_cents": 0, "yearly_price_cents": 19000})

    assert response.status_code == 200


def test_a_plan_cannot_be_zeroed_out_by_an_update(client):
    plan = client.post("/admin/plans", headers=ADMIN,
                       json={"name": "Pro", "price_cents": 1900}).json()

    response = client.post(f"/admin/plans/{plan['id']}", headers=ADMIN,
                           json={"price_cents": 0, "yearly_price_cents": 0})

    assert response.status_code == 400


# ---- il segnaposto interno ---------------------------------------------------------------


def test_the_internal_plan_may_be_free(client, tenant):
    """Non è un prodotto: dargli un prezzo per superare il controllo lo farebbe sembrare
    acquistabile, che è esattamente il difetto da evitare."""
    internal = _internal_plan()
    if internal is None:  # database di test: il primo piano fa da segnaposto
        first = client.get("/admin/plans", headers=ADMIN).json()[0]
        _make_internal(first["id"])
        internal = _internal_plan()

    response = client.post(f"/admin/plans/{internal.id}", headers=ADMIN,
                           json={"price_cents": 0, "yearly_price_cents": 0})

    assert response.status_code == 200


def test_the_internal_plan_is_hidden_from_the_customer_billing_view(client, tenant):
    first = client.get("/admin/plans", headers=ADMIN).json()[0]
    _make_internal(first["id"])
    client.post("/admin/plans", headers=ADMIN, json={"name": "Pro", "price_cents": 1900})

    listed = client.get("/billing/plans", headers=tenant["op"]).json()

    names = [p["name"] for p in listed]
    assert first["name"] not in names, "il segnaposto interno era visibile al cliente"
    assert "Pro" in names


def test_the_internal_plan_is_hidden_from_the_public_signup_page(client, tenant):
    first = client.get("/admin/plans", headers=ADMIN).json()[0]
    _make_internal(first["id"])

    listed = client.get("/public/plans").json()

    assert first["name"] not in [p["name"] for p in listed]


def test_the_superadmin_still_sees_it(client, tenant):
    """Va gestito da qualche parte: nascosto ovunque sarebbe un piano fantasma."""
    first = client.get("/admin/plans", headers=ADMIN).json()[0]
    _make_internal(first["id"])

    listed = client.get("/admin/plans", headers=ADMIN).json()

    row = next(p for p in listed if p["id"] == first["id"])
    assert row["internal"] is True


# ---- modifica dal pannello ---------------------------------------------------------------


def test_a_plan_can_be_edited(client):
    """L'endpoint esisteva già ma il pannello non lo usava: un prezzo sbagliato obbligava a
    toccare il database."""
    plan = client.post("/admin/plans", headers=ADMIN,
                       json={"name": "Pro", "price_cents": 1900}).json()

    response = client.post(f"/admin/plans/{plan['id']}", headers=ADMIN, json={
        "name": "Pro annuale", "price_cents": 1900, "yearly_price_cents": 19000,
        "monthly_message_limit": 500, "stripe_price_id": "price_x",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Pro annuale"
    assert body["yearly_price_cents"] == 19000
    assert body["monthly_message_limit"] == 500

"""Impostazioni WooCommerce nella knowledge base, e svuotamento della base.

Sono la risposta autorevole a «quali sono i metodi di spedizione/pagamento?»: senza, il modello
rispondeva da conoscenza generale e inventava corrieri e prezzi.
"""
from sqlmodel import Session, select

from app import db
from app.woocommerce import render_settings
from conftest import TENANT_ORIGIN

SETTINGS = {
    "currency": "EUR",
    "shipping_zones": [
        {"name": "Italia", "methods": [
            {"title": "Corriere espresso", "cost": "7"},
            {"title": "Ritiro in negozio", "free": True},
        ]},
        {"name": "", "methods": [{"title": "Spedizione internazionale", "cost": "19"}]},
    ],
    "payment_gateways": [
        {"title": "Carta di credito", "description": "Visa, Mastercard"},
        {"title": "Bonifico bancario"},
    ],
    "free_shipping_from": "50",
}


# ---- Resa del testo ---------------------------------------------------------------------


def test_the_rendering_names_zones_methods_and_costs():
    text = render_settings(SETTINGS)

    assert "Spedizioni disponibili per Italia: Corriere espresso a 7 EUR" in text
    assert "Spedizione internazionale a 19 EUR" in text
    assert "Pagamenti accettati: Carta di credito (Visa, Mastercard); Bonifico bancario." in text
    assert "gratuita per ordini a partire da 50 EUR" in text


def test_each_line_is_a_sentence_the_model_can_quote():
    """Il testo è la materia prima del modello: se legge come un dump di configurazione, la
    risposta al visitatore legge così. Niente intestazioni amministrative, niente elenchi
    puntati che perdono senso staccati dal loro titolo."""
    text = render_settings(SETTINGS)

    assert "configurati in questo negozio" not in text
    assert not any(line.startswith("- ") for line in text.split("\n"))
    for line in [l for l in text.split("\n") if l.strip()]:
        assert line.endswith("."), f"non è una frase compiuta: {line}"


def test_a_free_method_says_so_in_words():
    """«0 EUR» si legge come un valore mancante; «gratuita» no."""
    text = render_settings(SETTINGS)

    # non "gratuita": l'aggettivo dovrebbe accordarsi col nome del metodo, di cui non
    # conosciamo il genere ("Ritiro" è maschile, "Consegna" femminile)
    assert "Ritiro in negozio senza costi di spedizione" in text
    assert "Ritiro in negozio (0" not in text


def test_a_zone_without_a_name_gets_one():
    text = render_settings({"shipping_zones": [{"methods": [{"title": "Standard"}]}]})

    # il ripiego è scritto per stare dentro la frase, articolo compreso
    assert "Spedizioni disponibili per il resto del mondo" in text


def test_nothing_configured_renders_nothing():
    """Una sezione vuota inviterebbe il modello a riempirla: è esattamente ciò che evitiamo."""
    assert render_settings({}) == ""
    assert render_settings({"shipping_zones": [], "payment_gateways": []}) == ""
    # una zona senza metodi non produce una riga a vuoto
    assert render_settings({"shipping_zones": [{"name": "Italia", "methods": []}]}) == ""


def test_only_public_facing_fields_are_rendered():
    """Questo testo finisce nel contesto di un modello che parla col pubblico."""
    text = render_settings({
        "currency": "EUR",
        "payment_gateways": [{
            "title": "Stripe", "description": "Carte", "api_key": "sk_live_segreto", "id": "stripe",
        }],
    })

    assert "Stripe" in text
    assert "sk_live_segreto" not in text
    assert "stripe" not in text.replace("Stripe", "")


# ---- Indicizzazione ---------------------------------------------------------------------


def test_settings_reach_the_knowledge_base(client, tenant, drain):
    response = client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    assert response.status_code == 200
    assert response.json()["indexed"] is True
    drain()

    with Session(db.engine) as session:
        chunks = session.exec(
            select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])
        ).all()

    assert chunks, "le impostazioni non sono state indicizzate"
    assert all(c.source == "woocommerce" for c in chunks)
    assert "Corriere espresso" in " ".join(c.text for c in chunks)


def test_resyncing_replaces_instead_of_stacking(client, tenant, drain):
    """Un metodo tolto in WooCommerce deve sparire dalle risposte, non restare accanto al nuovo."""
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": {
        "currency": "EUR",
        "shipping_zones": [{"name": "Italia", "methods": [{"title": "Posta ordinaria", "cost": "3"}]}],
    }})
    drain()

    with Session(db.engine) as session:
        text = " ".join(c.text for c in session.exec(
            select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])
        ).all())

    assert "Posta ordinaria" in text
    assert "Corriere espresso" not in text


def test_clearing_the_settings_removes_them(client, tenant, drain):
    """Se il negozio disattiva tutto, la base non deve conservare l'ultima versione buona."""
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()

    response = client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": {}})

    assert response.json()["indexed"] is False
    with Session(db.engine) as session:
        assert not session.exec(select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])).all()


def test_settings_are_tenant_scoped(client, tenant, drain):
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Altro", "allowed_origins": TENANT_ORIGIN}).json()
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()

    with Session(db.engine) as session:
        assert not session.exec(
            select(db.Chunk).where(db.Chunk.client_id == other["id"])
        ).all()


# ---- Svuotamento della knowledge base ----------------------------------------------------


def test_clearing_requires_the_confirmation_word(client, tenant, drain):
    """Lascia l'assistente senza nulla da cui rispondere: non deve poter partire per sbaglio."""
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()

    refused = client.request("DELETE", "/knowledge-base", headers=tenant["op"], json={"confirm": "si"})

    assert refused.status_code == 400
    with Session(db.engine) as session:
        assert session.exec(select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])).all()


def test_clearing_empties_chunks_and_products(client, tenant, drain):
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    client.post("/ingest/product", headers=tenant["key"], json={
        "url": "https://sito.it/p/1", "title": "Felpa", "price": "45", "description": "Cotone",
    })
    drain()

    response = client.request("DELETE", "/knowledge-base", headers=tenant["op"], json={"confirm": "svuota"})

    assert response.status_code == 200
    assert response.json()["removed_chunks"] > 0
    with Session(db.engine) as session:
        assert not session.exec(select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])).all()
        assert not session.exec(select(db.Product).where(db.Product.client_id == tenant["cid"])).all()


def test_clearing_never_crosses_tenants(client, tenant, drain):
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Vicino", "allowed_origins": TENANT_ORIGIN}).json()
    client.post("/ingest/woocommerce", headers={"Authorization": f"Bearer {other['api_key']}"},
                json={"settings": SETTINGS})
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()

    client.request("DELETE", "/knowledge-base", headers=tenant["op"], json={"confirm": "svuota"})

    with Session(db.engine) as session:
        assert session.exec(select(db.Chunk).where(db.Chunk.client_id == other["id"])).all()


def test_clearing_is_audited(client, tenant, drain):
    client.post("/ingest/woocommerce", headers=tenant["key"], json={"settings": SETTINGS})
    drain()
    client.request("DELETE", "/knowledge-base", headers=tenant["op"], json={"confirm": "svuota"})

    actions = [row["action"] for row in client.get(
        "/admin/audit", headers={"Authorization": "Bearer test-admin"}
    ).json()]

    assert "knowledge_base.cleared" in actions


def test_clearing_requires_an_operator(client, tenant):
    """La api_key sta nelle pagine pubbliche del widget: non deve poter svuotare nulla."""
    assert client.request(
        "DELETE", "/knowledge-base", headers=tenant["key"], json={"confirm": "svuota"}
    ).status_code in (401, 403)

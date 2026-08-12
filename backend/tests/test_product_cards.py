"""Le card prodotto lungo il percorso reale.

I test esistenti o sostituiscono `retrieve_products`, o girano con l'embedder finto di conftest
che restituisce vettori a zero — fra due vettori nulli la distanza coseno non è definita, quindi
nessun prodotto supera mai la soglia. Il risultato è che il recupero vero non era coperto da
nulla: una regressione lì sarebbe arrivata al cliente senza che un test se ne accorgesse.

Qui l'embedder è finto ma **discriminante**: vettori diversi per testi diversi, così le distanze
hanno un ordine e la soglia significa qualcosa.
"""
import hashlib

import pytest
from sqlmodel import Session, select

from app import db
from conftest import TENANT_ORIGIN


def _fake_embed(text: str):
    """Vettore deterministico e normalizzato, vicino per testi che condividono parole.

    Non è un modello: distribuisce le parole su poche dimensioni, abbastanza perché
    "felpa zip" e "avete felpe con zip?" finiscano vicini e "ombrello" lontano.
    """
    vec = [0.0] * db.EMBED_DIM
    for word in (text or "").lower().replace("?", " ").replace(",", " ").split():
        stem = word[:4]  # "felpa"/"felpe" cadono sullo stesso asse
        index = int(hashlib.sha256(stem.encode()).hexdigest(), 16) % db.EMBED_DIM
        vec[index] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm else [1.0] + [0.0] * (db.EMBED_DIM - 1)


@pytest.fixture
def real_retrieval(monkeypatch):
    from app import rag
    monkeypatch.setattr(rag, "embed", _fake_embed)
    monkeypatch.setattr("app.routers.widget.retrieve_products", rag.retrieve_products)
    return _fake_embed


def test_a_matching_product_comes_back_as_a_card(client, tenant, drain, real_retrieval):
    client.post("/ingest/product", headers=tenant["key"], json={
        "url": "https://sito.it/p/felpa", "title": "Felpa zip",
        "price": "45 EUR", "image_url": "https://sito.it/felpa.jpg", "description": "Felpa zip",
    })
    drain()

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "avete felpe con zip",
    }).json()

    assert body["products"], "nessuna card prodotto: il recupero non ha restituito nulla"
    card = body["products"][0]
    assert card["title"] == "Felpa zip"
    assert card["price"] == "45 EUR"
    assert card["product_url"] == "https://sito.it/p/felpa"


def test_an_unrelated_question_returns_no_card(client, tenant, drain, real_retrieval):
    """La soglia esiste per non mostrare un prodotto a caso sotto una domanda che non lo cerca."""
    client.post("/ingest/product", headers=tenant["key"], json={
        "url": "https://sito.it/p/felpa", "title": "Felpa zip", "price": "45 EUR",
        "description": "Felpa zip",
    })
    drain()

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "quali sono gli orari del supporto",
    }).json()

    assert body["products"] == []


def test_a_product_without_an_embedding_is_never_shown(client, tenant, real_retrieval):
    """Una riga non ancora indicizzata ha distanza NULL: va esclusa, non mostrata a distanza zero."""
    with Session(db.engine) as session:
        session.add(db.Product(
            client_id=tenant["cid"], product_url="https://sito.it/p/x",
            title="Non indicizzato", price="1", image_url="", embedding=None,
        ))
        session.commit()

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "non indicizzato",
    }).json()

    assert body["products"] == []


def test_cards_never_cross_tenants(client, tenant, drain, real_retrieval):
    admin = {"Authorization": "Bearer test-admin"}
    other = client.post("/admin/clients", headers=admin, json={"name": "Vicino", "allowed_origins": TENANT_ORIGIN}).json()
    client.post("/ingest/product", headers={"Authorization": f"Bearer {other['api_key']}"}, json={
        "url": "https://altro.it/p/felpa", "title": "Felpa zip", "price": "45 EUR",
        "description": "Felpa zip",
    })
    drain()

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "avete felpe con zip",
    }).json()

    assert body["products"] == []


def test_clearing_the_knowledge_base_removes_the_cards(client, tenant, drain, real_retrieval):
    """Il pulsante «Svuota» cancella anche i prodotti: dopo, le card spariscono finché non si
    risincronizza. È atteso, ed è la spiegazione più probabile se scompaiono all'improvviso."""
    client.post("/ingest/product", headers=tenant["key"], json={
        "url": "https://sito.it/p/felpa", "title": "Felpa zip", "price": "45 EUR",
        "description": "Felpa zip",
    })
    drain()
    assert client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "avete felpe con zip"}).json()["products"]

    client.request("DELETE", "/knowledge-base", headers=tenant["op"], json={"confirm": "svuota"})

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v2", "message": "avete felpe con zip"}).json()
    assert body["products"] == []


def test_a_product_match_alone_puts_the_question_in_scope(client, tenant, drain, real_retrieval):
    """`ingest_product` crea la scheda, non un chunk. Finché il guardiano di scope guardava solo
    i chunk, un negozio le cui schede non erano indicizzate anche come pagine si sentiva
    rispondere «non posso aiutarti» su un prodotto che ha davvero in catalogo — e quel percorso
    esce con `products: []`, card comprese. Una corrispondenza a catalogo è già la prova che la
    domanda riguarda questo negozio."""
    client.post("/ingest/product", headers=tenant["key"], json={
        "url": "https://sito.it/p/felpa", "title": "Felpa zip", "price": "45 EUR",
        "description": "Felpa zip",
    })
    drain()

    with Session(db.engine) as session:  # nessun chunk: solo catalogo
        assert not session.exec(
            select(db.Chunk).where(db.Chunk.client_id == tenant["cid"])
        ).all()

    body = client.post("/chat", headers=tenant["key"], json={
        "visitor_id": "v1", "message": "avete felpe con zip",
    }).json()

    from app.routers.widget import _out_of_scope_reply
    assert body["reply"] != _out_of_scope_reply(None)
    assert body["products"][0]["title"] == "Felpa zip"


def test_the_question_is_embedded_twice_and_no_more(client, tenant, drain, real_retrieval):
    """Due volte: una per i chunk, una per il catalogo — sono indici distinti. Il conteggio è
    fissato qui perché ogni embedding è una chiamata a pagamento sulla domanda del visitatore, e
    una terza si aggiunge senza farsi notare."""
    calls = []
    from app import rag
    original = rag.embed
    rag.embed = lambda text: (calls.append(text), original(text))[1]
    try:
        client.post("/chat", headers=tenant["key"], json={
            "visitor_id": "v1", "message": "avete felpe con zip",
        })
    finally:
        rag.embed = original

    assert calls.count("avete felpe con zip") == 2, f"embedding: {calls.count('avete felpe con zip')}"

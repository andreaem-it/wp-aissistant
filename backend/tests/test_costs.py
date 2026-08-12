"""Per-tenant AI cost and margin. The token counts come from AiResponseLog, which /chat writes
on every turn; here they are written directly so the numbers under test are exact."""
from datetime import datetime, timedelta

from sqlmodel import Session

from app import db
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _price(client, model, input_cents=0, output_cents=0, currency="eur"):
    """Prices are stated here in **cents** per million tokens because the expectations below are
    in cents; the API takes the provider's own figure (currency units), hence the /100."""
    return client.put("/admin/model-prices", headers=ADMIN, json={
        "model": model,
        "input_price_per_million": input_cents / 100,
        "output_price_per_million": output_cents / 100,
        "currency": currency,
    })


def _plan(client, name, price_cents=100, yearly_price_cents=0):
    return client.post("/admin/plans", headers=ADMIN, json={
        "name": name, "price_cents": price_cents, "yearly_price_cents": yearly_price_cents,
    }).json()["id"]


def _tenant(client, name, plan_id, *, status="active", interval="month"):
    created = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    with Session(db.engine) as session:
        row = session.get(db.Client, created["id"])
        row.plan_id = plan_id
        row.billing_status = status
        row.subscription_interval = interval
        session.add(row)
        session.commit()
    return created["id"]


def _turns(client_id, model, *, count=1, tokens_in=0, tokens_out=0, age_days=1):
    """Write AiResponseLog rows directly: the fake LLM in tests reports no realistic usage."""
    with Session(db.engine) as session:
        conv = db.Conversation(client_id=client_id, visitor_id="v1")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        for _ in range(count):
            session.add(db.AiResponseLog(
                client_id=client_id,
                conversation_id=conv.id,
                outcome="answered",
                model=model,
                tokens_prompt=tokens_in,
                tokens_completion=tokens_out,
                created_at=datetime.utcnow() - timedelta(days=age_days),
            ))
        session.commit()


# ---- Pricing ---------------------------------------------------------------------------------


def test_cost_is_priced_from_recorded_tokens(client):
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Acme", plan_id)
    # 200 cents per million in, 400 out -> 2M in = 400c, 1M out = 400c -> 800c
    _price(client, "llama-3", input_cents=200, output_cents=400)
    _turns(cid, "llama-3", tokens_in=2_000_000, tokens_out=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()
    row = data["clients"][0]

    assert row["cost_cents"] == 800.0
    assert row["monthly_revenue_cents"] == 10_000
    assert row["monthly_margin_cents"] == 9_200.0
    assert data["margin_pct"] == 92.0


def test_fractions_of_a_cent_are_not_rounded_away(client):
    """A single turn costs a fraction of a cent: rounding per turn would erase the spend."""
    plan_id = _plan(client, "Free")
    cid = _tenant(client, "Piccolo", plan_id)
    _price(client, "cheap", input_cents=100, output_cents=100)  # 1 cent per 10k tokens
    _turns(cid, "cheap", count=1000, tokens_in=1_000, tokens_out=0)

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    # 1000 turns x 1000 tokens = 1M tokens = 100 cents, not 0
    assert row["cost_cents"] == 100.0
    assert row["turns"] == 1000


def test_unpriced_model_is_reported_not_assumed_free(client):
    plan_id = _plan(client, "Pro", price_cents=5_000)
    cid = _tenant(client, "Ignoto", plan_id)
    _turns(cid, "modello-senza-listino", tokens_in=1_000_000, tokens_out=500_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["unpriced_models"] == ["modello-senza-listino"]
    assert data["clients"][0]["fully_priced"] is False
    # its spend is excluded from the total rather than counted as zero
    assert data["monthly_cost_cents"] == 0.0


def test_partially_priced_tenant_is_excluded_from_the_total(client):
    plan_id = _plan(client, "Pro", price_cents=5_000)
    cid = _tenant(client, "Misto", plan_id)
    _price(client, "noto", input_cents=1_000, output_cents=1_000)
    _turns(cid, "noto", tokens_in=1_000_000)
    _turns(cid, "ignoto", tokens_in=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["clients"][0]["fully_priced"] is False
    assert data["monthly_cost_cents"] == 0.0  # an incomplete total would understate the spend
    assert "ignoto" in data["unpriced_models"]


# ---- Window and normalisation ----------------------------------------------------------------


def test_window_cost_is_normalised_to_a_month(client):
    """Revenue is monthly, so a 90-day cost must be scaled before the two are compared."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Lungo", plan_id)
    _price(client, "m", input_cents=1_000, output_cents=0)
    _turns(cid, "m", tokens_in=9_000_000, age_days=40)  # 9000 cents, outside 30 days

    thirty = client.get("/admin/costs", headers=ADMIN, params={"days": 30}).json()
    ninety = client.get("/admin/costs", headers=ADMIN, params={"days": 90}).json()

    assert thirty["clients"] == []  # the turns are older than the window
    row = ninety["clients"][0]
    assert row["cost_cents"] == 9_000.0
    assert row["monthly_cost_cents"] == 3_000.0  # 9000 x 30/90


def test_window_is_bounded(client):
    assert client.get("/admin/costs", headers=ADMIN, params={"days": 0}).status_code == 400
    assert client.get("/admin/costs", headers=ADMIN, params={"days": 400}).status_code == 400


def test_clients_are_ranked_by_monthly_cost(client):
    plan_id = _plan(client, "Pro", price_cents=1_000)
    cheap = _tenant(client, "Poco", plan_id)
    pricey = _tenant(client, "Molto", plan_id)
    _price(client, "m", input_cents=1_000, output_cents=0)
    _turns(cheap, "m", tokens_in=1_000_000)
    _turns(pricey, "m", tokens_in=5_000_000)

    names = [r["name"] for r in client.get("/admin/costs", headers=ADMIN).json()["clients"]]

    assert names == ["Molto", "Poco"]


def test_revenue_counts_only_contracted_tenants(client):
    """A trialing tenant costs money but brings none yet: it must not inflate the margin."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    trial = _tenant(client, "Prova", plan_id, status="trialing")
    _price(client, "m", input_cents=100, output_cents=0)
    _turns(trial, "m", tokens_in=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["monthly_revenue_cents"] == 0
    assert data["clients"][0]["monthly_revenue_cents"] == 10_000  # what it would be worth


def test_yearly_subscriber_revenue_is_normalised(client):
    plan_id = _plan(client, "Annuale", price_cents=0, yearly_price_cents=120_000)
    cid = _tenant(client, "Anno", plan_id, interval="year")
    _price(client, "m", input_cents=100, output_cents=0)
    _turns(cid, "m", tokens_in=1_000_000)

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    assert row["monthly_revenue_cents"] == 10_000  # 120000/12, not 120000


def test_margin_pct_is_absent_without_revenue(client):
    # un tenant sospeso non produce ricavo: è il caso in cui la percentuale non è calcolabile
    plan_id = _plan(client, "Sospeso")
    cid = _tenant(client, "Senza ricavo", plan_id, status="canceled")
    _price(client, "m", input_cents=100, output_cents=0)
    _turns(cid, "m", tokens_in=1_000_000)

    # no revenue means no percentage: a division by zero must not become "0%"
    assert client.get("/admin/costs", headers=ADMIN).json()["margin_pct"] is None


# ---- Price list management --------------------------------------------------------------------


def test_price_upsert_replaces_by_model_name(client):
    assert _price(client, "gpt", input_cents=100, output_cents=200).status_code == 200
    assert _price(client, "gpt", input_cents=250, output_cents=500).status_code == 200

    rows = client.get("/admin/model-prices", headers=ADMIN).json()

    assert len(rows) == 1
    assert rows[0]["input_price_per_million"] == 2.5


def test_price_validation(client):
    assert _price(client, "  ").status_code == 400
    assert _price(client, "x", input_cents=-1).status_code == 400
    assert client.put("/admin/model-prices", headers=ADMIN,
                      json={"model": "x", "currency": "euro"}).status_code == 400


def test_price_can_be_deleted(client):
    created = _price(client, "obsoleto", input_cents=10).json()

    assert client.delete(f"/admin/model-prices/{created['id']}", headers=ADMIN).status_code == 200
    assert client.get("/admin/model-prices", headers=ADMIN).json() == []
    assert client.delete(f"/admin/model-prices/{created['id']}", headers=ADMIN).status_code == 404


def test_price_changes_are_audited(client):
    _price(client, "tracciato", input_cents=10)

    actions = [row["action"] for row in client.get("/admin/audit", headers=ADMIN).json()]

    assert "model_price.set" in actions


# ---- Access ------------------------------------------------------------------------------------


def test_costs_require_the_admin_key(client, tenant):
    """Cross-tenant: costs span every client, so an operator token must never reach them."""
    assert client.get("/admin/costs", headers=tenant["op"]).status_code in (401, 403)
    assert client.get("/admin/costs").status_code in (401, 403)
    assert client.get("/admin/model-prices", headers=tenant["op"]).status_code in (401, 403)
    assert client.put("/admin/model-prices", headers=tenant["op"],
                      json={"model": "x"}).status_code in (401, 403)


# ---- Provider figures survive the round trip ---------------------------------------------------


def test_published_price_is_stored_without_rounding(client):
    """Cloudflare quotes $0.152 per M input: storing 0.15 would be a 1% error on every turn."""
    client.put("/admin/model-prices", headers=ADMIN, json={
        "model": "@cf/meta/llama-3.1-8b-instruct-fp8",
        "input_price_per_million": 0.152,
        "output_price_per_million": 0.287,
        "currency": "usd",
    })

    row = client.get("/admin/model-prices", headers=ADMIN).json()[0]

    assert row["input_price_per_million"] == 0.152
    assert row["output_price_per_million"] == 0.287
    assert row["currency"] == "usd"


def test_sub_cent_price_is_not_rounded_to_zero(client):
    """An embedding model at $0.012/M would round to a whole cent — a 17% error."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Fine", plan_id)
    client.put("/admin/model-prices", headers=ADMIN, json={
        "model": "bge", "input_price_per_million": 0.012, "output_price_per_million": 0,
    })
    _turns(cid, "bge", tokens_in=100_000_000)  # 100M tokens x $0.012/M = $1.20 = 120 cents

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    assert row["cost_cents"] == 120.0


def test_cost_of_the_real_cloudflare_price(client):
    """End to end on the numbers actually published for the model this product runs on."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Reale", plan_id)
    client.put("/admin/model-prices", headers=ADMIN, json={
        "model": "llama-fp8",
        "input_price_per_million": 0.152,
        "output_price_per_million": 0.287,
    })
    _turns(cid, "llama-fp8", tokens_in=10_000_000, tokens_out=2_000_000)

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    # 10M x $0.152 = $1.52 ; 2M x $0.287 = $0.574 ; total $2.094 = 209.4 cents
    assert row["cost_cents"] == 209.4


# ---- Currency ----------------------------------------------------------------------------------


def test_costs_flag_a_currency_mismatch_instead_of_converting(client):
    """A USD price list against EUR plans is two units, not a margin. Say so."""
    plan_id = _plan(client, "Euro", price_cents=10_000)  # plans default to eur
    cid = _tenant(client, "Misto", plan_id)
    _price(client, "usd-model", input_cents=100, currency="usd")
    _turns(cid, "usd-model", tokens_in=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["mixed_currencies"] is True
    assert data["currency"] is None
    assert data["currencies"] == ["eur", "usd"]
    # a percentage across two currencies would be meaningless
    assert data["margin_pct"] is None


def test_costs_report_a_single_currency_when_they_agree(client):
    plan_id = _plan(client, "Euro", price_cents=10_000)
    cid = _tenant(client, "Coerente", plan_id)
    _price(client, "eur-model", input_cents=100, currency="eur")
    _turns(cid, "eur-model", tokens_in=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["mixed_currencies"] is False
    assert data["currency"] == "eur"
    assert data["margin_pct"] == 99.0


# ---- Embedding and storage --------------------------------------------------------------------


def _embedded(client_id, model, *, ingest_chars=0, query_chars=0, tokens=0, age_days=1):
    """Write the daily rollup directly: the fake embedder in tests measures nothing."""
    from datetime import date
    with Session(db.engine) as session:
        day = (datetime.utcnow() - timedelta(days=age_days)).date()
        row = db.EmbeddingUsage(
            client_id=client_id, model=model, day=day,
            ingest_chars=ingest_chars, query_chars=query_chars, tokens=tokens, requests=1,
        )
        session.add(row)
        session.commit()
    assert isinstance(day, date)


def _attachment(client_id, size_bytes, key=""):
    # size_bytes is a 32-bit column, which is fine in production because uploads are capped at
    # MAX_UPLOAD_BYTES (10 MB); only the SUM across a tenant can be large, and Postgres returns
    # that as a bigint. Tests therefore build totals from several realistic rows.
    with Session(db.engine) as session:
        conv = db.Conversation(client_id=client_id, visitor_id="v")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        msg = db.Message(conversation_id=conv.id, role="user", content="x")
        session.add(msg)
        session.commit()
        session.refresh(msg)
        session.add(db.Attachment(
            client_id=client_id, conversation_id=conv.id, message_id=msg.id,
            object_key=f"k{client_id}-{size_bytes}-{key}", filename="a.pdf",
            content_type="application/pdf", size_bytes=size_bytes,
        ))
        session.commit()


def test_embedding_cost_is_counted(client):
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Acme", plan_id)
    _price(client, "bge", input_cents=100)  # 1 EUR per million tokens
    # 4M chars / 4 chars-per-token = 1M tokens = 100 cents
    _embedded(cid, "bge", ingest_chars=3_000_000, query_chars=1_000_000)

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    assert row["embedding_cost_cents"] == 100.0
    assert row["embedding_chars"] == 4_000_000
    assert row["cost_cents"] == 100.0  # nessun turno di chat: è tutto embedding


def test_reported_tokens_beat_the_estimate(client):
    """When the provider tells us the tokens we use them: the ratio is only a fallback."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Esatto", plan_id)
    _price(client, "bge", input_cents=100)
    # chars would estimate 1M tokens, but the provider reported half that
    _embedded(cid, "bge", ingest_chars=4_000_000, tokens=500_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["clients"][0]["embedding_cost_cents"] == 50.0
    assert data["clients"][0]["embedding_estimated"] is False
    assert data["embedding_estimated"] is False


def test_an_estimated_cost_says_so(client):
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Stimato", plan_id)
    _price(client, "bge", input_cents=100)
    _embedded(cid, "bge", ingest_chars=4_000_000)  # nessun token riportato

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert data["clients"][0]["embedding_estimated"] is True
    assert data["embedding_estimated"] is True
    assert data["chars_per_token"] == 4.0


def test_an_unpriced_embedding_model_is_reported(client):
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Ignoto", plan_id)
    _embedded(cid, "modello-senza-listino", ingest_chars=1_000_000)

    data = client.get("/admin/costs", headers=ADMIN).json()

    assert "modello-senza-listino" in data["unpriced_models"]
    assert data["clients"][0]["fully_priced"] is False
    assert data["monthly_cost_cents"] == 0.0


def test_embedding_respects_the_window(client):
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Vecchio", plan_id)
    _price(client, "bge", input_cents=100)
    _embedded(cid, "bge", ingest_chars=4_000_000, age_days=60)

    narrow = client.get("/admin/costs", headers=ADMIN, params={"days": 30}).json()
    wide = client.get("/admin/costs", headers=ADMIN, params={"days": 90}).json()

    assert narrow["clients"] == []
    assert wide["clients"][0]["embedding_cost_cents"] == 100.0


def test_storage_is_unpriced_until_configured(client, monkeypatch):
    """No price means unknown, not free: the field is null and the total stays without it."""
    from app import costs
    monkeypatch.setattr(costs, "STORAGE_MILLICENTS_PER_GB_MONTH", None)
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Archivio", plan_id)
    _attachment(cid, 1024 ** 3)

    data = client.get("/admin/costs", headers=ADMIN).json()
    row = next(r for r in data["clients"] if r["client_id"] == cid)

    assert data["storage_priced"] is False
    assert row["storage_cost_cents"] is None
    assert row["storage_bytes"] == 1024 ** 3


def test_storage_is_priced_per_gb_month(client, monkeypatch):
    from app import costs
    # 1500 millicents = 1.5 cents per GB-month
    monkeypatch.setattr(costs, "STORAGE_MILLICENTS_PER_GB_MONTH", 1500)
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Archivio", plan_id)
    _attachment(cid, 1024 ** 3, key="a")
    _attachment(cid, 1024 ** 3, key="b")

    data = client.get("/admin/costs", headers=ADMIN).json()
    row = next(r for r in data["clients"] if r["client_id"] == cid)

    assert data["storage_priced"] is True
    assert row["storage_cost_cents"] == 3.0  # 2 GB x 1.5 centesimi
    assert data["storage_bytes"] == 2 * 1024 ** 3


def test_storage_is_not_scaled_by_the_window(client, monkeypatch):
    """Storage is a stock already expressed per month: scaling it like a flow would triple it."""
    from app import costs
    monkeypatch.setattr(costs, "STORAGE_MILLICENTS_PER_GB_MONTH", 1000)
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Stock", plan_id)
    _attachment(cid, 1024 ** 3)

    thirty = client.get("/admin/costs", headers=ADMIN, params={"days": 30}).json()
    ninety = client.get("/admin/costs", headers=ADMIN, params={"days": 90}).json()

    assert thirty["clients"][0]["monthly_cost_cents"] == 1.0
    assert ninety["clients"][0]["monthly_cost_cents"] == 1.0


def test_ingest_and_query_embeddings_are_both_counted(client):
    """The chat embeds every question: leaving queries out would understate a busy tenant."""
    plan_id = _plan(client, "Pro", price_cents=10_000)
    cid = _tenant(client, "Traffico", plan_id)
    _price(client, "bge", input_cents=100)
    _embedded(cid, "bge", ingest_chars=2_000_000, query_chars=2_000_000)

    row = client.get("/admin/costs", headers=ADMIN).json()["clients"][0]

    assert row["embedding_chars"] == 4_000_000
    assert row["embedding_cost_cents"] == 100.0


def test_ingest_actually_records_usage(client, tenant, drain):
    """Il percorso reale, non il rollup scritto a mano.

    record_embedding è best-effort e inghiotte le eccezioni, così un errore al suo interno non
    fa fallire un ingest o una risposta al visitatore. Il prezzo di quella scelta è che un bug
    lì dentro non si vede: senza questo test la misurazione può smettere di funzionare in
    silenzio, ed è esattamente quello che è successo la prima volta.
    """
    from sqlmodel import select
    from app.llm import EMBED_MODEL

    client.post(
        "/ingest/site-page",
        headers=tenant["key"],
        json={"url": "https://sito.it/spedizioni", "text": "Le spedizioni partono in 24 ore. " * 20},
    )
    drain()

    with Session(db.engine) as session:
        rows = session.exec(
            select(db.EmbeddingUsage).where(db.EmbeddingUsage.client_id == tenant["cid"])
        ).all()

    assert rows, "l'ingest non ha registrato alcun uso di embedding"
    assert rows[0].model == EMBED_MODEL
    assert rows[0].ingest_chars > 0
    assert rows[0].query_chars == 0


def test_a_chat_question_records_query_usage(client, tenant, drain):
    """Anche la domanda del visitatore viene embeddata: se non risultasse, il costo di un
    tenant con molto traffico sarebbe sistematicamente sottostimato."""
    from sqlmodel import select

    client.post(
        "/ingest/site-page",
        headers=tenant["key"],
        json={"url": "https://sito.it/resi", "text": "I resi si accettano entro 30 giorni."},
    )
    drain()
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v1", "message": "Come funzionano i resi?"})

    with Session(db.engine) as session:
        row = session.exec(
            select(db.EmbeddingUsage).where(db.EmbeddingUsage.client_id == tenant["cid"])
        ).first()

    assert row.query_chars > 0

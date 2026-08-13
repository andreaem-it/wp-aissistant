"""L'assistente dentro il pannello del cliente.

Due tenant nella stessa conversazione: **noi rispondiamo**, il cliente **è l'argomento**. Tutto
ciò che questi test presidiano discende da lì.

Il rischio non è che la funzione non parta — quello si vede subito. È che parta *troppo*: che il
contesto di un tenant finisca nella conversazione di un altro, che un token falso venga creduto,
o che il blocco dei dati account cresca fino a diventare un dump del database dentro il prompt di
un modello. Nessuno dei tre fa rumore.
"""
import base64
import json
from datetime import datetime, timedelta

import pytest
from sqlmodel import Session, select

from app import billing, db, panel_assistant
from app.rag import build_system
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}
SECRET = "s" * 40


@pytest.fixture
def signed(monkeypatch):
    """Il segreto di firma configurato. Letto a ogni chiamata, non all'import: è ciò che rende
    monkeypatchabile una funzione che in produzione si accende con una variabile d'ambiente."""
    monkeypatch.setenv(panel_assistant.SECRET_ENV, SECRET)


# ---- La firma -----------------------------------------------------------------------------------


def test_a_token_we_issued_verifies(signed):
    token = panel_assistant.issue_token(client_id=7, operator_id=3)
    payload = panel_assistant.verify_token(token)

    assert payload["client_id"] == 7
    assert payload["operator_id"] == 3


def test_a_tampered_payload_is_rejected(signed):
    """Il payload è leggibile per costruzione — firmare non è cifrare. Deve essere *inalterabile*,
    che è la proprietà che serve: il `client_id` decide di chi si parla."""
    token = panel_assistant.issue_token(client_id=7, operator_id=3)
    payload_b64, _, signature = token.partition(".")
    stolen = json.loads(base64.b64decode(payload_b64))
    stolen["client_id"] = 999
    forged = base64.b64encode(json.dumps(stolen).encode()).decode()

    assert panel_assistant.verify_token(f"{forged}.{signature}") is None


def test_a_token_signed_with_another_secret_is_rejected(monkeypatch):
    monkeypatch.setenv(panel_assistant.SECRET_ENV, "a" * 40)
    token = panel_assistant.issue_token(client_id=7, operator_id=3)
    monkeypatch.setenv(panel_assistant.SECRET_ENV, "b" * 40)

    assert panel_assistant.verify_token(token) is None


def test_an_expired_token_is_rejected(signed):
    token = panel_assistant.issue_token(client_id=7, operator_id=3)
    later = datetime.utcnow() + timedelta(seconds=panel_assistant.TOKEN_TTL_SECONDS + 1)

    assert panel_assistant.verify_token(token, now=later) is None


def test_without_a_secret_nothing_verifies(monkeypatch):
    """Spenta, non insicura. Un segreto assente deve rendere la funzione inerte: se la verifica
    accettasse quando non c'è nulla con cui verificare, il caso «non configurato» diventerebbe il
    caso «chiunque può dire di essere chiunque», e in produzione si nota solo dopo."""
    monkeypatch.setenv(panel_assistant.SECRET_ENV, "")

    assert panel_assistant.configured() is False
    assert panel_assistant.verify_token("qualsiasi.cosa") is None


def test_garbage_does_not_raise(signed):
    for rubbish in [None, "", "senza-punto", "a.b", "...", "x" * 5000]:
        assert panel_assistant.verify_token(rubbish) is None


# ---- L'emissione --------------------------------------------------------------------------------


def test_the_token_endpoint_needs_an_operator_session(client, tenant, signed):
    assert client.post("/panel/assistant/token").status_code == 401
    assert client.post("/panel/assistant/token", headers=tenant["key"]).status_code == 401


def test_the_token_is_bound_to_the_operator_own_tenant(client, tenant, signed):
    """Nessun parametro in ingresso, ed è il punto: un endpoint che accetta il tenant di cui
    parlare è un endpoint che lo concede."""
    res = client.post("/panel/assistant/token", headers=tenant["op"])

    assert res.status_code == 200
    payload = panel_assistant.verify_token(res.json()["token"])
    assert payload["client_id"] == tenant["cid"]


def test_without_a_secret_the_endpoint_says_so(client, tenant, monkeypatch):
    monkeypatch.setenv(panel_assistant.SECRET_ENV, "")
    res = client.post("/panel/assistant/token", headers=tenant["op"])

    assert res.status_code == 503


# ---- Il contesto: whitelist, non dump -------------------------------------------------------------


ALLOWED_FIELDS = {
    "piano",
    "stato_abbonamento",
    "documenti_indicizzati",
    "pagine_sito_indicizzate",
    "ultimo_ingest",
    "siti_registrati",
    "plugin_verificato",
    "canali_attivi",
    "conversazioni_aperte",
    "conversazioni_in_attesa_di_risposta",
}


def test_the_context_is_exactly_the_allowed_fields(client, tenant):
    """Questo test fallisce quando qualcuno *aggiunge* un campo, ed è voluto: un campo nuovo nel
    prompt di un modello è una decisione, non un dettaglio d'implementazione."""
    with Session(db.engine) as session:
        dati = panel_assistant.describe_client(session, tenant["cid"])

    assert set(dati) == ALLOWED_FIELDS


def test_the_context_never_carries_conversation_or_contact_content(client, tenant):
    """Il confine vero. Ciò che l'assistente deve sapere è *quante* conversazioni aspettano, mai
    cosa dicono — e il modo per verificarlo è mettere nel database qualcosa di riconoscibile e
    non trovarlo da nessuna parte nel blocco che finisce nel prompt."""
    segreto = "SEGRETO-DA-NON-VEDERE-MAI"
    client.post(
        "/chat",
        headers=tenant["key"],
        json={"visitor_id": "v1", "message": segreto},
    )
    with Session(db.engine) as session:
        conv = session.exec(select(db.Conversation)).first()
        # Il contatto lo crea già `/chat`: qui gli si dà un nome riconoscibile, che è il punto.
        contatto = session.exec(select(db.Contact)).first()
        contatto.name = "Mario Rossi"
        contatto.email = "mario@example.com"
        session.add(contatto)
        session.commit()
        dati = panel_assistant.describe_client(session, tenant["cid"])
        blocco = panel_assistant.context_block(dati)

    assert conv is not None
    for vietato in (segreto, "Mario Rossi", "mario@example.com", tenant["api_key"]):
        assert vietato not in blocco


def test_the_context_counts_registered_sites_not_observed_ones(client, tenant):
    """Un `observed` è la traccia di un dominio visto passare, non un permesso. Contarlo qui
    farebbe rispondere «il sito è registrato» proprio a chi ha il problema opposto."""
    with Session(db.engine) as session:
        session.add(db.ClientOrigin(
            client_id=tenant["cid"], origin="https://visto.example", host="visto.example",
            kind="observed", source="traffic",
        ))
        session.commit()
        prima = panel_assistant.describe_client(session, tenant["cid"])["siti_registrati"]

        session.add(db.ClientOrigin(
            client_id=tenant["cid"], origin="https://vero.example", host="vero.example",
            kind="live", source="panel",
        ))
        session.commit()
        dopo = panel_assistant.describe_client(session, tenant["cid"])["siti_registrati"]

    assert dopo == prima + 1


def test_an_unknown_tenant_has_no_context(client):
    with Session(db.engine) as session:
        assert panel_assistant.describe_client(session, 999_999) is None


# ---- Il prompt ------------------------------------------------------------------------------------


def test_the_account_block_widens_the_grounding_rule():
    """Un blocco di fatti che il prompt vieta di enunciare verrebbe ignorato, o — peggio —
    obbedito a metà. Se i dati account entrano, la regola di grounding deve nominarli."""
    account = panel_assistant.context_block({"piano": "Pro", "siti_registrati": 0})
    prompt = build_system(["Si installa dal pannello."], None, "WP AIssistant", account=account)

    assert "ACCOUNT DATA" in prompt
    assert "or in the ACCOUNT DATA section" in prompt
    assert prompt.index("ACCOUNT DATA") < prompt.index("Context:")


def test_without_an_account_the_prompt_is_unchanged():
    """La stragrande maggioranza delle conversazioni non ha un account: non devono vedere né un
    blocco vuoto né una regola di grounding allargata a una sezione che non esiste."""
    prompt = build_system(["Si installa dal pannello."], None, "WP AIssistant")

    assert "ACCOUNT DATA" not in prompt
    assert "MUST appear verbatim in the context below." in prompt


def test_booleans_and_empty_lists_are_readable():
    blocco = panel_assistant.context_block({
        "plugin_verificato": False, "canali_attivi": [], "ultimo_ingest": None,
    })

    assert "plugin verificato: no" in blocco
    assert "canali attivi: nessuno" in blocco
    assert "ultimo ingest: mai" in blocco


# ---- L'innesto sulla chat -------------------------------------------------------------------------


def _platform_tenant(client, name="WP AIssistant"):
    """Il nostro tenant: quello su un piano interno che eroga servizio. È l'unico da cui il
    contesto di pannello viene onorato."""
    with Session(db.engine) as session:
        plan = session.exec(
            select(db.Plan).where(db.Plan.code == billing.UNLIMITED_PLAN_CODE)
        ).first()
        if not plan:
            plan = db.Plan(name="Interno — Illimitato", code=billing.UNLIMITED_PLAN_CODE,
                           internal=True, chat_rate_limit=600, max_live_origins=0)
            session.add(plan)
            session.commit()
            session.refresh(plan)
        plan_id = plan.id
    created = client.post("/admin/clients", headers=ADMIN,
                          json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    with Session(db.engine) as session:
        row = session.get(db.Client, created["id"])
        row.plan_id = plan_id
        session.add(row)
        session.commit()
    return created


@pytest.fixture
def prompts(monkeypatch):
    """Cattura il prompt di sistema con cui il modello viene chiamato.

    I messaggi qui sotto sono saluti di proposito. Con una knowledge base vuota il guardiano
    dello scope risponde «fuori ambito» **prima** di costruire il prompt, e il modello non viene
    mai chiamato: si finirebbe a verificare che una lista è vuota per il motivo sbagliato. Il
    saluto è l'unico percorso che raggiunge `build_system` senza dover prima inventare un corpus,
    e attraversa esattamente la stessa riga.
    """
    from app.routers import widget as widget_router

    seen = []
    monkeypatch.setattr(
        widget_router, "llm_chat",
        lambda system, history, message: seen.append(system) or {"reply": "ok"},
    )
    return seen


def test_the_panel_context_reaches_the_prompt(client, tenant, signed, prompts):
    ours = _platform_tenant(client)
    token = client.post("/panel/assistant/token", headers=tenant["op"]).json()["token"]

    res = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {ours['api_key']}", "X-Panel-Assistant-Token": token},
        json={"visitor_id": "op-1", "message": "ciao"},
    )

    assert res.status_code == 200
    assert prompts and "ACCOUNT DATA" in prompts[-1]


def test_a_forged_token_is_ignored_and_the_chat_still_answers(client, tenant, signed, prompts):
    """Degradazione giusta: il token arricchisce il contesto, non autorizza l'accesso. Non c'è
    niente da negare — solo qualcosa da non aggiungere."""
    ours = _platform_tenant(client)

    res = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {ours['api_key']}",
                 "X-Panel-Assistant-Token": "falso.token"},
        json={"visitor_id": "op-1", "message": "ciao"},
    )

    assert res.status_code == 200
    assert prompts and "ACCOUNT DATA" not in prompts[-1]


def test_another_tenant_widget_never_honours_a_panel_token(client, tenant, signed, prompts):
    """Il token è legato al tenant di chi l'ha chiesto, quindi non legge i dati di nessun altro.
    Ma presentato al widget di un altro cliente riverserebbe i *propri* dati nella casella di
    quello: nessuno ruba niente, e proprio per questo passerebbe inosservato."""
    token = client.post("/panel/assistant/token", headers=tenant["op"]).json()["token"]
    altro = client.post("/admin/clients", headers=ADMIN,
                        json={"name": "Altro", "allowed_origins": TENANT_ORIGIN}).json()

    res = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {altro['api_key']}", "X-Panel-Assistant-Token": token},
        json={"visitor_id": "v9", "message": "ciao"},
    )

    assert res.status_code == 200
    assert prompts and "ACCOUNT DATA" not in prompts[-1]


def test_reading_a_client_context_is_audited(client, tenant, signed, prompts):
    """Un accesso ai dati di un cliente fatto da un sistema nostro deve restare ricostruibile."""
    ours = _platform_tenant(client)
    token = client.post("/panel/assistant/token", headers=tenant["op"]).json()["token"]
    client.post(
        "/chat",
        headers={"Authorization": f"Bearer {ours['api_key']}", "X-Panel-Assistant-Token": token},
        json={"visitor_id": "op-1", "message": "ciao"},
    )

    with Session(db.engine) as session:
        entry = session.exec(
            select(db.AuditLog).where(db.AuditLog.action == "panel_assistant.context_read")
        ).first()

    assert entry is not None
    assert entry.client_id == tenant["cid"]
    assert entry.target == f"client:{tenant['cid']}"


def test_the_panel_shares_one_tenant_but_not_one_budget(client, tenant, signed, prompts, monkeypatch):
    """Tutto il pannello passa dal nostro **unico** `client.id`, e questo è il punto in cui una
    chiave di rate limit scritta sul solo tenant farebbe danno: il primo operatore che scrive
    esaurirebbe il budget di tutti gli altri, e il sintomo sarebbe «l'assistenza non risponde»
    per chi non ha fatto niente.

    La roadmap chiede di verificarlo con un test invece che dedurlo dal codice, ed è la richiesta
    giusta: la chiave è una stringa costruita altrove, e cambia senza che nulla qui si accorga.
    """
    from app import deps

    chiavi = []
    monkeypatch.setattr(deps.chat_limiter, "check", lambda key, limit: chiavi.append((key, limit)))
    ours = _platform_tenant(client)
    token = client.post("/panel/assistant/token", headers=tenant["op"]).json()["token"]
    client.post(
        "/chat",
        headers={"Authorization": f"Bearer {ours['api_key']}", "X-Panel-Assistant-Token": token},
        json={"visitor_id": "op-1", "message": "ciao"},
    )

    assert chiavi
    chiave, limite = chiavi[-1]
    prefisso = f"chat:{ours['id']}:"
    assert chiave.startswith(prefisso)
    assert chiave != prefisso, "la chiave deve separare gli operatori, non solo i tenant"
    # E il tetto è quello del piano interno, non il default globale: il nostro tenant serve tutti
    # i pannelli insieme, quindi il limite del piano gratuito lo strozzerebbe.
    assert limite == 600


def test_the_panel_header_is_allowed_cross_origin():
    """Il pannello e il backend stanno su origin diversi: un header non elencato viene bloccato
    dal browser *prima* di partire, con il server che sta benissimo. È lo stesso fallimento muto
    che aveva reso irraggiungibili 36 rotte."""
    from app import cors

    assert "X-Panel-Assistant-Token" in cors.headers("https://panel.example")["Access-Control-Allow-Headers"]

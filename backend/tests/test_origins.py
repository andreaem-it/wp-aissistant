"""La licenza è legata al dominio: un sito live, uno di staging, i locali gratis.

Questo blocco è in **sola osservazione**: annota e conta, non rifiuta. I test qui fissano due
cose distinte — le regole di classificazione, che decidono cosa un cliente potrà registrare, e
il fatto che l'osservazione non cambi il comportamento di nessuna chiamata.

La regola più facile da sbagliare, e quella che regalerebbe una licenza, è il confronto della
parola chiave: per **etichetta DNS**, mai per sottostringa.
"""
import pytest
from sqlmodel import Session, select

from app import db, origins

ADMIN = {"Authorization": "Bearer test-admin"}


@pytest.fixture(autouse=True)
def _reset_observation_throttle():
    """L'antirimbalzo dell'osservazione vive nel processo, non nel database: senza azzerarlo un
    test che riusa lo stesso (cliente, dominio) di un test precedente non scriverebbe nulla, e
    fallirebbe per una ragione che non ha niente a che vedere con ciò che verifica."""
    origins._last_observed.clear()
    yield
    origins._last_observed.clear()


def _other_tenant(client, name="Origins Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN,
                json={"email": email, "password": "password1"})
    return {"cid": other["id"], "key": {"Authorization": f"Bearer {other['api_key']}"}}


# ---- host confrontabile ---------------------------------------------------------------------


def test_www_and_bare_domain_are_the_same_host():
    assert origins.host_of("https://www.esempio.it") == origins.host_of("https://esempio.it")


def test_scheme_and_port_do_not_change_the_site():
    assert origins.same_site("http://esempio.it", "https://esempio.it")
    assert origins.same_site("https://esempio.it:8443", "https://esempio.it")


def test_a_different_domain_is_a_different_site():
    assert not origins.same_site("https://esempio.it", "https://altrosito.it")


def test_a_subdomain_is_not_the_same_site_as_its_parent():
    """Altrimenti un solo slot live coprirebbe shop., blog. e quanti altri se ne vogliono."""
    assert not origins.same_site("https://shop.esempio.it", "https://esempio.it")


# ---- locali: sempre ammessi, mai contati -----------------------------------------------------


def test_local_hosts_are_recognised():
    for value in ("http://localhost:3000", "http://127.0.0.1:8080", "http://esempio.local",
                  "http://esempio.test", "http://sito.localhost"):
        assert origins.is_local(value), value


def test_a_real_domain_is_not_local():
    assert not origins.is_local("https://esempio.it")


def test_local_is_covered_without_being_registered():
    assert origins.covered("http://localhost:5173", [])


# ---- etichette di staging: per etichetta, mai per sottostringa -------------------------------


def test_a_development_label_is_recognised():
    for value in ("https://staging.esempio.it", "https://dev.esempio.it",
                  "https://demo.esempio.it", "https://shop.staging.esempio.it"):
        assert origins.has_staging_label(value), value


def test_a_word_that_merely_contains_the_keyword_is_not_a_staging_label():
    """`devoto.it` e `demolizioni.it` contengono "dev" e "demo" e sono siti veri.

    Un controllo scritto con `in` invece che sulle etichette regalerebbe lo slot di staging a
    chiunque abbia un dominio che comincia così, e non se ne accorgerebbe nessuno.
    """
    for value in ("https://devoto.it", "https://demolizioni.it", "https://testata.it",
                  "https://betaneve.it", "https://stagecoach-hotel.it"):
        assert not origins.has_staging_label(value), value


def test_the_vocabulary_is_closed():
    assert "produzione" not in origins.STAGING_LABELS
    assert {"staging", "dev", "demo", "test", "preprod", "uat"} <= origins.STAGING_LABELS


# ---- lo slot di staging deve stare sotto il dominio live -------------------------------------


def test_a_staging_subdomain_of_the_live_domain_is_accepted():
    assert origins.staging_rejection("https://staging.esempio.it", "https://esempio.it") is None


def test_a_keyword_subdomain_of_another_domain_is_refused():
    """Il punto dell'intera regola: `demo.altrosito.it` rispetta la convenzione ed è un secondo
    sito commerciale. Con la sola parola chiave lo slot sarebbe una licenza in regalo."""
    reason = origins.staging_rejection("https://demo.altrosito.it", "https://esempio.it")

    assert reason is not None
    assert "esempio.it" in reason


def test_a_subdomain_without_a_development_label_is_refused():
    reason = origins.staging_rejection("https://shop.esempio.it", "https://esempio.it")

    assert reason is not None
    assert "ambiente di prova" in reason


def test_a_known_development_platform_is_accepted_anywhere():
    """Le agenzie ospitano lo staging fuori dal dominio del cliente: rifiutarle romperebbe
    installazioni oneste."""
    for value in ("https://esempio.wpengine.com", "https://esempio.pantheonsite.io",
                  "https://esempio.vercel.app", "https://esempio.ddev.site"):
        assert origins.staging_rejection(value, "https://esempio.it") is None, value


def test_an_unknown_platform_is_refused():
    assert origins.staging_rejection("https://esempio.hosting-a-caso.io", "https://esempio.it")


def test_staging_cannot_be_the_live_domain():
    assert origins.staging_rejection("https://www.esempio.it", "https://esempio.it")


def test_a_local_address_is_not_a_staging_slot():
    reason = origins.staging_rejection("http://localhost:3000", "https://esempio.it")

    assert reason is not None
    assert "non occupano" in reason


def test_staging_without_a_live_domain_explains_what_to_do_first():
    reason = origins.staging_rejection("https://staging.esempio.it", "")

    assert reason is not None
    assert "live" in reason


# ---- copertura ------------------------------------------------------------------------------


def test_a_registered_domain_is_covered_with_or_without_www():
    assert origins.covered("https://www.esempio.it", ["https://esempio.it"])
    assert origins.covered("https://esempio.it", ["https://www.esempio.it"])


def test_an_unregistered_domain_is_not_covered():
    assert not origins.covered("https://altrosito.it", ["https://esempio.it"])


# ---- osservazione: annota, non rifiuta -------------------------------------------------------


def _observed(client_id):
    with Session(db.engine) as session:
        return session.exec(
            select(db.ClientOrigin).where(db.ClientOrigin.client_id == client_id)
        ).all()


def test_a_chat_from_an_unregistered_origin_still_works(client, tenant):
    """Il cuore di questo blocco: stiamo guardando, non ancora applicando. Se questo test
    fallisce chiedendo un 403, qualcuno ha acceso l'applicazione senza la migrazione dei
    clienti esistenti."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://sito-mai-visto.it"},
                           json={"message": "ciao", "visitor_id": "v-osservazione"})

    assert response.status_code == 200


def test_the_origin_is_recorded_as_observed(client, tenant):
    client.post("/chat", headers={**tenant["key"], "Origin": "https://osservato.it"},
                json={"message": "ciao", "visitor_id": "v-annotato"})

    rows = [r for r in _observed(tenant["cid"]) if r.host == "osservato.it"]
    assert len(rows) == 1
    assert rows[0].kind == "observed"
    assert rows[0].source == "traffic"
    assert rows[0].confirmed_at is None


def test_an_observed_row_grants_nothing(client, tenant, monkeypatch):
    """`observed` è una traccia di traffico, non un permesso: non deve entrare nell'allowlist
    del livello browser. Una riga confermata invece sì — è il senso della conferma."""
    from app import cors

    monkeypatch.setattr(cors, "CORS_ALLOW_ALL", False)
    with Session(db.engine) as session:
        session.add(db.ClientOrigin(client_id=tenant["cid"], origin="https://intruso.it",
                                    host="intruso.it", kind="observed", source="traffic"))
        session.add(db.ClientOrigin(client_id=tenant["cid"], origin="https://confermato.it",
                                    host="confermato.it", kind="live", source="panel"))
        session.commit()
        cors.rebuild_allowed_origins(session)

    assert not cors.is_allowed("https://intruso.it")
    assert cors.is_allowed("https://confermato.it")


def test_local_traffic_is_not_recorded(client, tenant):
    """I locali non occupano slot: annotarli riempirebbe il pannello di righe che non
    significano niente."""
    client.post("/chat", headers={**tenant["key"], "Origin": "http://localhost:5173"},
                json={"message": "ciao", "visitor_id": "v-locale"})

    assert not [r for r in _observed(tenant["cid"]) if "localhost" in r.host]


def test_a_call_without_an_origin_records_no_domain(client, tenant):
    """Una chiamata senza header Origin non viene da un browser. Non c'è dominio da annotare —
    ma è il segnale che una chiave pubblica è usata da un server, ed è l'unico buco che la
    CORS non copre affatto."""
    client.post("/chat", headers=tenant["key"],
                json={"message": "ciao", "visitor_id": "v-senza-origin"})

    assert _observed(tenant["cid"]) == []


# ---- isolamento fra tenant -------------------------------------------------------------------


def test_observations_are_scoped_to_the_calling_tenant(client, tenant):
    other = _other_tenant(client)
    client.post("/chat", headers={**tenant["key"], "Origin": "https://primo.it"},
                json={"message": "ciao", "visitor_id": "v-1"})
    client.post("/chat", headers={**other["key"], "Origin": "https://secondo.it"},
                json={"message": "ciao", "visitor_id": "v-2"})

    assert [r.host for r in _observed(tenant["cid"])] == ["primo.it"]
    assert [r.host for r in _observed(other["cid"])] == ["secondo.it"]

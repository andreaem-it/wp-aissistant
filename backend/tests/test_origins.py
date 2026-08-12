"""La licenza è legata al dominio: un sito live, uno di staging, i locali gratis.

Questo blocco è in **sola osservazione**: annota e conta, non rifiuta. I test qui fissano due
cose distinte — le regole di classificazione, che decidono cosa un cliente potrà registrare, e
il fatto che l'osservazione non cambi il comportamento di nessuna chiamata.

La regola più facile da sbagliare, e quella che regalerebbe una licenza, è il confronto della
parola chiave: per **etichetta DNS**, mai per sottostringa.
"""
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app import db, origins
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


@pytest.fixture(autouse=True)
def _no_live_change_cooldown(monkeypatch):
    """Il raffreddamento sul cambio del dominio live non c'entra con quasi nessuno di questi
    test, e lasciarlo attivo li farebbe fallire per il motivo sbagliato. Il test che lo
    riguarda lo riaccende da sé."""
    monkeypatch.setattr(origins, "LIVE_CHANGE_COOLDOWN", None)


@pytest.fixture(autouse=True)
def _reset_observation_throttle():
    """L'antirimbalzo dell'osservazione vive nel processo, non nel database: senza azzerarlo un
    test che riusa lo stesso (cliente, dominio) di un test precedente non scriverebbe nulla, e
    fallirebbe per una ragione che non ha niente a che vedere con ciò che verifica."""
    origins._last_observed.clear()
    yield
    origins._last_observed.clear()


def _other_tenant(client, name="Origins Other"):
    other = client.post("/admin/clients", headers=ADMIN,
                        json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN,
                json={"email": email, "password": "password1"})
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {
        "cid": other["id"],
        "key": {"Authorization": f"Bearer {other['api_key']}"},
        "op": {"Authorization": f"Bearer {token}"},
    }


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


def test_a_chat_from_an_unregistered_domain_is_refused(client, tenant):
    """Il cuore del blocco: la licenza vale sui domini registrati e su nessun altro."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://sito-mai-visto.it"},
                           json={"message": "ciao", "visitor_id": "v-estraneo"})

    assert response.status_code == 403
    assert "sito-mai-visto.it" in response.json()["detail"]


def test_a_chat_from_the_registered_domain_works(client, tenant):
    response = client.post("/chat", headers=tenant["key"],
                           json={"message": "ciao", "visitor_id": "v-legittimo"})

    assert response.status_code == 200


def test_www_of_the_registered_domain_works(client, tenant):
    """`www.esempio.it` ed `esempio.it` sono lo stesso sito: rifiutare il primo sarebbe un
    403 incomprensibile per chi ha registrato il secondo."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://www.acme.example"},
                           json={"message": "ciao", "visitor_id": "v-www"})

    assert response.status_code == 200


def test_a_tenant_without_any_domain_is_refused(client):
    """Il default ribaltato. Prima l'assenza di configurazione **disattivava** il controllo:
    una licenza senza domini valeva ovunque. Ora non vale da nessuna parte."""
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Senza dominio"}).json()

    response = client.post("/chat", headers={"Authorization": f"Bearer {other['api_key']}"},
                           json={"message": "ciao", "visitor_id": "v-senza-licenza"})

    assert response.status_code == 403
    assert "Nessun dominio registrato" in response.json()["detail"]


def test_a_call_without_an_origin_header_is_refused(client, tenant):
    """Il varco che restava intero: nessun browser omette Origin, quindi una chiamata che non
    ce l'ha non viene da una pagina — ed è il modo realistico di usare una chiave copiata da un
    sito. Chi integra da un server ha /v1 con una chiave dotata di scope."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": ""},
                           json={"message": "ciao", "visitor_id": "v-server"})

    assert response.status_code == 403
    assert "/v1" in response.json()["detail"]


def test_local_development_always_works(client, tenant):
    """Gli indirizzi locali non occupano slot e non si negano mai: bloccarli romperebbe
    l'ambiente di sviluppo di ogni cliente senza proteggere niente."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": "http://localhost:5173"},
                           json={"message": "ciao", "visitor_id": "v-locale"})

    assert response.status_code == 200


def test_the_refusal_never_reaches_the_visitor(client, tenant):
    """Un problema di licenza riguarda chi installa, non chi sta scrivendo: nel corpo non deve
    finire nulla che il widget possa mostrare come risposta dell'assistente."""
    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://non-registrato.it"},
                           json={"message": "ciao", "visitor_id": "v-visitatore"})

    assert response.status_code == 403
    assert "reply" not in response.json()


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


def test_the_registered_domain_is_seen_again(client, tenant):
    """L'osservazione sopravvive all'applicazione, ma cambia mestiere: non serve più a sapere
    chi romperemmo, serve a dire al cliente quando quel dominio è stato usato l'ultima volta."""
    client.post("/chat", headers=tenant["key"],
                json={"message": "ciao", "visitor_id": "v-visto"})

    rows = [r for r in _observed(tenant["cid"]) if r.host == "acme.example"]
    assert len(rows) == 1
    assert rows[0].kind == "live"


# ---- isolamento fra tenant -------------------------------------------------------------------


def test_a_domain_registered_by_another_tenant_does_not_grant_access(client, tenant):
    """Prima l'allowlist CORS era globale e il controllo per-cliente si disattivava da solo:
    bastava che un tenant qualsiasi avesse registrato quel dominio. Ora la licenza è di chi
    l'ha registrata."""
    other = _other_tenant(client)
    with Session(db.engine) as session:
        session.add(db.ClientOrigin(client_id=other["cid"], origin="https://solo-suo.it",
                                    host="solo-suo.it", kind="live", source="panel"))
        session.commit()

    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://solo-suo.it"},
                           json={"message": "ciao", "visitor_id": "v-prestito"})

    assert response.status_code == 403


def test_registering_a_domain_is_scoped_to_the_calling_tenant(client, tenant):
    other = _other_tenant(client)

    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "https://mio-dominio.it", "kind": "live"})
    assert response.status_code == 200

    listing = client.get("/account/origins", headers=other["op"]).json()
    assert "mio-dominio.it" not in [o["host"] for o in listing["origins"]]


def test_a_tenant_cannot_delete_another_tenants_domain(client, tenant):
    """Convenzione del progetto: la risorsa di un altro tenant risponde 404, mai 403, per non
    rivelarne l'esistenza."""
    other = _other_tenant(client)
    created = client.post("/account/origins", headers=other["op"],
                          json={"origin": "https://altrui.it", "kind": "live"}).json()

    response = client.delete(f"/account/origins/{created['origin']['id']}", headers=tenant["op"])

    assert response.status_code == 404


# ---- gli slot dal pannello del cliente --------------------------------------------------------


def test_a_second_live_domain_replaces_the_first(client, tenant):
    """Uno slot solo: cambiare dominio è normale — rebrand, migrazione, lancio — e si fa da
    soli, senza un ticket."""
    client.post("/account/origins", headers=tenant["op"],
                json={"origin": "https://nuovo.it", "kind": "live"})

    listing = client.get("/account/origins", headers=tenant["op"]).json()
    live = [o["host"] for o in listing["origins"] if o["kind"] == "live"]
    assert live == ["nuovo.it"]
    assert listing["slots"]["live_used"] == 1


def test_changing_the_live_domain_again_too_soon_is_refused(client, tenant, monkeypatch):
    """Il raffreddamento scoraggia l'uso che vogliamo evitare — ruotare la stessa licenza fra
    siti — e dice quando sarà possibile invece di rifiutare e basta."""
    monkeypatch.setattr(origins, "LIVE_CHANGE_COOLDOWN", timedelta(days=7))
    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "https://troppo-presto.it", "kind": "live"})

    assert response.status_code == 400
    assert "Potrai cambiarlo" in response.json()["detail"]


def test_a_staging_subdomain_can_be_registered(client, tenant):
    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "https://staging.acme.example", "kind": "staging"})

    assert response.status_code == 200
    assert response.json()["slots"]["staging_used"] == 1


def test_a_staging_domain_outside_the_live_site_is_refused(client, tenant):
    """`demo.altrosito.it` rispetta la convenzione ed è un secondo sito commerciale: è il caso
    che l'intera regola esiste per fermare."""
    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "https://demo.altrosito.it", "kind": "staging"})

    assert response.status_code == 400
    assert "acme.example" in response.json()["detail"]


def test_only_one_staging_domain(client, tenant):
    client.post("/account/origins", headers=tenant["op"],
                json={"origin": "https://staging.acme.example", "kind": "staging"})

    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "https://dev.acme.example", "kind": "staging"})

    assert response.status_code == 400
    assert "staging" in response.json()["detail"]


def test_a_registered_staging_domain_serves_the_widget(client, tenant):
    client.post("/account/origins", headers=tenant["op"],
                json={"origin": "https://staging.acme.example", "kind": "staging"})

    response = client.post("/chat", headers={**tenant["key"], "Origin": "https://staging.acme.example"},
                           json={"message": "ciao", "visitor_id": "v-staging"})

    assert response.status_code == 200


def test_a_local_address_cannot_be_registered(client, tenant):
    response = client.post("/account/origins", headers=tenant["op"],
                           json={"origin": "http://localhost:3000", "kind": "staging"})

    assert response.status_code == 400
    assert "non occupano slot" in response.json()["detail"]


def test_removing_the_live_domain_stops_the_widget(client, tenant):
    """La prova che la tabella è la sorgente di verità e non uno specchio di qualcos'altro."""
    listing = client.get("/account/origins", headers=tenant["op"]).json()
    live_id = next(o["id"] for o in listing["origins"] if o["kind"] == "live")

    client.delete(f"/account/origins/{live_id}", headers=tenant["op"])
    response = client.post("/chat", headers=tenant["key"],
                           json={"message": "ciao", "visitor_id": "v-dopo-rimozione"})

    assert response.status_code == 403

"""L'aspetto del widget, lato server.

Il rischio che questi test presidiano non è che una preferenza non si salvi: è che il
vocabolario del backend e quello del widget divergano. Il sintomo sarebbe un'opzione che il
pannello offre, il backend accetta e il widget ignora — senza un errore da nessuna parte, che è
esattamente come si è manifestato il debito 5 dell'handoff con le intestazioni CORS.
"""
import json
from pathlib import Path

from sqlmodel import Session, select

from app import db, widget_config
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


# ---- il vocabolario è uno solo ----------------------------------------------------------------


def test_the_backend_reads_the_widget_vocabulary_instead_of_restating_it():
    """La lista dei valori ammessi sta in `sdk/widget/src/schema.js` e arriva qui generata.

    Se questo test fallisce, qualcuno ha scritto a mano una copia in Python — oppure la build del
    widget non è stata rieseguita dopo aver toccato lo schema, e l'artefatto versionato è vecchio.
    """
    generated = json.loads(
        (Path(__file__).resolve().parents[2] / "sdk" / "widget" / "schema.json").read_text()
    )

    assert widget_config.APPEARANCE == generated["appearance"]
    assert widget_config.FLAGS == generated["flags"]
    assert widget_config.DEFAULT_COLOR == generated["defaultColor"]


def test_every_option_has_a_default_inside_its_own_vocabulary():
    for name, spec in widget_config.APPEARANCE.items():
        assert spec["default"] in spec["values"], f"{name}: il default non è fra i valori ammessi"


def test_without_the_generated_schema_nothing_is_accepted(monkeypatch):
    """Un'immagine che spedisce solo `backend/` non ha il file del widget. In quel caso si
    rifiuta tutto invece di accettare tutto: è l'unico modo sicuro di sbagliare."""
    monkeypatch.setattr(widget_config, "APPEARANCE", {})
    monkeypatch.setattr(widget_config, "FLAGS", {})

    clean = widget_config.normalise({"appearance": {"theme": "dark"}})

    assert clean["appearance"] == {"color": widget_config.DEFAULT_COLOR}


# ---- validazione -------------------------------------------------------------------------------


def test_a_value_outside_the_vocabulary_is_refused_not_corrected(client, tenant):
    """Il widget ripiega sul default perché deve funzionare comunque; il configuratore no.

    Un'impostazione salvata che non ha alcun effetto è peggio di un errore: il cliente crede di
    aver scelto qualcosa e vede il widget di prima.
    """
    response = client.put("/account/widget-config", headers=tenant["op"],
                          json={"appearance": {"theme": "arcobaleno"}})

    assert response.status_code == 400
    assert "arcobaleno" in response.json()["detail"]
    # e il messaggio dice quali sono i valori buoni, invece di lasciarlo indovinare
    assert "light" in response.json()["detail"]


def test_a_valid_configuration_is_saved_and_returned(client, tenant):
    response = client.put("/account/widget-config", headers=tenant["op"], json={
        "appearance": {"theme": "dark", "position": "left", "color": "#00ff88", "showAvatar": False},
        "texts": {"title": "Assistenza", "welcome": "Ciao!"},
    })

    assert response.status_code == 200
    saved = response.json()["config"]
    assert saved["appearance"]["theme"] == "dark"
    assert saved["appearance"]["color"] == "#00ff88"
    assert saved["appearance"]["showAvatar"] is False
    assert saved["texts"]["title"] == "Assistenza"

    again = client.get("/account/widget-config", headers=tenant["op"]).json()
    assert again["config"] == saved
    assert again["configured"] is True


def test_an_unset_boolean_keeps_its_default_instead_of_becoming_false(client, tenant):
    # `undefined` significa "non l'ho toccato": trattarlo come falso nasconderebbe l'avatar a chi
    # non ha mai aperto quella impostazione.
    response = client.put("/account/widget-config", headers=tenant["op"], json={"appearance": {}})

    assert response.json()["config"]["appearance"]["showAvatar"] is True


def test_a_colour_that_could_escape_the_css_is_refused(client, tenant):
    response = client.put("/account/widget-config", headers=tenant["op"],
                          json={"appearance": {"color": "#000; background: url(evil)"}})

    assert response.status_code == 400


def test_a_privacy_url_must_be_absolute(client, tenant):
    refused = client.put("/account/widget-config", headers=tenant["op"],
                         json={"texts": {"privacyUrl": "javascript:alert(1)"}})
    assert refused.status_code == 400

    accepted = client.put("/account/widget-config", headers=tenant["op"],
                          json={"texts": {"privacyUrl": "https://esempio.it/privacy"}})
    assert accepted.status_code == 200


def test_texts_have_a_ceiling(client, tenant):
    response = client.put("/account/widget-config", headers=tenant["op"],
                          json={"texts": {"title": "x" * 500}})

    assert response.status_code == 400
    assert "title" in response.json()["detail"]


def test_a_tenant_that_never_saved_gets_the_defaults_not_an_error(client, tenant):
    response = client.get("/account/widget-config", headers=tenant["op"])

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["config"]["appearance"]["theme"] == "light"


def test_the_vocabulary_travels_with_the_configuration(client, tenant):
    """Il pannello costruisce i menu a tendina da qui: riscrivere la lista nel frontend sarebbe
    la terza copia della stessa cosa."""
    vocabulary = client.get("/account/widget-config", headers=tenant["op"]).json()["vocabulary"]

    assert "dark" in vocabulary["appearance"]["theme"]["values"]
    assert vocabulary["appearance"]["theme"]["default"] == "light"
    assert vocabulary["textLimits"]["title"] > 0


def test_a_corrupt_row_falls_back_to_the_defaults(client, tenant):
    """Una riga illeggibile non deve rendere inutilizzabile la schermata: si riparte da ciò che
    il widget userebbe comunque."""
    with Session(db.engine) as session:
        session.add(db.WidgetConfig(client_id=tenant["cid"], payload="{non è json"))
        session.commit()

    response = client.get("/account/widget-config", headers=tenant["op"])

    assert response.status_code == 200
    assert response.json()["config"]["appearance"]["theme"] == "light"


# ---- isolamento fra tenant ---------------------------------------------------------------------


def test_configurations_never_cross_tenants(client, tenant):
    other = client.post("/admin/clients", headers=ADMIN,
                        json={"name": "Config Other", "allowed_origins": TENANT_ORIGIN}).json()
    client.post(f"/admin/clients/{other['id']}/operators", headers=ADMIN,
                json={"email": "config-other@other.it", "password": "password1"})
    token = client.post("/operator/login",
                        json={"email": "config-other@other.it", "password": "password1"}).json()["token"]
    other_op = {"Authorization": f"Bearer {token}"}

    client.put("/account/widget-config", headers=tenant["op"],
               json={"appearance": {"theme": "dark"}})

    assert client.get("/account/widget-config", headers=other_op).json()["config"]["appearance"]["theme"] == "light"
    with Session(db.engine) as session:
        rows = session.exec(select(db.WidgetConfig)).all()
    assert [r.client_id for r in rows] == [tenant["cid"]]


def test_saving_twice_updates_the_same_row(client, tenant):
    client.put("/account/widget-config", headers=tenant["op"], json={"appearance": {"theme": "dark"}})
    client.put("/account/widget-config", headers=tenant["op"], json={"appearance": {"theme": "auto"}})

    with Session(db.engine) as session:
        rows = session.exec(select(db.WidgetConfig).where(
            db.WidgetConfig.client_id == tenant["cid"]
        )).all()

    assert len(rows) == 1
    assert json.loads(rows[0].payload)["appearance"]["theme"] == "auto"


def test_the_endpoint_needs_an_operator_session(client, tenant):
    # la chiave pubblica del widget sta in ogni pagina: non deve poter riconfigurare niente
    assert client.get("/account/widget-config", headers=tenant["key"]).status_code == 401
    assert client.put("/account/widget-config", headers=tenant["key"], json={}).status_code == 401

"""Il canale di aggiornamento del plugin WordPress.

Il plugin è distribuito da noi e non da WordPress.org: se non chiede lui gli aggiornamenti, non
li riceve. È rimasto così per mesi senza che nulla lo dicesse, ed è il motivo per cui questi
test guardano soprattutto le cose che possono tornare a rompersi **in silenzio**: una versione
che diverge fra le sue tre dichiarazioni, e un indirizzo di download che smette di puntare dove
deve.
"""
import json
import re
from pathlib import Path

from app import plugin_release

PLUGIN_FILE = Path(__file__).resolve().parents[2] / "wp-plugin" / "wp-aissistant" / "wp-aissistant.php"


def _plugin_source() -> str:
    return PLUGIN_FILE.read_text(encoding="utf-8")


# ---- Una versione sola, dichiarata in tre posti ---------------------------------------------


def test_the_manifest_version_matches_the_plugin_itself():
    """Tre dichiarazioni della stessa versione: l'header del plugin, la costante `WPAI_VERSION` e
    questo manifest. `build.sh` già confronta le prime due; la terza è nuova, e senza un test che
    la leghi alle altre il backend annuncerebbe con serenità una versione che nessuno ha
    pubblicato — offrendo a ogni sito un aggiornamento che scarica il pacchetto sbagliato o non
    scarica niente.

    È la stessa regola di `schema.json` e `schema.js`: una lista in più linguaggi si tiene
    insieme con un test, non con l'attenzione.
    """
    source = _plugin_source()
    header = re.search(r"Version:\s*([0-9][0-9A-Za-z.-]*)", source).group(1)
    constant = re.search(r"define\('WPAI_VERSION',\s*'([^']+)'\)", source).group(1)

    assert plugin_release.release()["version"] == header
    assert plugin_release.release()["version"] == constant


def test_the_manifest_file_is_valid_json_with_what_wordpress_needs():
    data = json.loads(plugin_release.RELEASE_FILE.read_text(encoding="utf-8"))

    for field in ("version", "requires", "tested", "requires_php"):
        assert data.get(field), f"manca «{field}» nel manifest del rilascio"


def test_the_requirements_match_the_plugin_readme():
    """`readme.txt` li dichiara già, ed è quello che un amministratore legge nel pacchetto. Due
    numeri diversi per la stessa cosa producono il caso peggiore: WordPress mostra
    «Richiede WordPress 6.0» nell'avviso di aggiornamento e poi installa un plugin che nel suo
    readme dice 5.8, oppure — al contrario — offre l'aggiornamento a un sito troppo vecchio per
    reggerlo. Li ho già sbagliati una volta scrivendo il manifest a mano.
    """
    readme = (PLUGIN_FILE.parent / "readme.txt").read_text(encoding="utf-8")
    data = plugin_release.release()

    dichiarati = {
        "requires": re.search(r"Requires at least:\s*(\S+)", readme).group(1),
        "tested": re.search(r"Tested up to:\s*(\S+)", readme).group(1),
        "requires_php": re.search(r"Requires PHP:\s*(\S+)", readme).group(1),
    }
    for campo, atteso in dichiarati.items():
        assert data[campo] == atteso, f"«{campo}»: il manifest dice {data[campo]}, readme.txt {atteso}"


def test_the_readme_stable_tag_matches_the_release():
    readme = (PLUGIN_FILE.parent / "readme.txt").read_text(encoding="utf-8")

    assert re.search(r"Stable tag:\s*(\S+)", readme).group(1) == plugin_release.release()["version"]


# ---- L'endpoint ------------------------------------------------------------------------------


def test_the_update_endpoint_is_public(client):
    """Deliberatamente senza autenticazione. Chiuderlo dietro la `api_key` significherebbe che un
    sito con la chiave scaduta o non ancora configurata smette di ricevere correzioni di
    sicurezza — l'opposto di ciò che serve. La licenza si applica alle risposte della chat, dove
    il controllo è server-side ed è già stretto, non al diritto di avere l'ultima versione.
    """
    res = client.get("/plugin/update")

    assert res.status_code == 200
    assert res.json()["version"] == plugin_release.release()["version"]


def test_the_endpoint_answers_with_the_fields_wordpress_reads(client):
    body = client.get("/plugin/update").json()

    for field in ("slug", "plugin", "version", "download_url", "requires", "requires_php", "tested"):
        assert body.get(field), f"manca «{field}»: WordPress non saprebbe cosa farne"
    assert body["plugin"] == "wp-aissistant/wp-aissistant.php"
    assert "changelog" in body["sections"]


def test_the_download_points_at_an_immutable_cdn_path(client):
    """Lo zip non passa dal backend: il manifest è qualche centinaio di byte, il megabyte lo
    serve R2. E il percorso porta la versione, come per il widget — un pacchetto che cambia
    sotto lo stesso indirizzo è un aggiornamento che non si può ripetere né verificare."""
    body = client.get("/plugin/update").json()

    assert body["download_url"].startswith("https://cdn.wpaissistant.it/plugin/")
    assert body["version"] in body["download_url"]
    assert body["download_url"].endswith("/wp-aissistant.zip")


def test_the_answer_is_cacheable(client):
    """Ogni sito con il plugin interroga questo endpoint, e WordPress lo fa a ogni caricamento
    della pagina dei plugin quando il transient è scaduto. Senza cache al bordo è un moltiplicatore
    che cresce con i clienti."""
    res = client.get("/plugin/update")

    assert "max-age" in res.headers.get("cache-control", "")


# ---- Il lato plugin: le cose che rompono un sito in silenzio -----------------------------------


def test_the_plugin_refuses_a_download_url_outside_our_cdn():
    """WordPress **esegue** il codice che scarica da `package`. Un manifest che punta altrove non
    è un aggiornamento: è esecuzione di codice arbitrario sul sito del cliente. Il dominio è
    fissato nel plugin, non negoziato nella risposta — così anche se il backend fosse compromesso
    o un proxy riscrivesse la risposta, il peggio che succede è che non si aggiorna."""
    source = _plugin_source()

    assert "strpos($manifest['download_url'], 'https://cdn.wpaissistant.it/') !== 0" in source


def test_the_plugin_declares_no_update_as_well_as_updates():
    """`no_update` non è una formalità: senza, WordPress continua a proporre l'aggiornamento
    rimasto in un transient precedente anche dopo averlo installato."""
    source = _plugin_source()

    assert "no_update[$basename]" in source
    assert "unset($transient->response[$basename])" in source


def test_the_plugin_caches_failures_too():
    """Un backend irraggiungibile senza cache negativa farebbe ritentare a ogni caricamento di
    pagina: il carico peggiore esattamente nel momento peggiore."""
    source = _plugin_source()

    assert source.count("set_transient(WPAI_UPDATE_TRANSIENT, ['version' => '']") >= 3


def test_a_cached_failure_is_not_mistaken_for_a_manifest():
    """Il fallimento è in cache come array vuoto di versione, e un array è **vero** in PHP: al
    primo giro la funzione tornava `null` correttamente, al secondo restituiva quell'array e il
    chiamante lo prendeva per buono, registrando un aggiornamento con versione vuota. Il tipo
    dice «ho una risposta», il contenuto dice «non ne ho»; a decidere dev'essere il contenuto.
    """
    source = _plugin_source()

    assert "empty($cached['version']) ? null : $cached" in source


def test_the_plugin_talks_to_the_real_backend_domain():
    """Puntava all'URL grezzo di Railway, come tutto il resto prima di oggi."""
    source = _plugin_source()

    assert "https://backend.wpaissistant.it" in source
    assert "railway.app" not in source

"""Security guard for the WooCommerce order-lookup callback: the backend must only call back
one of the tenant's registered domains, never a spoofed site_url (SSRF).

L'elenco arriva ora da `ClientOrigin` (la licenza legata al dominio) invece che dalla stringa
`Client.allowed_origins`, quindi l'argomento è una lista. La proprietà da difendere non cambia:
un `site_url` scelto dall'attaccante non deve mai diventare la destinazione di una chiamata."""
# order-lookup helpers moved with the widget router when main.py was split
from app.routers import widget as main


class _Req:
    def __init__(self, **headers):
        self._h = headers

    class _H:
        def __init__(self, h):
            self._h = h

        def get(self, k):
            return self._h.get(k)

    @property
    def headers(self):
        return _Req._H(self._h)


def test_trusted_origin_when_site_url_matches_allowlist():
    req = _Req(origin="https://site.it")
    # site_url (with a path) is normalized and matches the configured origin
    assert main._trusted_callback_origin(["https://site.it"], "https://site.it/shop", req) == "https://site.it"


def test_spoofed_site_url_is_rejected():
    req = _Req(origin="https://site.it")
    # attacker-controlled site_url pointing at an internal host -> refused (no SSRF)
    assert main._trusted_callback_origin(["https://site.it"], "http://169.254.169.254/latest/meta-data", req) == ""


def test_falls_back_to_request_origin_if_site_url_untrusted():
    req = _Req(origin="https://site.it")
    # site_url untrusted, but the request Origin header is allowed -> use it
    assert main._trusted_callback_origin(["https://site.it"], "http://evil.tld", req) == "https://site.it"


def test_requires_allowlist_configured():
    req = _Req(origin="https://site.it")
    # nessun dominio registrato -> non si richiama nessuno (default sicuro)
    assert main._trusted_callback_origin([], "https://site.it", req) == ""


def test_bootstrap_accepts_an_unregistered_https_site():
    """Solo la registrazione del plugin passa di qui: là la fiducia viene dal challenge HMAC,
    che prova il possesso del sito, non dall'elenco — che per un cliente nuovo è vuoto."""
    req = _Req(origin="https://nuovo.it")
    assert main._trusted_callback_origin([], "https://nuovo.it", req, bootstrap=True) == "https://nuovo.it"


def test_bootstrap_still_refuses_internal_targets():
    """Un `site_url` che punta a un indirizzo interno fa fallire la validazione **del tutto**,
    anche in bootstrap: non si ripiega sull'header Origin. Ripiegare in silenzio nasconderebbe
    un tentativo di SSRF dietro un esito riuscito."""
    req = _Req(origin="https://nuovo.it")
    assert main._trusted_callback_origin(
        [], "http://169.254.169.254/latest/meta-data", req, bootstrap=True) == ""


def test_bootstrap_refuses_plain_http():
    """Un sito in chiaro non è un posto dove mandare la richiesta di un ordine."""
    req = _Req(origin="http://nuovo.it")
    assert main._trusted_callback_origin([], "http://nuovo.it", req, bootstrap=True) == ""

"""Security guard for the WooCommerce order-lookup callback: the backend must only call back
an origin the client configured (allowed_origins), never a spoofed site_url (SSRF)."""
from app import main


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
    assert main._trusted_callback_origin("https://site.it", "https://site.it/shop", req) == "https://site.it"


def test_spoofed_site_url_is_rejected():
    req = _Req(origin="https://site.it")
    # attacker-controlled site_url pointing at an internal host -> refused (no SSRF)
    assert main._trusted_callback_origin("https://site.it", "http://169.254.169.254/latest/meta-data", req) == ""


def test_falls_back_to_request_origin_if_site_url_untrusted():
    req = _Req(origin="https://site.it")
    # site_url untrusted, but the request Origin header is allowed -> use it
    assert main._trusted_callback_origin("https://site.it", "http://evil.tld", req) == "https://site.it"


def test_requires_allowlist_configured():
    req = _Req(origin="https://site.it")
    # no allowed_origins configured -> never call back (safe default)
    assert main._trusted_callback_origin("", "https://site.it", req) == ""

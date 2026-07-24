import types

import pytest

from app import llm


def _fake_completion(content):
    def _completion(model, messages, **kwargs):
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    return _completion


def _raising(*args, **kwargs):
    raise ConnectionError("ollama unreachable")


def test_plain_reply(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("Ciao!"))
    assert llm.chat("sys", [], "ciao") == {"reply": "Ciao!"}


def test_escalation_marker_parsed(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE: serve un umano"))
    assert llm.chat("sys", [], "voglio un rimborso") == {"escalate": "serve un umano"}


def test_escalation_without_reason_defaults(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE:"))
    assert llm.chat("sys", [], "x") == {"escalate": "unspecified"}


def test_chat_raises_llm_unavailable_when_provider_unreachable(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _raising)
    with pytest.raises(llm.LLMUnavailableError):
        llm.chat("sys", [], "ciao")


def test_embed_raises_llm_unavailable_when_provider_unreachable(monkeypatch):
    # force the litellm path regardless of the configured default (cloudflare/* bypasses litellm)
    monkeypatch.setattr(llm, "EMBED_MODEL", "ollama/nomic-embed-text")
    monkeypatch.setattr(llm.litellm, "embedding", _raising)
    with pytest.raises(llm.LLMUnavailableError):
        llm.embed("testo")


class _FakeCloudflareResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_embed_routes_cloudflare_models_to_direct_http(monkeypatch):
    """litellm doesn't support Cloudflare Workers AI embeddings, so this path bypasses it."""
    import json

    monkeypatch.setattr(llm, "EMBED_MODEL", "cloudflare/@cf/baai/bge-m3")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "token123")

    captured = {}

    def _fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        body = json.dumps({"success": True, "result": {"data": [[0.1, 0.2, 0.3]]}}).encode()
        return _FakeCloudflareResponse(body)

    monkeypatch.setattr(llm.urllib.request, "urlopen", _fake_urlopen)
    assert llm.embed("ciao") == [0.1, 0.2, 0.3]
    assert captured["url"].endswith("/ai/run/@cf/baai/bge-m3")
    assert captured["auth"] == "Bearer token123"


def test_embed_cloudflare_raises_llm_unavailable_on_api_error(monkeypatch):
    import json

    monkeypatch.setattr(llm, "EMBED_MODEL", "cloudflare/@cf/baai/bge-m3")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "token123")

    def _fake_urlopen(req, timeout):
        body = json.dumps({"success": False, "errors": ["boom"]}).encode()
        return _FakeCloudflareResponse(body)

    monkeypatch.setattr(llm.urllib.request, "urlopen", _fake_urlopen)
    with pytest.raises(llm.LLMUnavailableError):
        llm.embed("ciao")

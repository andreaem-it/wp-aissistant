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
    result = llm.chat("sys", [], "ciao")
    assert result["reply"] == "Ciao!"
    # every call also carries diagnostics for the AI response log (app/db.py AiResponseLog)
    assert set(result) == {"reply", "model", "latency_ms", "tokens_prompt", "tokens_completion"}


def test_escalation_marker_parsed(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE: serve un umano"))
    result = llm.chat("sys", [], "voglio un rimborso")
    assert result["escalate"] == "serve un umano"


def test_escalation_without_reason_defaults(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE:"))
    result = llm.chat("sys", [], "x")
    assert result["escalate"] == "unspecified"


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


def _fake_stream_chunks(text, with_usage):
    """A fake streaming response: content chunks, plus a final usage chunk if requested."""
    for tok in text:
        delta = types.SimpleNamespace(content=tok)
        yield types.SimpleNamespace(model="m", usage=None, choices=[types.SimpleNamespace(delta=delta)])
    if with_usage:
        yield types.SimpleNamespace(model="m", usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3), choices=[])


def test_stream_captures_token_usage(monkeypatch):
    monkeypatch.setattr(llm, "_stream_usage_supported", True)

    def _completion(model, messages, **kwargs):
        # provider supports stream_options -> emits usage
        assert kwargs.get("stream_options") == {"include_usage": True}
        return _fake_stream_chunks("ok", with_usage=True)

    monkeypatch.setattr(llm.litellm, "completion", _completion)
    events = list(llm.chat_stream("sys", [], "ciao"))
    meta = events[-1][1]
    assert meta["tokens_prompt"] == 7 and meta["tokens_completion"] == 3


def test_stream_falls_back_when_provider_rejects_stream_options(monkeypatch):
    monkeypatch.setattr(llm, "_stream_usage_supported", True)
    calls = {"with_opts": 0, "without": 0}

    def _completion(model, messages, **kwargs):
        if "stream_options" in kwargs:
            calls["with_opts"] += 1
            raise TypeError("provider rejects stream_options")
        calls["without"] += 1
        return _fake_stream_chunks("ok", with_usage=False)

    monkeypatch.setattr(llm.litellm, "completion", _completion)
    events = list(llm.chat_stream("sys", [], "ciao"))
    assert events[-1][0] == "meta"                 # streamed successfully via the fallback
    assert calls["with_opts"] == 1 and calls["without"] == 1
    assert llm._stream_usage_supported is False    # remembered: don't retry with options again

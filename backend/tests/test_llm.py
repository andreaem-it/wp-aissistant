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
    monkeypatch.setattr(llm.litellm, "embedding", _raising)
    with pytest.raises(llm.LLMUnavailableError):
        llm.embed("testo")

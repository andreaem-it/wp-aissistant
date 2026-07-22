import types

from app import llm


def _fake_completion(content):
    def _completion(model, messages):
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
    return _completion


def test_plain_reply(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("Ciao!"))
    assert llm.chat("sys", [], "ciao") == {"reply": "Ciao!"}


def test_escalation_marker_parsed(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE: serve un umano"))
    assert llm.chat("sys", [], "voglio un rimborso") == {"escalate": "serve un umano"}


def test_escalation_without_reason_defaults(monkeypatch):
    monkeypatch.setattr(llm.litellm, "completion", _fake_completion("ESCALATE:"))
    assert llm.chat("sys", [], "x") == {"escalate": "unspecified"}

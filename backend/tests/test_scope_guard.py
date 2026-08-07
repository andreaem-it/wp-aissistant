# the split moved these apart: scope logic is rag domain, the refusal text is the chat's
from app import rag
from app.rag import is_small_talk as _is_small_talk, retrieval_is_in_scope as _retrieval_is_in_scope
from app.routers.widget import _out_of_scope_reply


def test_small_talk_is_allowed_without_knowledge_context():
    assert _is_small_talk("Ciao!")
    assert _is_small_talk("Come stai?")


def test_general_knowledge_question_is_not_small_talk():
    assert not _is_small_talk("Quanto dista la Terra dalla Luna?")


def test_scope_requires_a_selected_close_result(monkeypatch):
    monkeypatch.setattr(rag, "SCOPE_MAX_DISTANCE", 0.62)
    assert _retrieval_is_in_scope([
        {"selected": True, "distance": 0.41},
        {"selected": False, "distance": 0.2},
    ])
    assert not _retrieval_is_in_scope([
        {"selected": True, "distance": 0.73},
        {"selected": False, "distance": 0.2},
    ])
    assert not _retrieval_is_in_scope([])


def test_out_of_scope_reply_does_not_offer_escalation():
    """Il rifiuto fuori ambito non deve promettere un umano: vale in ogni lingua, perché una
    traduzione che offre un operatore creerebbe un'aspettativa che il codice non mantiene."""
    from app import language

    promesse = ("operator", "operatore", "ticket", "agent", "mitarbeiter")
    for code in language.SUPPORTED:
        reply = _out_of_scope_reply(code).lower()
        assert reply
        assert not any(parola in reply for parola in promesse), code
    assert "cultura generale" in _out_of_scope_reply("it").lower()
    assert "general knowledge" in _out_of_scope_reply("en").lower()

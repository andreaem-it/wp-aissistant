from app import main


def test_small_talk_is_allowed_without_knowledge_context():
    assert main._is_small_talk("Ciao!")
    assert main._is_small_talk("Come stai?")


def test_general_knowledge_question_is_not_small_talk():
    assert not main._is_small_talk("Quanto dista la Terra dalla Luna?")


def test_scope_requires_a_selected_close_result(monkeypatch):
    monkeypatch.setattr(main, "SCOPE_MAX_DISTANCE", 0.62)
    assert main._retrieval_is_in_scope([
        {"selected": True, "distance": 0.41},
        {"selected": False, "distance": 0.2},
    ])
    assert not main._retrieval_is_in_scope([
        {"selected": True, "distance": 0.73},
        {"selected": False, "distance": 0.2},
    ])
    assert not main._retrieval_is_in_scope([])


def test_out_of_scope_reply_does_not_offer_escalation():
    reply = main._OUT_OF_SCOPE_REPLY.lower()
    assert "cultura generale" in reply
    assert "operatore" not in reply
    assert "ticket" not in reply

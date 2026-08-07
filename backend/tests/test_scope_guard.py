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


# ---- L'istruzione di grounding ------------------------------------------------------------

from app.rag import build_system


def test_the_prompt_names_no_tool():
    """Il prompt diceva «call escalate_to_human», una funzione che qui non esiste: l'escalation
    è un marcatore testuale. Istruito a usare un meccanismo che non ha, il modello rispondeva
    comunque — è la causa che ha prodotto metodi di spedizione inventati."""
    prompt = build_system(["Le spedizioni partono in 24 ore."])

    assert "escalate_to_human" not in prompt
    assert "call " not in prompt.lower() or "tool" not in prompt.lower()


def test_the_prompt_forbids_inventing_the_specifics_that_get_invented():
    """Non basta «rispondi dal contesto»: le cose che un modello piccolo inventa sono sempre le
    stesse — prezzi, sconti, corrieri, tempi, nomi di pagina — e vanno nominate."""
    prompt = build_system(["Le spedizioni partono in 24 ore."]).lower()

    for forbidden in ["price", "discount", "delivery time", "payment", "url"]:
        assert forbidden in prompt, f"il prompt non vieta esplicitamente di inventare: {forbidden}"


def test_the_prompt_covers_partial_context():
    """Il caso in cui l'invenzione avviene davvero: il contesto copre metà domanda."""
    prompt = build_system(["Le spedizioni partono in 24 ore."]).lower()

    assert "in part" in prompt or "only in part" in prompt


def test_the_context_is_still_carried_verbatim():
    """Il rafforzamento non deve aver perso il contesto, che è l'unica fonte ammessa."""
    prompt = build_system(["Le spedizioni partono in 24 ore.", "I resi entro 30 giorni."])

    assert "Le spedizioni partono in 24 ore." in prompt
    assert "I resi entro 30 giorni." in prompt

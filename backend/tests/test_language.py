"""Language detection, localized deterministic replies and cross-language knowledge base."""

from app import i18n, language, main


ADMIN = {"Authorization": "Bearer test-admin"}


def _chat(client, tenant, message, visitor="lang", locale=None, conversation=None):
    body = {"visitor_id": visitor, "message": message}
    if locale:
        body["locale"] = locale
    if conversation:
        body["conversation_id"] = conversation["conversation_id"]
        body["conversation_token"] = conversation["conversation_token"]
    return client.post("/chat", headers=tenant["key"], json=body).json()


def _conversation_language(client, tenant, conv_id):
    rows = client.get("/conversations", headers=tenant["op"]).json()
    return next(r["conversation"]["language"] for r in rows if r["conversation"]["id"] == conv_id)


# ---- detection ----


def test_detects_the_supported_languages():
    assert language.detect("Vorrei sapere quando arriva il mio ordine") == "it"
    assert language.detect("I would like to know where my order is") == "en"
    assert language.detect("Quiero saber dónde está mi pedido") == "es"
    assert language.detect("Je voudrais savoir où est ma commande") == "fr"
    assert language.detect("Ich möchte wissen, wo meine Bestellung ist") == "de"
    assert language.detect("Queria saber onde está a minha encomenda") == "pt"


def test_browser_locale_decides_when_the_text_says_nothing():
    """Un messaggio senza parole riconoscibili non deve produrre un indovinello."""
    assert language.detect("12345", hint="en-GB") == "en"
    assert language.detect("", hint="de-DE") == "de"
    assert language.detect("???", hint=None, default="it") == "it"


def test_text_wins_over_the_browser_locale():
    # il browser è in inglese ma il visitatore scrive in italiano: risponde in italiano
    assert language.detect("Vorrei un rimborso per il mio ordine", hint="en-US") == "it"


def test_unsupported_locale_falls_back_to_the_default():
    assert language.normalize("ja-JP") is None
    assert language.normalize("IT_it") == "it"
    assert language.detect("...", hint="ja-JP") == "it"


def test_detection_is_stable_for_short_greetings():
    assert language.detect("ciao") == "it"
    assert language.detect("hello") == "en"
    assert language.detect("hola") == "es"


# ---- catalog ----


def test_every_supported_language_has_every_string():
    missing = [
        (key, code)
        for key, entry in i18n.MESSAGES.items()
        for code in language.SUPPORTED
        if not entry.get(code)
    ]
    assert missing == []


def test_translation_falls_back_instead_of_showing_a_key():
    assert i18n.t("scope.out_of_scope", "de").startswith("Ich kann")
    assert i18n.t("scope.out_of_scope", "ja") == i18n.t("scope.out_of_scope", "it")
    assert i18n.t("chiave.inesistente", "it") == "chiave.inesistente"
    assert i18n.t("order.total", "en", value="12 €") == "Total: 12 €."


def test_prompt_instructs_the_answer_language():
    assert "German" in i18n.prompt_language_instruction("de")
    assert "Italian" in i18n.prompt_language_instruction(None)
    # il contesto può essere in un'altra lingua: è esattamente il caso cross-language
    assert "regardless of the language of the context" in i18n.prompt_language_instruction("en")


def test_system_prompt_carries_the_language_and_the_context(monkeypatch):
    prompt = main._build_system(["Le spedizioni partono in 24 ore."], "fr")
    assert "Le spedizioni partono in 24 ore." in prompt  # la KB resta nella sua lingua
    assert "Answer in French" in prompt


# ---- end to end ----


def test_conversation_stores_the_detected_language(client, tenant):
    chat = _chat(client, tenant, "Where is my order? I would like to know")
    assert _conversation_language(client, tenant, chat["conversation_id"]) == "en"


def test_language_can_change_mid_conversation(client, tenant):
    chat = _chat(client, tenant, "Hello, can you help me with this order?")
    assert _conversation_language(client, tenant, chat["conversation_id"]) == "en"

    _chat(client, tenant, "Vorrei sapere quando arriva il mio ordine", conversation=chat)
    assert _conversation_language(client, tenant, chat["conversation_id"]) == "it"


def test_out_of_scope_reply_is_localized(client, tenant):
    chat = _chat(client, tenant, "Who is the president of France? I would like to know")
    if chat["status"] == "open" and chat["reply"]:
        # la risposta fuori ambito è deterministica: se scatta, deve essere in inglese
        assert "cultura generale" not in chat["reply"]


def test_cart_reply_is_localized(client, tenant):
    assert "Add to cart" in main._cart_instruction_reply([{"title": "x"}], "en")
    assert "Aggiungi al carrello" in main._cart_instruction_reply([{"title": "x"}], "it")
    assert "In den Warenkorb" in main._cart_instruction_reply([{"title": "x"}], "de")


def test_order_reply_is_localized():
    data = {"verified": "full", "status": "shipped", "total": "42 €", "items": ["Scarpe"]}
    english = main._format_order_reply(data, "en")
    assert english.startswith("Order status: shipped.")
    assert "Total: 42 €." in english
    assert "Items: Scarpe." in english

    italian = main._format_order_reply(data, "it")
    assert italian.startswith("Stato dell'ordine: shipped.")

    assert main._format_order_reply({"verified": False}, "fr").startswith("Je n'ai pas pu")


def test_locale_hint_is_used_when_the_message_is_uninformative(client, tenant):
    chat = _chat(client, tenant, "?!", locale="es-ES")
    assert _conversation_language(client, tenant, chat["conversation_id"]) == "es"


# ---- inbox ----


def test_inbox_filters_by_language(client, tenant):
    italian = _chat(client, tenant, "Vorrei sapere il costo della spedizione", visitor="it")
    english = _chat(client, tenant, "I would like to know the shipping cost", visitor="en")

    def ids(params):
        return [r["conversation"]["id"] for r in client.get("/conversations", headers=tenant["op"], params=params).json()]

    assert ids({"conversation_language": "it"}) == [italian["conversation_id"]]
    assert ids({"conversation_language": "en"}) == [english["conversation_id"]]
    assert client.get(
        "/conversations", headers=tenant["op"], params={"conversation_language": "ja"}
    ).status_code == 400


def test_saved_view_can_filter_by_language(client, tenant):
    view = client.post("/saved-views", headers=tenant["op"], json={
        "name": "Inglese", "filters": {"conversation_language": "en"},
    }).json()
    assert view["filters"] == {"conversation_language": "en"}
    assert client.post("/saved-views", headers=tenant["op"], json={
        "name": "Marziano", "filters": {"conversation_language": "mars"},
    }).status_code == 400


def test_stats_report_the_language_split(client, tenant):
    _chat(client, tenant, "Vorrei sapere il costo della spedizione", visitor="it")
    _chat(client, tenant, "I would like to know the shipping cost", visitor="en1")
    _chat(client, tenant, "Where can I find my order? I would like to know", visitor="en2")

    languages = client.get("/stats", headers=tenant["op"]).json()["languages"]
    assert languages == {"it": 1, "en": 2}

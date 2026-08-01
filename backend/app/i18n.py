"""Visitor-facing strings the backend produces itself.

Only the deterministic replies live here — the ones the code writes, not the model: cart
instructions, out-of-scope refusals and order lookups. Order and cart answers are templated on
purpose (never a second LLM round-trip), so their translations have to be templated too.

The model's own answers are handled differently: the system prompt tells it which language to
answer in (see prompt_language_instruction), because translating a generated answer after the
fact would be a second chance to get it wrong.
"""

from .language import DEFAULT, SUPPORTED

LANGUAGE_NAMES = {
    "it": "Italian",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}

MESSAGES: dict[str, dict[str, str]] = {
    "cart.use_button": {
        "it": "Per aggiungere il prodotto, usa il pulsante “Aggiungi al carrello” nella scheda qui sotto.",
        "en": "To add the product, use the “Add to cart” button on the card below.",
        "es": "Para añadir el producto, usa el botón “Añadir al carrito” en la ficha de abajo.",
        "fr": "Pour ajouter le produit, utilisez le bouton « Ajouter au panier » sur la fiche ci-dessous.",
        "de": "Um das Produkt hinzuzufügen, nutze die Schaltfläche „In den Warenkorb“ auf der Karte unten.",
        "pt": "Para adicionar o produto, usa o botão “Adicionar ao carrinho” no cartão abaixo.",
    },
    "cart.no_product": {
        "it": "Posso aiutarti a trovare il prodotto, ma non ne ho identificato uno con certezza. Indicami il nome esatto: potrai aggiungerlo dal pulsante nella sua scheda.",
        "en": "I can help you find the product, but I couldn't identify one with certainty. Tell me the exact name and you'll be able to add it from the button on its card.",
        "es": "Puedo ayudarte a encontrar el producto, pero no he identificado ninguno con certeza. Dime el nombre exacto y podrás añadirlo desde el botón de su ficha.",
        "fr": "Je peux vous aider à trouver le produit, mais je n'en ai identifié aucun avec certitude. Indiquez-moi le nom exact : vous pourrez l'ajouter depuis le bouton de sa fiche.",
        "de": "Ich helfe dir gern, das Produkt zu finden, konnte aber keines sicher zuordnen. Nenn mir den genauen Namen, dann kannst du es über die Schaltfläche auf seiner Karte hinzufügen.",
        "pt": "Posso ajudar-te a encontrar o produto, mas não identifiquei nenhum com certeza. Diz-me o nome exato e poderás adicioná-lo pelo botão do seu cartão.",
    },
    "scope.out_of_scope": {
        "it": "Posso aiutarti con i prodotti, i servizi e l’assistenza relativi a questo sito. Non posso rispondere a domande di cultura generale.",
        "en": "I can help with the products, services and support related to this site. I can't answer general knowledge questions.",
        "es": "Puedo ayudarte con los productos, servicios y la asistencia de este sitio. No puedo responder preguntas de cultura general.",
        "fr": "Je peux vous aider sur les produits, les services et l'assistance de ce site. Je ne peux pas répondre à des questions de culture générale.",
        "de": "Ich kann bei Produkten, Leistungen und Support zu dieser Website helfen. Allgemeinwissensfragen kann ich nicht beantworten.",
        "pt": "Posso ajudar com os produtos, serviços e apoio deste site. Não posso responder a perguntas de cultura geral.",
    },
    "order.not_verified": {
        "it": "Non sono riuscito a verificare l'ordine con i dati forniti. Controlla il numero d'ordine e riprova, oppure chiedimi di parlare con un operatore.",
        "en": "I couldn't verify the order with the details provided. Check the order number and try again, or ask me to put you through to an operator.",
        "es": "No he podido verificar el pedido con los datos indicados. Comprueba el número de pedido e inténtalo de nuevo, o pídeme hablar con un operador.",
        "fr": "Je n'ai pas pu vérifier la commande avec les informations fournies. Vérifiez le numéro de commande et réessayez, ou demandez-moi un opérateur.",
        "de": "Ich konnte die Bestellung mit den angegebenen Daten nicht prüfen. Kontrolliere die Bestellnummer und versuche es erneut, oder bitte mich um einen Mitarbeiter.",
        "pt": "Não consegui verificar a encomenda com os dados fornecidos. Confirma o número da encomenda e tenta novamente, ou pede para falar com um operador.",
    },
    "order.status": {
        "it": "Stato dell'ordine: {value}.",
        "en": "Order status: {value}.",
        "es": "Estado del pedido: {value}.",
        "fr": "Statut de la commande : {value}.",
        "de": "Bestellstatus: {value}.",
        "pt": "Estado da encomenda: {value}.",
    },
    "order.status_unknown": {
        "it": "non disponibile", "en": "not available", "es": "no disponible",
        "fr": "non disponible", "de": "nicht verfügbar", "pt": "não disponível",
    },
    "order.shipping_date": {
        "it": "Data di spedizione: {value}.",
        "en": "Shipping date: {value}.",
        "es": "Fecha de envío: {value}.",
        "fr": "Date d'expédition : {value}.",
        "de": "Versanddatum: {value}.",
        "pt": "Data de envio: {value}.",
    },
    "order.no_shipping_date": {
        "it": "Non è ancora stata registrata una data di spedizione.",
        "en": "No shipping date has been recorded yet.",
        "es": "Todavía no se ha registrado una fecha de envío.",
        "fr": "Aucune date d'expédition n'a encore été enregistrée.",
        "de": "Es wurde noch kein Versanddatum erfasst.",
        "pt": "Ainda não foi registada uma data de envio.",
    },
    "order.total": {
        "it": "Totale: {value}.", "en": "Total: {value}.", "es": "Total: {value}.",
        "fr": "Total : {value}.", "de": "Summe: {value}.", "pt": "Total: {value}.",
    },
    "order.items": {
        "it": "Articoli: {value}.", "en": "Items: {value}.", "es": "Artículos: {value}.",
        "fr": "Articles : {value}.", "de": "Artikel: {value}.", "pt": "Artigos: {value}.",
    },
    "order.shipping_address": {
        "it": "Indirizzo di spedizione: {value}.",
        "en": "Shipping address: {value}.",
        "es": "Dirección de envío: {value}.",
        "fr": "Adresse de livraison : {value}.",
        "de": "Lieferadresse: {value}.",
        "pt": "Morada de envio: {value}.",
    },
}


def t(key: str, lang: str | None = None, **values) -> str:
    """Translate `key`, falling back to the default language when a string is missing rather
    than showing the raw key to a visitor."""
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    code = lang if lang in SUPPORTED else DEFAULT
    text = entry.get(code) or entry.get(DEFAULT) or ""
    return text.format(**values) if values else text


def prompt_language_instruction(lang: str | None) -> str:
    """Tell the model which language to answer in. The knowledge base can be in any language —
    the embeddings are multilingual — so retrieval is never filtered by language: the context
    may well be Italian while the visitor writes in German, and that is the point."""
    name = LANGUAGE_NAMES.get(lang if lang in SUPPORTED else DEFAULT, LANGUAGE_NAMES[DEFAULT])
    return (
        f"\n\nAnswer in {name}, regardless of the language of the context above: the visitor "
        f"wrote in {name} and must be answered in {name}. Keep product names, order numbers "
        f"and quoted text exactly as they appear in the context."
    )

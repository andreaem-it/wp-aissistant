/**
 * Testi del widget nelle lingue supportate.
 *
 * Tenuto in un file separato dal widget per due motivi: il file della chat era già la parte
 * più lunga del plugin, e le traduzioni cambiano con una cadenza diversa dal codice. Espone
 * `window.WPAI_I18N` nel browser e `module.exports` sotto Node, così le stesse stringhe
 * possono essere verificate dai test senza un DOM.
 *
 * I testi configurati dal cliente (benvenuto, sottotitolo, disclosure AI) NON stanno qui:
 * appartengono al tenant e restano nelle impostazioni del plugin.
 */
(function (root) {
  const DEFAULT = "it";
  const SUPPORTED = ["it", "en", "es", "fr", "de", "pt"];

  const STRINGS = {
    "chat.open": { it: "Apri la chat", en: "Open the chat", es: "Abrir el chat", fr: "Ouvrir le chat", de: "Chat öffnen", pt: "Abrir o chat" },
    "chat.close": { it: "Chiudi la chat", en: "Close the chat", es: "Cerrar el chat", fr: "Fermer le chat", de: "Chat schließen", pt: "Fechar o chat" },
    "chat.placeholder": { it: "Scrivi un messaggio…", en: "Write a message…", es: "Escribe un mensaje…", fr: "Écrivez un message…", de: "Nachricht schreiben…", pt: "Escreve uma mensagem…" },
    "chat.send": { it: "Invia", en: "Send", es: "Enviar", fr: "Envoyer", de: "Senden", pt: "Enviar" },
    "chat.error": {
      it: "Errore di connessione, riprova tra poco.",
      en: "Connection error, please try again shortly.",
      es: "Error de conexión, inténtalo de nuevo en un momento.",
      fr: "Erreur de connexion, réessayez dans un instant.",
      de: "Verbindungsfehler, bitte versuche es gleich noch einmal.",
      pt: "Erro de ligação, tenta novamente daqui a pouco.",
    },
    // Un problema di licenza non è un problema del visitatore: non può risolverlo e riprovare
    // non serve a niente, quindi il testo non lo invita a farlo e non spiega perché. Il motivo
    // vero va in console, per chi ha installato il widget.
    "chat.unavailable": {
      it: "La chat non è al momento disponibile su questo sito.",
      en: "The chat is currently unavailable on this site.",
      es: "El chat no está disponible en este sitio en este momento.",
      fr: "Le chat n'est pas disponible sur ce site pour le moment.",
      de: "Der Chat ist auf dieser Website derzeit nicht verfügbar.",
      pt: "O chat não está disponível neste site de momento.",
    },
    "chat.escalated": {
      it: "La tua richiesta è stata inoltrata a un operatore, ti risponderemo qui appena possibile.",
      en: "Your request has been passed to an operator, we'll reply here as soon as possible.",
      es: "Tu solicitud se ha enviado a un operador, te responderemos aquí lo antes posible.",
      fr: "Votre demande a été transmise à un opérateur, nous vous répondrons ici dès que possible.",
      de: "Deine Anfrage wurde an einen Mitarbeiter weitergeleitet, wir antworten hier so schnell wie möglich.",
      pt: "O teu pedido foi encaminhado para um operador, respondemos aqui assim que possível.",
    },
    "chat.quota": {
      it: "Il limite di messaggi è stato raggiunto. Riprova più tardi o contatta il supporto.",
      en: "The message limit has been reached. Try again later or contact support.",
      es: "Se ha alcanzado el límite de mensajes. Inténtalo más tarde o contacta con soporte.",
      fr: "La limite de messages est atteinte. Réessayez plus tard ou contactez le support.",
      de: "Das Nachrichtenlimit ist erreicht. Versuche es später erneut oder wende dich an den Support.",
      pt: "O limite de mensagens foi atingido. Tenta mais tarde ou contacta o suporte.",
    },
    "chat.typing": { it: "sta scrivendo...", en: "is typing...", es: "está escribiendo...", fr: "est en train d'écrire...", de: "schreibt...", pt: "está a escrever..." },
    "feedback.up": { it: "Risposta utile", en: "Helpful answer", es: "Respuesta útil", fr: "Réponse utile", de: "Hilfreiche Antwort", pt: "Resposta útil" },
    "feedback.down": { it: "Risposta non utile", en: "Unhelpful answer", es: "Respuesta no útil", fr: "Réponse inutile", de: "Nicht hilfreiche Antwort", pt: "Resposta não útil" },
    "contact.label": {
      it: "Lascia la tua email per essere avvisato della risposta:",
      en: "Leave your email to be notified when we reply:",
      es: "Déjanos tu email para avisarte de la respuesta:",
      fr: "Laissez votre e-mail pour être prévenu de la réponse :",
      de: "Hinterlasse deine E-Mail, um über die Antwort informiert zu werden:",
      pt: "Deixa o teu email para seres avisado da resposta:",
    },
    "contact.submit": { it: "Avvisami", en: "Notify me", es: "Avísame", fr: "Prévenez-moi", de: "Benachrichtigen", pt: "Avisa-me" },
    "contact.done": {
      it: "Ti avviseremo via email appena rispondiamo.",
      en: "We'll email you as soon as we reply.",
      es: "Te avisaremos por email en cuanto respondamos.",
      fr: "Nous vous préviendrons par e-mail dès notre réponse.",
      de: "Wir melden uns per E-Mail, sobald wir antworten.",
      pt: "Avisamos-te por email assim que respondermos.",
    },
    "ticket.title": { it: "Supporto non disponibile", en: "Support unavailable", es: "Soporte no disponible", fr: "Support indisponible", de: "Support nicht verfügbar", pt: "Apoio indisponível" },
    "ticket.submit": { it: "Apri un ticket", en: "Open a ticket", es: "Abrir un ticket", fr: "Ouvrir un ticket", de: "Ticket öffnen", pt: "Abrir um pedido" },
    "rating.question": {
      it: "Come valuti questa conversazione?",
      en: "How would you rate this conversation?",
      es: "¿Cómo valoras esta conversación?",
      fr: "Comment évaluez-vous cette conversation ?",
      de: "Wie bewertest du dieses Gespräch?",
      pt: "Como avalias esta conversa?",
    },
    "rating.comment": { it: "Commento (facoltativo)", en: "Comment (optional)", es: "Comentario (opcional)", fr: "Commentaire (facultatif)", de: "Kommentar (optional)", pt: "Comentário (opcional)" },
    "rating.thanks": { it: "Grazie per la valutazione.", en: "Thanks for your feedback.", es: "Gracias por tu valoración.", fr: "Merci pour votre évaluation.", de: "Danke für deine Bewertung.", pt: "Obrigado pela avaliação." },
    "rating.error": {
      it: "Non siamo riusciti a registrare la valutazione. Riprova.",
      en: "We couldn't record your rating. Please try again.",
      es: "No hemos podido registrar tu valoración. Inténtalo de nuevo.",
      fr: "Nous n'avons pas pu enregistrer votre évaluation. Réessayez.",
      de: "Wir konnten deine Bewertung nicht speichern. Bitte versuche es erneut.",
      pt: "Não conseguimos registar a avaliação. Tenta novamente.",
    },
    "rating.stars": { it: "{n} su 5", en: "{n} out of 5", es: "{n} de 5", fr: "{n} sur 5", de: "{n} von 5", pt: "{n} em 5" },
    "proactive.reply": { it: "Rispondi", en: "Reply", es: "Responder", fr: "Répondre", de: "Antworten", pt: "Responder" },
    "proactive.later": { it: "Non ora", en: "Not now", es: "Ahora no", fr: "Pas maintenant", de: "Nicht jetzt", pt: "Agora não" },
    "proactive.never": { it: "Non mostrare più", en: "Don't show again", es: "No mostrar más", fr: "Ne plus afficher", de: "Nicht mehr anzeigen", pt: "Não mostrar mais" },
    "proactive.close": { it: "Chiudi il messaggio", en: "Close the message", es: "Cerrar el mensaje", fr: "Fermer le message", de: "Nachricht schließen", pt: "Fechar a mensagem" },
    "lead.submit": { it: "Invia", en: "Send", es: "Enviar", fr: "Envoyer", de: "Senden", pt: "Enviar" },
    "lead.sending": { it: "Invio…", en: "Sending…", es: "Enviando…", fr: "Envoi…", de: "Senden…", pt: "A enviar…" },
    "lead.done": {
      it: "Grazie, ti ricontattiamo presto.",
      en: "Thanks, we'll get back to you soon.",
      es: "Gracias, te contactaremos pronto.",
      fr: "Merci, nous vous recontactons bientôt.",
      de: "Danke, wir melden uns bald.",
      pt: "Obrigado, entramos em contacto em breve.",
    },
    "common.retry": { it: "Riprova", en: "Try again", es: "Reintentar", fr: "Réessayer", de: "Erneut versuchen", pt: "Tentar de novo" },
    "cart.add": { it: "Aggiungi al carrello", en: "Add to cart", es: "Añadir al carrito", fr: "Ajouter au panier", de: "In den Warenkorb", pt: "Adicionar ao carrinho" },
    "cart.adding": { it: "Aggiungo…", en: "Adding…", es: "Añadiendo…", fr: "Ajout…", de: "Wird hinzugefügt…", pt: "A adicionar…" },
    "cart.added": { it: "✓ Aggiunto", en: "✓ Added", es: "✓ Añadido", fr: "✓ Ajouté", de: "✓ Hinzugefügt", pt: "✓ Adicionado" },
    "cart.options": { it: "Scegli le opzioni", en: "Choose options", es: "Elige las opciones", fr: "Choisir les options", de: "Optionen wählen", pt: "Escolher opções" },
    "cart.added_message": {
      it: "{product} è stato aggiunto al carrello.",
      en: "{product} has been added to the cart.",
      es: "{product} se ha añadido al carrito.",
      fr: "{product} a été ajouté au panier.",
      de: "{product} wurde in den Warenkorb gelegt.",
      pt: "{product} foi adicionado ao carrinho.",
    },
    "cart.product": { it: "Il prodotto", en: "The product", es: "El producto", fr: "Le produit", de: "Das Produkt", pt: "O produto" },
  };

  /** `it-IT`, `IT_it`, `it` → `it`; null se non è una lingua supportata. */
  function normalize(code) {
    if (!code) return null;
    const base = String(code).trim().toLowerCase().split(/[-_]/)[0];
    return SUPPORTED.indexOf(base) === -1 ? null : base;
  }

  /** Lingua da usare: impostazione del sito, poi browser, poi italiano. */
  function resolve(siteLocale, browserLocale) {
    return normalize(siteLocale) || normalize(browserLocale) || DEFAULT;
  }

  /** Traduce, con fallback alla lingua predefinita: mai mostrare una chiave al visitatore. */
  function t(key, lang, values) {
    const entry = STRINGS[key];
    if (!entry) return key;
    let text = entry[normalize(lang) || DEFAULT] || entry[DEFAULT] || key;
    if (values) {
      Object.keys(values).forEach((name) => {
        text = text.replace("{" + name + "}", values[name]);
      });
    }
    return text;
  }

  const api = { DEFAULT, SUPPORTED, STRINGS, normalize, resolve, t };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.WPAI_I18N = api;
})(typeof window !== "undefined" ? window : null);

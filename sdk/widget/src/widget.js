/**
 * Il widget di chat: la parte che disegna.
 *
 * Estratto da `wp-plugin/wp-aissistant/assets/chat-widget.js` **senza riscriverlo** — stesso
 * criterio della divisione di `main.py`: uno spostamento non deve cambiare niente di
 * osservabile. È cambiato solo ciò che doveva: i globali `window.WPAI`, `window.WPAI_I18N` e
 * `window.WPAI_RULES` sono diventati configurazione e import.
 *
 * Tutto ciò che sa di WordPress è uscito di qui e vive nell'adapter `host`, che la piattaforma
 * ospite fornisce e che è **opzionale**: senza, il widget funziona: niente carrello e niente
 * dati completi dell'ordine, che è il comportamento giusto su un sito che non vende da sé.
 *
 * | Capacità dell'host | A cosa serve |
 * |---|---|
 * | `siteUrl` | la callback della ricerca ordini; l'header Origin non basta, un'installazione in sottocartella darebbe una URL sbagliata |
 * | `identityToken()` | prova d'identità del visitatore, per i dati completi dell'ordine invece del solo stato |
 * | `addToCart(product, button)` | aggiunta al carrello e ciò che ne segue sulla piattaforma |
 */
import * as I18N from "./i18n.js";
import * as RULES from "./rules.js";
import * as schema from "./schema.js";

/**
 * Monta il widget nella pagina.
 *
 * `config` sono coppie proprietà/valore — la stessa forma che producono la pagina delle
 * impostazioni del plugin e il configuratore del pannello — e `config.host` l'adapter.
 */
export function mount(config) {
  const cfg = config || {};
  const host = cfg.host || {};
  const look = schema.appearance(cfg.appearance || cfg);
  const VISITOR_KEY = "wpai_visitor_id";
  const CONV_KEY = "wpai_conversation_id";
  const CONV_TOKEN_KEY = "wpai_conversation_token";
  const ESCALATED_KEY = "wpai_escalated_shown";
  const CONTACT_KEY = "wpai_contact_given";
  const OPEN_KEY = "wpai_chat_open";
  const TICKET_OFFER_KEY = "wpai_ticket_offer";
  const RATED_KEY = "wpai_conversation_rated";
  const LEAD_KEY = "wpai_lead_form_shown";

  const PROACTIVE_KEY = "wpai_proactive_seen";
  const PROACTIVE_SESSION_KEY = "wpai_proactive_session_";
  const PROACTIVE_OPTOUT_KEY = "wpai_proactive_optout";
  const PROACTIVE_VARIANT_KEY = "wpai_proactive_variants";

  // Lingua del widget: impostazione del sito WordPress, poi browser, poi italiano. Il backend
  // riceve comunque il locale come suggerimento e rileva la lingua da ciò che il visitatore
  // scrive davvero.
  const LANG = I18N.resolve(cfg.locale, navigator.language);
  function t(key, values) {
    return I18N.t(key, LANG, values);
  }

  function visitorId() {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  }

  // L'identità del visitatore, quando la piattaforma ospite sa provarla: un token firmato di
  // breve durata con cui il backend offre i dati completi dell'ordine invece del solo stato.
  // Chi la fornisce è l'adapter `host` — su WordPress è un utente loggato, altrove sarà altro —
  // e senza adapter il widget funziona lo stesso, con il livello base.
  // Richiesto una volta sola e tenuto per la vita della pagina: vale 5 minuti, che bastano.
  let userTokenPromise = null;
  function userToken() {
    if (!host.identityToken) return Promise.resolve(null);
    if (!userTokenPromise) {
      userTokenPromise = Promise.resolve()
        .then(() => host.identityToken())
        .catch(() => null);
    }
    return userTokenPromise;
  }

  // ---- Licenza legata al dominio ----
  //
  // Il backend risponde 403 quando il widget gira su un dominio non registrato, o quando la
  // chiamata non porta un header Origin. È un problema di **installazione**, non del visitatore:
  // il motivo vero va a chi può correggerlo, cioè in console, mentre in chat compare un testo
  // neutro che non invita a riprovare — riprovare non cambierebbe nulla.
  //
  // `licenceBlocked` è vischioso di proposito: una volta accertato, si smette di chiamare il
  // backend. Senza, ogni messaggio del visitatore genererebbe due 403 (stream + fallback) per
  // un problema che nessuna ripetizione può risolvere.
  let licenceBlocked = false;

  async function noteLicenceRefusal(res) {
    if (res.status !== 403) return false;
    let detail = "";
    try {
      const payload = await res.clone().json();
      detail = payload && typeof payload.detail === "string" ? payload.detail : "";
    } catch (e) {
      detail = "";
    }
    licenceBlocked = true;
    console.error(
      "[WP AIssistant] Il widget non è attivo su questo dominio. " +
      (detail || "Registra il dominio del sito dal pannello, in Impostazioni → Siti e licenza.")
    );
    return true;
  }

  function addMessage(container, role, text) {
    const el = document.createElement("div");
    el.className = "wpai-msg " + role;
    el.textContent = text;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  // build cards via the DOM (textContent), never innerHTML: product title/price/url come from
  // the backend but could contain HTML — interpolating them would be an XSS vector.
  function safeHttpUrl(url) {
    return /^https?:\/\//i.test(url || "") ? url : "#";
  }

  function addProducts(container, products) {
    if (!products || !products.length) return;
    const wrap = document.createElement("div");
    wrap.className = "wpai-products";
    for (const p of products) {
      const card = document.createElement("div");
      card.className = "wpai-product-card";
      const productLink = document.createElement("a");
      productLink.className = "wpai-product-link";
      productLink.href = safeHttpUrl(p.product_url);
      productLink.target = "_blank";
      productLink.rel = "noopener";
      if (p.image_url) {
        const img = document.createElement("img");
        img.src = safeHttpUrl(p.image_url);
        img.alt = "";
        productLink.appendChild(img);
      }
      const info = document.createElement("div");
      info.className = "wpai-product-info";
      const title = document.createElement("div");
      title.className = "wpai-product-title";
      title.textContent = p.title || "";
      info.appendChild(title);
      if (p.price) {
        const price = document.createElement("div");
        price.className = "wpai-product-price";
        price.textContent = p.price + " €";
        info.appendChild(price);
      }
      productLink.appendChild(info);
      card.appendChild(productLink);

      // Il carrello esiste solo se la piattaforma ospite ne ha uno: senza adapter la card resta
      // un collegamento al prodotto, che è la cosa giusta su un sito che non vende da sé.
      if (host.addToCart) {
        const addButton = document.createElement("button");
        addButton.type = "button";
        addButton.className = "wpai-add-to-cart";
        addButton.textContent = t("cart.add");
        let optionsUrl = "";
        addButton.addEventListener("click", async () => {
          if (optionsUrl) {
            window.location.assign(optionsUrl);
            return;
          }
          if (addButton.disabled) return;
          addButton.disabled = true;
          addButton.textContent = t("cart.adding");
          try {
            // L'adapter decide come si aggiunge al carrello e cosa succede dopo (su WooCommerce:
            // i frammenti jQuery). Qui resta solo lo stato del pulsante, che è disegno.
            const result = await host.addToCart(p, addButton);
            if (result && result.optionsUrl) {
              optionsUrl = result.optionsUrl;
              addButton.textContent = t("cart.options");
              addButton.disabled = false;
              return;
            }
            addButton.textContent = t("cart.added");
            addButton.classList.add("is-added");
            addMessage(container, "assistant", t("cart.added_message", { product: p.title || t("cart.product") }));
          } catch (error) {
            addButton.textContent = t("common.retry");
            addButton.disabled = false;
            addButton.title = error.message || "";
          }
        });
        card.appendChild(addButton);
      }
      wrap.appendChild(card);
    }
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  async function sendFeedback(conversationId, messageId, value, wrap) {
    try {
      await fetch(`${cfg.backendUrl}/chat/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
        body: JSON.stringify({
          conversation_id: Number(conversationId),
          conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
          message_id: messageId,
          value,
        }),
      });
      wrap.setAttribute("data-voted", value); // CSS highlights the chosen button, hides the other
    } catch (e) {
      // feedback is best-effort — never disrupt the chat over it
    }
  }

  function addFeedback(container, conversationId, messageId) {
    if (!messageId) return;
    const wrap = document.createElement("div");
    wrap.className = "wpai-feedback";
    for (const [value, icon, aria] of [["up", "fa-thumbs-up", t("feedback.up")], ["down", "fa-thumbs-down", t("feedback.down")]]) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wpai-fb-btn wpai-fb-" + value;
      btn.innerHTML = `<i class="fa-solid ${icon}"></i>`;
      btn.setAttribute("aria-label", aria);
      btn.addEventListener("click", () => sendFeedback(conversationId, messageId, value, wrap));
      wrap.appendChild(btn);
    }
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // On escalation, let the visitor leave an email to be notified when an operator replies.
  // Shown once per conversation; posts the email + current page URL to /chat/contact.
  function addContactForm(container, conversationId) {
    if (!conversationId || localStorage.getItem(CONTACT_KEY) === String(conversationId)) return;
    const wrap = document.createElement("div");
    wrap.className = "wpai-contact";
    const label = document.createElement("div");
    label.className = "wpai-contact-label";
    label.textContent = t("contact.label");
    const form = document.createElement("form");
    form.className = "wpai-contact-form";
    const input = document.createElement("input");
    input.type = "email";
    input.required = true;
    input.placeholder = "tua@email.it";
    const btn = document.createElement("button");
    btn.type = "submit";
    btn.textContent = t("contact.submit");
    form.appendChild(input);
    form.appendChild(btn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await fetch(`${cfg.backendUrl}/chat/contact`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
          body: JSON.stringify({
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            email: input.value,
            url: window.location.href,
          }),
        });
        localStorage.setItem(CONTACT_KEY, String(conversationId));
        wrap.innerHTML = '<i class="fa-solid fa-check"></i> ' + t("contact.done");
        wrap.className = "wpai-contact done";
      } catch (e2) {
        // best-effort: don't block the chat if the contact save fails
      }
    });
    wrap.appendChild(label);
    wrap.appendChild(form);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // CSAT: chiede una valutazione della conversazione (non della singola risposta) quando
  // l'operatore la chiude. Mostrata una sola volta per conversazione.
  function addRatingForm(container, conversationId) {
    if (!conversationId) return;
    if (localStorage.getItem(RATED_KEY) === String(conversationId)) return;
    if (container.querySelector(".wpai-rating")) return;
    localStorage.setItem(RATED_KEY, String(conversationId)); // non richiederla più, anche se non risponde

    const wrap = document.createElement("div");
    wrap.className = "wpai-rating";
    const label = document.createElement("div");
    label.className = "wpai-contact-label";
    label.textContent = t("rating.question");
    const stars = document.createElement("div");
    stars.className = "wpai-rating-stars";
    const form = document.createElement("form");
    form.className = "wpai-contact-form";
    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 500;
    input.placeholder = t("rating.comment");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = t("lead.submit");
    form.appendChild(input);
    form.appendChild(submit);

    let chosen = 0;
    const send = async () => {
      if (!chosen) return;
      try {
        const res = await fetch(`${cfg.backendUrl}/chat/rating`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
          body: JSON.stringify({
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            score: chosen,
            comment: input.value || "",
          }),
        });
        if (!res.ok) throw new Error("rating failed");
        wrap.innerHTML = '<i class="fa-solid fa-check"></i> ' + t("rating.thanks");
        wrap.className = "wpai-rating done";
      } catch (e) {
        // niente conferme ottimistiche: se non è stata registrata, dillo
        label.textContent = t("rating.error");
      }
    };

    for (let value = 1; value <= 5; value += 1) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wpai-star";
      btn.innerHTML = '<i class="fa-regular fa-star"></i>';
      btn.setAttribute("aria-label", t("rating.stars", { n: value }));
      btn.addEventListener("click", () => {
        chosen = value;
        [...stars.children].forEach((el, index) => {
          el.innerHTML = index < value ? '<i class="fa-solid fa-star"></i>' : '<i class="fa-regular fa-star"></i>';
          el.setAttribute("aria-pressed", index < value ? "true" : "false");
        });
        form.hidden = false;
      });
      stars.appendChild(btn);
    }
    form.hidden = true;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      send();
    });

    wrap.appendChild(label);
    wrap.appendChild(stars);
    wrap.appendChild(form);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // ---- Form di qualificazione (lead) ----------------------------------------------------
  //
  // Mostrato una sola volta per conversazione, dopo l'escalation. Il consenso, quando il form
  // lo prevede, è obbligatorio anche lato server: qui il bottone resta disabilitato finché non
  // è spuntato, ma la verifica vera non sta nel browser.

  function leadFormShown(conversationId) {
    return localStorage.getItem(LEAD_KEY) === String(conversationId);
  }

  async function addLeadForm(container, conversationId) {
    if (!conversationId || leadFormShown(conversationId)) return;
    let form;
    try {
      const res = await fetch(`${cfg.backendUrl}/widget/lead-form?trigger=escalation`, {
        headers: { Authorization: `Bearer ${cfg.apiKey}` },
      });
      if (!res.ok) return;
      form = (await res.json()).form;
    } catch (e) {
      return; // nessun form: la conversazione prosegue normalmente
    }
    if (!form || !form.fields.length) return;
    localStorage.setItem(LEAD_KEY, String(conversationId));

    const wrap = document.createElement("div");
    wrap.className = "wpai-contact";
    if (form.intro) {
      const intro = document.createElement("div");
      intro.className = "wpai-contact-label";
      intro.textContent = form.intro;
      wrap.appendChild(intro);
    }

    const el = document.createElement("form");
    el.className = "wpai-lead-form";
    const inputs = {};
    for (const field of form.fields) {
      const label = document.createElement("label");
      label.className = "wpai-lead-field";
      const caption = document.createElement("span");
      caption.textContent = field.label + (field.required ? " *" : "");
      let control;
      if (field.type === "select") {
        control = document.createElement("select");
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "—";
        control.appendChild(empty);
        for (const option of field.options || []) {
          const opt = document.createElement("option");
          opt.value = option;
          opt.textContent = option;
          control.appendChild(opt);
        }
      } else {
        control = document.createElement("input");
        control.type = field.type === "email" ? "email" : field.type === "tel" ? "tel" : "text";
      }
      control.required = Boolean(field.required);
      inputs[field.key] = control;
      label.appendChild(caption);
      label.appendChild(control);
      el.appendChild(label);
    }

    let consentBox = null;
    if (form.consent_text) {
      const consentLabel = document.createElement("label");
      consentLabel.className = "wpai-lead-consent";
      consentBox = document.createElement("input");
      consentBox.type = "checkbox";
      const consentText = document.createElement("span");
      consentText.textContent = form.consent_text;
      consentLabel.appendChild(consentBox);
      consentLabel.appendChild(consentText);
      el.appendChild(consentLabel);
    }

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = t("lead.submit");
    el.appendChild(submit);

    el.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      submit.textContent = t("lead.sending");
      const data = {};
      for (const [key, control] of Object.entries(inputs)) data[key] = control.value;
      try {
        const res = await fetch(`${cfg.backendUrl}/widget/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
          body: JSON.stringify({
            form_id: form.id,
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            data,
            consent: consentBox ? consentBox.checked : false,
          }),
        });
        if (!res.ok) throw new Error("invio non riuscito");
        wrap.innerHTML = '<i class="fa-solid fa-check"></i> ' + t("lead.done");
        wrap.className = "wpai-contact done";
      } catch (e2) {
        // niente conferme ottimistiche: se non è stato registrato, dillo e lascia riprovare
        submit.disabled = false;
        submit.textContent = t("common.retry");
      }
    });

    wrap.appendChild(el);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  // ---- Messaggi proattivi -------------------------------------------------------------
  //
  // Le regole arrivano dal backend e vengono valutate qui: nessun round-trip per pagina.
  // Il visitatore comanda: un solo messaggio per pagina, mai a chat aperta o su una
  // conversazione già avviata, e "Non mostrare più" vale per sempre su questo browser.

  function proactiveShownAt(ruleId) {
    try {
      return JSON.parse(localStorage.getItem(PROACTIVE_KEY) || "{}")[String(ruleId)] || 0;
    } catch (e) {
      return 0;
    }
  }

  function rememberProactive(ruleId) {
    try {
      const seen = JSON.parse(localStorage.getItem(PROACTIVE_KEY) || "{}");
      seen[String(ruleId)] = Date.now();
      localStorage.setItem(PROACTIVE_KEY, JSON.stringify(seen));
      sessionStorage.setItem(PROACTIVE_SESSION_KEY + ruleId, "1");
    } catch (e) {
      // storage pieno o disabilitato: al massimo il messaggio riappare, non è un errore
    }
  }

  function proactiveAllowed(rule) {
    // la decisione sta in chat-rules.js; qui si legge soltanto lo storage
    return RULES.proactiveAllowed(rule, {
      optedOut: localStorage.getItem(PROACTIVE_OPTOUT_KEY) === "1",
      seenThisSession: sessionStorage.getItem(PROACTIVE_SESSION_KEY + rule.id) === "1",
      lastShownAt: proactiveShownAt(rule.id),
      now: Date.now(),
    });
  }

  function cartHasItems() {
    // Quante cose ha nel carrello lo sa la piattaforma ospite, non il widget: su WooCommerce è
    // un cookie, altrove sarà altro. Senza adapter la risposta è "non lo so", e le regole
    // proattive che dipendono dal carrello semplicemente non scattano — meglio che indovinare.
    return host.cartItemCount ? host.cartItemCount() > 0 : false;
  }

  function proactiveMatches(rule) {
    return RULES.proactiveMatches(rule, window.location.href, cartHasItems() ? 1 : 0);
  }

  function proactiveVariant(rule) {
    if (!rule.message_b) return "a";
    try {
      const assignments = JSON.parse(localStorage.getItem(PROACTIVE_VARIANT_KEY) || "{}");
      const key = String(rule.id);
      const variant = RULES.proactiveVariant(rule, assignments[key]);
      if (assignments[key] !== variant) {
        assignments[key] = variant;
        localStorage.setItem(PROACTIVE_VARIANT_KEY, JSON.stringify(assignments));
      }
      return variant;
    } catch (e) {
      return "a";
    }
  }

  async function proactiveEvent(ruleId, kind, variant) {
    try {
      await fetch(`${cfg.backendUrl}/widget/proactive/${ruleId}/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
        body: JSON.stringify({ kind, variant }),
      });
    } catch (e) {
      // la misurazione non deve mai disturbare la navigazione
    }
  }

  function showProactive(root, rule, openChat, messages) {
    if (document.getElementById("wpai-proactive")) return;
    const bubble = document.createElement("div");
    bubble.id = "wpai-proactive";
    bubble.className = "wpai-proactive";
    bubble.setAttribute("role", "status");

    const text = document.createElement("p");
    const variant = proactiveVariant(rule);
    const selectedMessage = variant === "b" ? rule.message_b : rule.message;
    text.textContent = selectedMessage;
    const actions = document.createElement("div");
    actions.className = "wpai-proactive-actions";

    const reply = document.createElement("button");
    reply.type = "button";
    reply.className = "wpai-proactive-reply";
    reply.textContent = t("proactive.reply");
    reply.addEventListener("click", () => {
      bubble.remove();
      addMessage(messages, "assistant", selectedMessage);
      openChat();
      proactiveEvent(rule.id, "engagement", variant);
    });

    const dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "wpai-proactive-dismiss";
    dismiss.textContent = t("proactive.later");
    dismiss.addEventListener("click", () => bubble.remove());

    const never = document.createElement("button");
    never.type = "button";
    never.className = "wpai-proactive-never";
    never.textContent = t("proactive.never");
    never.addEventListener("click", () => {
      localStorage.setItem(PROACTIVE_OPTOUT_KEY, "1");
      bubble.remove();
    });

    const close = document.createElement("button");
    close.type = "button";
    close.className = "wpai-proactive-close";
    close.setAttribute("aria-label", t("proactive.close"));
    close.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';
    close.addEventListener("click", () => bubble.remove());

    actions.appendChild(reply);
    actions.appendChild(dismiss);
    actions.appendChild(never);
    bubble.appendChild(close);
    bubble.appendChild(text);
    bubble.appendChild(actions);
    root.appendChild(bubble);

    rememberProactive(rule.id);
    proactiveEvent(rule.id, "impression", variant);
  }

  function startProactive(root, isOpen, openChat, messages, hasConversation) {
    if (localStorage.getItem(PROACTIVE_OPTOUT_KEY) === "1") return;
    fetch(`${cfg.backendUrl}/widget/proactive`, {
      headers: { Authorization: `Bearer ${cfg.apiKey}` },
    })
      .then((res) => (res.ok ? res.json() : { rules: [] }))
      .then((data) => {
        const rules = (data.rules || []).filter((rule) => proactiveAllowed(rule) && proactiveMatches(rule));
        if (rules.length === 0) return;
        // un solo messaggio per pagina: vince la prima regola configurata
        const canShow = () => !isOpen() && !hasConversation() && !document.getElementById("wpai-proactive");
        const fire = (rule) => { if (canShow()) showProactive(root, rule, openChat, messages); };

        const byUrl = rules.find((r) => r.trigger_type === "url");
        const byCart = rules.find((r) => r.trigger_type === "cart");
        const immediate = byUrl || byCart;
        if (immediate) {
          window.setTimeout(() => fire(immediate), 1200); // lascia respirare la pagina
          return;
        }
        const timed = rules.find((r) => r.trigger_type === "time_on_page");
        if (timed) window.setTimeout(() => fire(timed), Math.max(timed.delay_seconds, 1) * 1000);

        const exit = rules.find((r) => r.trigger_type === "exit_intent");
        if (exit) {
          const onLeave = (event) => {
            if (event.clientY > 0) return; // solo verso la barra del browser
            document.removeEventListener("mouseout", onLeave);
            fire(exit);
          };
          document.addEventListener("mouseout", onLeave);
        }
      })
      .catch(() => {
        // nessun messaggio proattivo: la chat resta comunque disponibile
      });
  }

  function supportAvailable() {
    return RULES.supportAvailable(cfg.support, new Date());
  }

  function rememberTicketOffer(conversationId, reason) {
    localStorage.setItem(TICKET_OFFER_KEY, JSON.stringify({
      conversationId: String(conversationId),
      reason: reason || "richiesta del visitatore fuori orario",
      createdAt: Date.now(),
    }));
  }

  function savedTicketOffer(conversationId) {
    try {
      const offer = JSON.parse(localStorage.getItem(TICKET_OFFER_KEY) || "null");
      const isCurrentConversation = offer && offer.conversationId === String(conversationId);
      const isRecent = offer && Number(offer.createdAt) > Date.now() - 24 * 60 * 60 * 1000;
      if (isCurrentConversation && isRecent) return offer;
      localStorage.removeItem(TICKET_OFFER_KEY);
      return null;
    } catch (error) {
      localStorage.removeItem(TICKET_OFFER_KEY);
      return null;
    }
  }

  function clearTicketOffer(container) {
    localStorage.removeItem(TICKET_OFFER_KEY);
    const offer = container.querySelector(".wpai-ticket-offer");
    if (offer) offer.remove();
  }

  function addTicketOffer(container, conversationId, reason) {
    if (!conversationId || container.querySelector(".wpai-ticket-offer")) return;
    rememberTicketOffer(conversationId, reason);
    const wrap = document.createElement("div");
    wrap.className = "wpai-ticket-offer";
    const icon = document.createElement("i");
    icon.className = "fa-regular fa-clock";
    icon.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = "Per questa richiesta serve un operatore";
    const description = document.createElement("span");
    description.textContent = "Il supporto è offline. Apri un ticket e ti risponderemo appena disponibile.";
    copy.appendChild(title);
    copy.appendChild(description);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Apri un ticket";
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Apertura…";
      try {
        const res = await fetch(`${cfg.backendUrl}/chat/ticket`, {
          method: "POST",
          headers: {"Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}`},
          body: JSON.stringify({
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            reason: reason || "richiesta del visitatore fuori orario",
          }),
        });
        if (!res.ok) throw new Error("ticket failed");
        localStorage.removeItem(TICKET_OFFER_KEY);
        localStorage.setItem(ESCALATED_KEY, String(conversationId));
        wrap.remove();
        addMessage(container, "system", "Ticket aperto. Lascia la tua email per ricevere la risposta dell'operatore.");
        addContactForm(container, conversationId);
      } catch (error) {
        button.disabled = false;
        button.textContent = "Riprova ad aprire il ticket";
      }
    });
    wrap.appendChild(icon);
    wrap.appendChild(copy);
    wrap.appendChild(button);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  function setTyping(container, on) {
    let el = container.querySelector("#wpai-typing");
    if (on) {
      if (!el) {
        el = document.createElement("div");
        el.id = "wpai-typing";
        el.className = "wpai-msg assistant wpai-typing";
        el.setAttribute("aria-label", `${cfg.title} sta scrivendo`);
        for (let i = 0; i < 3; i++) el.appendChild(document.createElement("span"));
        container.appendChild(el);
        container.scrollTop = container.scrollHeight;
      }
    } else if (el) {
      el.remove();
    }
  }

  let lastMessageId = 0;
  let pollTimer = null;

  // once handed to an operator, no AI is answering — don't show "AI sta scrivendo"
  function isEscalated(conversationId) {
    return conversationId && localStorage.getItem(ESCALATED_KEY) === String(conversationId);
  }

  async function sendMessage(message, messages, retried) {
    // on a retry, ignore the stored conversation id (it was stale) and start fresh
    const conversationId = retried ? null : localStorage.getItem(CONV_KEY);
    if (!isEscalated(conversationId)) setTyping(messages, true);
    let res;
    try {
      res = await fetch(`${cfg.backendUrl}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${cfg.apiKey}`,
        },
        body: JSON.stringify({
          visitor_id: visitorId(),
          message,
          conversation_id: conversationId ? Number(conversationId) : null,
          conversation_token: conversationId ? localStorage.getItem(CONV_TOKEN_KEY) : null,
          wp_user_token: await userToken(),
          site_url: host.siteUrl || "",
          support_available: supportAvailable(),
          locale: LANG,
        }),
      });
    } finally {
      setTyping(messages, false);
    }
    if (!res.ok) {
      // a stored conversation id that no longer belongs to this client 404s — drop it and retry once
      if (res.status === 404 && conversationId && !retried) {
        localStorage.removeItem(CONV_KEY);
        localStorage.removeItem(CONV_TOKEN_KEY);
        localStorage.removeItem(ESCALATED_KEY);
        return sendMessage(message, messages, true);
      }
      if (await noteLicenceRefusal(res)) throw new Error("licence");
      throw new Error(`chat request failed: ${res.status}`);
    }
    const data = await res.json();
    localStorage.setItem(CONV_KEY, data.conversation_id);
    localStorage.setItem(CONV_TOKEN_KEY, data.conversation_token);
    startPolling(data.conversation_id, messages);
    if (data.status === "escalated") {
      if (localStorage.getItem(ESCALATED_KEY) !== String(data.conversation_id)) {
        localStorage.setItem(ESCALATED_KEY, String(data.conversation_id));
        addMessage(messages, "system", t("chat.escalated"));
        addContactForm(messages, data.conversation_id);
        addLeadForm(messages, data.conversation_id);
      }
    } else if (data.status === "quota_exceeded") {
      addMessage(messages, "system", t("chat.quota"));
    } else if (data.status === "ticket_offered") {
      addTicketOffer(messages, data.conversation_id, data.reason);
    } else {
      localStorage.removeItem(ESCALATED_KEY);
      addMessage(messages, "assistant", data.reply);
      addProducts(messages, data.products);
      addFeedback(messages, data.conversation_id, data.message_id);
    }
  }

  // Streaming variant: renders the reply token-by-token over SSE. Throws only on a *pre-stream*
  // failure (so the caller can safely fall back to the blocking /chat); once the stream has
  // started, mid-stream errors are shown inline and never rethrown (avoids double-sending).
  async function sendMessageStream(message, messages, retried) {
    // on a retry, ignore the stored conversation id (it was stale) and start fresh
    const conversationId = retried ? null : localStorage.getItem(CONV_KEY);
    if (!isEscalated(conversationId)) setTyping(messages, true);
    let res;
    try {
      res = await fetch(`${cfg.backendUrl}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
        body: JSON.stringify({
          visitor_id: visitorId(),
          message,
          conversation_id: conversationId ? Number(conversationId) : null,
          conversation_token: conversationId ? localStorage.getItem(CONV_TOKEN_KEY) : null,
          wp_user_token: await userToken(),
          site_url: host.siteUrl || "",
          support_available: supportAvailable(),
          locale: LANG,
        }),
      });
    } catch (e) {
      setTyping(messages, false);
      throw e; // network error before streaming -> caller falls back
    }
    if (!res.ok || !res.body) {
      setTyping(messages, false);
      // a stored conversation id that no longer belongs to this client 404s — drop it and retry once
      if (res.status === 404 && conversationId && !retried) {
        localStorage.removeItem(CONV_KEY);
        localStorage.removeItem(CONV_TOKEN_KEY);
        localStorage.removeItem(ESCALATED_KEY);
        return sendMessageStream(message, messages, true);
      }
      // 403 di licenza: non ha senso ripiegare sul percorso bloccante, che riceverebbe lo
      // stesso rifiuto. Si ferma qui e lo si dice a chi installa.
      if (await noteLicenceRefusal(res)) throw new Error("licence");
      throw new Error(`stream failed: ${res.status}`);
    }

    let convId = conversationId;
    let bubble = null;
    const onEvent = (evt) => {
      if (evt.type === "start") {
        convId = evt.conversation_id;
        localStorage.setItem(CONV_KEY, convId);
        localStorage.setItem(CONV_TOKEN_KEY, evt.conversation_token);
        startPolling(convId, messages);
      } else if (evt.type === "token") {
        setTyping(messages, false);
        if (!bubble) {
          bubble = document.createElement("div");
          bubble.className = "wpai-msg assistant";
          messages.appendChild(bubble);
        }
        bubble.textContent += evt.text;
        messages.scrollTop = messages.scrollHeight;
      } else if (evt.type === "escalated") {
        setTyping(messages, false);
        if (localStorage.getItem(ESCALATED_KEY) !== String(convId)) {
          localStorage.setItem(ESCALATED_KEY, String(convId));
          addMessage(messages, "system", t("chat.escalated"));
          addContactForm(messages, convId);
          addLeadForm(messages, convId);
        }
      } else if (evt.type === "quota_exceeded") {
        setTyping(messages, false);
        addMessage(messages, "system", t("chat.quota"));
      } else if (evt.type === "ticket_offered") {
        setTyping(messages, false);
        addTicketOffer(messages, convId, evt.reason);
      } else if (evt.type === "done") {
        setTyping(messages, false);
        localStorage.removeItem(ESCALATED_KEY);
        addProducts(messages, evt.products);
        addFeedback(messages, evt.conversation_id, evt.message_id);
      }
    };

    try {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (frame.startsWith("data:")) {
            try { onEvent(JSON.parse(frame.slice(5).trim())); } catch (e) { /* skip bad frame */ }
          }
        }
      }
    } catch (e) {
      // mid-stream failure: surface inline, do NOT rethrow (a fallback would double-send)
      setTyping(messages, false);
      addMessage(messages, "system", "Connessione interrotta, riprova tra poco.");
    }
  }

  // shows "<name> sta scrivendo..." when a human operator is typing; kept at the bottom
  function setOperatorTyping(container, name) {
    const existing = container.querySelector("#wpai-op-typing");
    if (existing) existing.remove();
    if (name) {
      const el = document.createElement("div");
      el.id = "wpai-op-typing";
      el.className = "wpai-msg assistant wpai-typing";
      el.textContent = `${name} ${t("chat.typing")}`;
      container.appendChild(el);
      container.scrollTop = container.scrollHeight;
    }
  }

  // ponytail: polling instead of websockets, good enough for occasional operator replies
  function startPolling(conversationId, messages) {
    if (pollTimer || !conversationId) return;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(
          `${cfg.backendUrl}/conversations/${conversationId}/messages?after_id=${lastMessageId}`,
          {
            headers: {
              Authorization: `Bearer ${cfg.apiKey}`,
              "X-Conversation-Token": localStorage.getItem(CONV_TOKEN_KEY) || "",
            },
          }
        );
        const data = await res.json();
        for (const m of data.messages) {
          lastMessageId = Math.max(lastMessageId, m.id);
          if (m.role === "operator") addMessage(messages, "assistant", m.content);
        }
        setOperatorTyping(messages, data.operator_typing);
        // conversazione chiusa dall'operatore: chiedi il CSAT, se non è già stato dato
        if (data.status === "closed" && !data.rated) addRatingForm(messages, conversationId);
      } catch (err) {
        // silent: next tick retries
      }
    }, 3000);
  }

  async function restoreConversation(messages) {
    const conversationId = localStorage.getItem(CONV_KEY);
    const conversationToken = localStorage.getItem(CONV_TOKEN_KEY);
    if (!conversationId || !conversationToken) return false;

    try {
      const res = await fetch(
        `${cfg.backendUrl}/conversations/${conversationId}/messages?after_id=0`,
        {
          headers: {
            Authorization: `Bearer ${cfg.apiKey}`,
            "X-Conversation-Token": conversationToken,
          },
        }
      );
      if (!res.ok) {
        if ([403, 404].includes(res.status)) {
          localStorage.removeItem(CONV_KEY);
          localStorage.removeItem(CONV_TOKEN_KEY);
          localStorage.removeItem(ESCALATED_KEY);
        }
        return false;
      }

      const data = await res.json();
      const history = Array.isArray(data.messages) ? data.messages : [];
      for (const message of history) {
        lastMessageId = Math.max(lastMessageId, Number(message.id) || 0);
        if (message.role === "user") addMessage(messages, "user", message.content);
        if (["assistant", "operator"].includes(message.role)) {
          addMessage(messages, "assistant", message.content);
        }
        if (message.role === "system") addMessage(messages, "system", message.content);
      }
      setOperatorTyping(messages, data.operator_typing);
      startPolling(conversationId, messages);
      const offer = savedTicketOffer(conversationId);
      if (offer) addTicketOffer(messages, conversationId, offer.reason);
      return history.length > 0;
    } catch (error) {
      return false;
    }
  }

  function init() {
    const root = document.createElement("div");
    root.id = "wpai-root";
    // Il vocabolario delle opzioni sta in `schema.js`, una volta sola: qui c'erano dieci
    // liste di valori ammessi scritte a mano, e la fase 3 ne avrebbe aggiunta un'altra nel
    // pannello. Vedi il debito 5 dell'handoff per come finisce quando divergono.
    root.className = schema.rootClasses(look).join(" ");
    root.style.setProperty("--wpai-accent", look.color);
    document.body.appendChild(root);

    const toggle = document.createElement("button");
    toggle.id = "wpai-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-label", t("chat.open"));
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "wpai-window");
    const toggleLabel = document.createElement("span");
    toggleLabel.textContent = cfg.launcherLabel || "";
    const toggleIcon = document.createElement("i");
    toggleIcon.className = "fa-solid fa-" + look.launcherIcon;
    toggleIcon.setAttribute("aria-hidden", "true");
    if (cfg.launcherLabel) {
      toggle.classList.add("has-label");
      toggle.appendChild(toggleLabel);
    }
    toggle.appendChild(toggleIcon);
    root.appendChild(toggle);

    const win = document.createElement("div");
    win.id = "wpai-window";
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-modal", "false");
    win.setAttribute("aria-label", "Chat con " + cfg.title);

    const header = document.createElement("div");
    header.id = "wpai-header";
    const avatar = document.createElement("img");
    avatar.src = safeHttpUrl(cfg.image);
    avatar.alt = "";
    const headerCopy = document.createElement("div");
    headerCopy.className = "wpai-header-copy";
    const heading = document.createElement("strong");
    heading.textContent = cfg.title;
    const subtitle = document.createElement("small");
    subtitle.textContent = cfg.subtitle;
    headerCopy.appendChild(heading);
    if (look.showStatus) headerCopy.appendChild(subtitle);
    const close = document.createElement("button");
    close.id = "wpai-close";
    close.type = "button";
    close.setAttribute("aria-label", "Chiudi la chat");
    const closeIcon = document.createElement("i");
    closeIcon.className = "fa-solid fa-xmark";
    closeIcon.setAttribute("aria-hidden", "true");
    close.appendChild(closeIcon);
    if (look.showAvatar) header.appendChild(avatar);
    header.appendChild(headerCopy);
    header.appendChild(close);

    const messages = document.createElement("div");
    messages.id = "wpai-messages";
    messages.setAttribute("aria-live", "polite");
    const disclosure = document.createElement("div");
    disclosure.className = "wpai-disclosure";
    disclosure.appendChild(document.createTextNode(
      cfg.aiDisclosure || "Stai parlando con un assistente virtuale basato su intelligenza artificiale."
    ));
    if (cfg.privacyUrl) {
      disclosure.appendChild(document.createTextNode(" Proseguendo accetti la nostra "));
      const privacyLink = document.createElement("a");
      privacyLink.href = safeHttpUrl(cfg.privacyUrl);
      privacyLink.target = "_blank";
      privacyLink.rel = "noopener";
      privacyLink.textContent = "privacy policy";
      disclosure.appendChild(privacyLink);
      disclosure.appendChild(document.createTextNode("."));
    }
    messages.appendChild(disclosure);

    const form = document.createElement("form");
    form.id = "wpai-form";
    const input = document.createElement("input");
    input.id = "wpai-input";
    input.type = "text";
    input.placeholder = cfg.inputPlaceholder || t("chat.placeholder");
    input.autocomplete = "off";
    input.setAttribute("aria-label", "Messaggio");
    const send = document.createElement("button");
    send.type = "submit";
    send.setAttribute("aria-label", "Invia messaggio");
    const sendIcon = document.createElement("i");
    sendIcon.className = "fa-solid fa-arrow-up";
    sendIcon.setAttribute("aria-hidden", "true");
    send.appendChild(sendIcon);
    form.appendChild(input);
    form.appendChild(send);
    win.appendChild(header);
    win.appendChild(messages);
    win.appendChild(form);
    root.appendChild(win);

    function setOpen(open) {
      win.classList.toggle("open", open);
      root.classList.toggle("wpai-is-open", open);
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? t("chat.close") : t("chat.open"));
      toggleIcon.className = open ? "fa-solid fa-xmark" : "fa-solid fa-comment-dots";
      localStorage.setItem(OPEN_KEY, open ? "1" : "0");
      if (open) window.setTimeout(() => input.focus(), 180);
    }

    toggle.addEventListener("click", () => setOpen(!win.classList.contains("open")));
    close.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && win.classList.contains("open")) {
        setOpen(false);
        toggle.focus();
      }
    });

    let hasHistory = false;
    restoreConversation(messages).then((restored) => {
      hasHistory = restored;
      if (!restored && cfg.welcome) addMessage(messages, "assistant", cfg.welcome);
      startProactive(
        root,
        () => win.classList.contains("open"),
        () => setOpen(true),
        messages,
        () => hasHistory,
      );
    });
    if (localStorage.getItem(OPEN_KEY) === "1") setOpen(true);

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      // A ticket offer belongs only to the escalation turn that produced it. If the visitor
      // continues the conversation normally, it must not look like a global availability alert.
      clearTicketOffer(messages);
      addMessage(messages, "user", text);
      input.value = "";
      try {
        if (licenceBlocked) throw new Error("licence");
        await sendMessageStream(text, messages);
      } catch (err) {
        // streaming unavailable (old backend / buffering proxy) — fall back to blocking /chat.
        // Un rifiuto di licenza non è una di quelle cause: riprovare darebbe lo stesso esito.
        try {
          if (licenceBlocked) throw new Error("licence");
          await sendMessage(text, messages);
        } catch (err2) {
          addMessage(messages, "system", t(licenceBlocked ? "chat.unavailable" : "chat.error"));
        }
      }
    });
  }

  init();

  /**
   * Smonta il widget: via il DOM **e** il polling.
   *
   * Fermare il timer non è pulizia formale: senza, un widget rimosso continua a interrogare il
   * backend per sempre. Sulla pagina di un sito non si nota perché la pagina cambia; dentro un
   * pannello a pagina singola — dove il widget monta e smonta a ogni navigazione — resterebbe un
   * poller per ogni visita, tutti attivi insieme.
   */
  return {
    destroy() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      document.getElementById("wpai-root")?.remove();
    },
  };
}

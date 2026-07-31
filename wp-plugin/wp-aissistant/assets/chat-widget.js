(function () {
  const VISITOR_KEY = "wpai_visitor_id";
  const CONV_KEY = "wpai_conversation_id";
  const CONV_TOKEN_KEY = "wpai_conversation_token";
  const ESCALATED_KEY = "wpai_escalated_shown";
  const CONTACT_KEY = "wpai_contact_given";
  const OPEN_KEY = "wpai_chat_open";
  const TICKET_OFFER_KEY = "wpai_ticket_offer";
  const RATED_KEY = "wpai_conversation_rated";

  function visitorId() {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  }

  // Logged-in WP users get a short-lived signed token proving their identity, so the backend
  // can offer full order data instead of the basic status-only tier. Fetched once and cached
  // for the page's lifetime (it's valid 5 minutes, plenty for a chat session).
  let userTokenPromise = null;
  function userToken() {
    if (!WPAI.loggedIn) return Promise.resolve(null);
    if (!userTokenPromise) {
      userTokenPromise = fetch(WPAI.ajaxUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ action: "wpai_user_token" }),
      })
        .then((r) => r.json())
        .then((res) => (res && res.success ? res.data.token : null))
        .catch(() => null);
    }
    return userTokenPromise;
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

      const addButton = document.createElement("button");
      addButton.type = "button";
      addButton.className = "wpai-add-to-cart";
      addButton.textContent = "Aggiungi al carrello";
      let optionsUrl = "";
      addButton.addEventListener("click", async () => {
        if (optionsUrl) {
          window.location.assign(optionsUrl);
          return;
        }
        if (addButton.disabled) return;
        addButton.disabled = true;
        addButton.textContent = "Aggiungo…";
        try {
          const response = await fetch(WPAI.ajaxUrl, {
            method: "POST",
            headers: {"Content-Type": "application/x-www-form-urlencoded"},
            body: new URLSearchParams({
              action: "wpai_add_to_cart",
              nonce: WPAI.cartNonce,
              product_url: p.product_url,
            }),
          });
          const result = await response.json();
          if (!response.ok || !result.success) {
            const error = result && result.data ? result.data : {};
            if (error.product_url) {
              optionsUrl = error.product_url;
              addButton.textContent = "Scegli le opzioni";
              addButton.disabled = false;
              return;
            }
            throw new Error(error.message || "Aggiunta non riuscita");
          }
          addButton.textContent = "✓ Aggiunto";
          addButton.classList.add("is-added");
          if (window.jQuery) {
            window.jQuery(document.body).trigger("added_to_cart", [
              result.data.fragments || {},
              result.data.cart_hash || "",
              window.jQuery(addButton),
            ]);
            window.jQuery(document.body).trigger("wc_fragment_refresh");
          }
          document.body.dispatchEvent(new CustomEvent("wpai_cart_updated", {detail: result.data}));
          addMessage(container, "assistant", `${p.title || "Il prodotto"} è stato aggiunto al carrello.`);
        } catch (error) {
          addButton.textContent = "Riprova";
          addButton.disabled = false;
          addButton.title = error.message || "";
        }
      });
      card.appendChild(addButton);
      wrap.appendChild(card);
    }
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  async function sendFeedback(conversationId, messageId, value, wrap) {
    try {
      await fetch(`${WPAI.backendUrl}/chat/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${WPAI.apiKey}` },
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
    for (const [value, icon, aria] of [["up", "fa-thumbs-up", "Risposta utile"], ["down", "fa-thumbs-down", "Risposta non utile"]]) {
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
    label.textContent = "Lascia la tua email per essere avvisato della risposta:";
    const form = document.createElement("form");
    form.className = "wpai-contact-form";
    const input = document.createElement("input");
    input.type = "email";
    input.required = true;
    input.placeholder = "tua@email.it";
    const btn = document.createElement("button");
    btn.type = "submit";
    btn.textContent = "Avvisami";
    form.appendChild(input);
    form.appendChild(btn);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await fetch(`${WPAI.backendUrl}/chat/contact`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${WPAI.apiKey}` },
          body: JSON.stringify({
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            email: input.value,
            url: window.location.href,
          }),
        });
        localStorage.setItem(CONTACT_KEY, String(conversationId));
        wrap.innerHTML = '<i class="fa-solid fa-check"></i> Ti avviseremo via email appena rispondiamo.';
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
    label.textContent = "Come valuti questa conversazione?";
    const stars = document.createElement("div");
    stars.className = "wpai-rating-stars";
    const form = document.createElement("form");
    form.className = "wpai-contact-form";
    const input = document.createElement("input");
    input.type = "text";
    input.maxLength = 500;
    input.placeholder = "Commento (facoltativo)";
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "Invia";
    form.appendChild(input);
    form.appendChild(submit);

    let chosen = 0;
    const send = async () => {
      if (!chosen) return;
      try {
        const res = await fetch(`${WPAI.backendUrl}/chat/rating`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${WPAI.apiKey}` },
          body: JSON.stringify({
            conversation_id: Number(conversationId),
            conversation_token: localStorage.getItem(CONV_TOKEN_KEY),
            score: chosen,
            comment: input.value || "",
          }),
        });
        if (!res.ok) throw new Error("rating failed");
        wrap.innerHTML = '<i class="fa-solid fa-check"></i> Grazie per la valutazione.';
        wrap.className = "wpai-rating done";
      } catch (e) {
        // niente conferme ottimistiche: se non è stata registrata, dillo
        label.textContent = "Non siamo riusciti a registrare la valutazione. Riprova.";
      }
    };

    for (let value = 1; value <= 5; value += 1) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "wpai-star";
      btn.innerHTML = '<i class="fa-regular fa-star"></i>';
      btn.setAttribute("aria-label", `${value} su 5`);
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

  function supportAvailable() {
    const support = WPAI.support || {};
    if (!support.enabled) return true;
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone: support.timezone,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatToParts(new Date());
      const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
      const dayMap = {Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7};
      const day = dayMap[values.weekday];
      const minute = Number(values.hour) * 60 + Number(values.minute);
      const toMinute = (value) => {
        const [hour, min] = String(value).split(":").map(Number);
        return hour * 60 + min;
      };
      const start = toMinute(support.start);
      const end = toMinute(support.end);
      const days = (support.days || []).map(Number);
      if (start <= end) return days.includes(day) && minute >= start && minute < end;
      const previousDay = day === 1 ? 7 : day - 1;
      return (days.includes(day) && minute >= start) || (days.includes(previousDay) && minute < end);
    } catch (error) {
      return true;
    }
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
        const res = await fetch(`${WPAI.backendUrl}/chat/ticket`, {
          method: "POST",
          headers: {"Content-Type": "application/json", Authorization: `Bearer ${WPAI.apiKey}`},
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
        el.setAttribute("aria-label", `${WPAI.title} sta scrivendo`);
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
      res = await fetch(`${WPAI.backendUrl}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${WPAI.apiKey}`,
        },
        body: JSON.stringify({
          visitor_id: visitorId(),
          message,
          conversation_id: conversationId ? Number(conversationId) : null,
          conversation_token: conversationId ? localStorage.getItem(CONV_TOKEN_KEY) : null,
          wp_user_token: await userToken(),
          site_url: WPAI.siteUrl,
          support_available: supportAvailable(),
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
      throw new Error(`chat request failed: ${res.status}`);
    }
    const data = await res.json();
    localStorage.setItem(CONV_KEY, data.conversation_id);
    localStorage.setItem(CONV_TOKEN_KEY, data.conversation_token);
    startPolling(data.conversation_id, messages);
    if (data.status === "escalated") {
      if (localStorage.getItem(ESCALATED_KEY) !== String(data.conversation_id)) {
        localStorage.setItem(ESCALATED_KEY, String(data.conversation_id));
        addMessage(messages, "system", "La tua richiesta è stata inoltrata a un operatore, ti risponderemo qui appena possibile.");
        addContactForm(messages, data.conversation_id);
      }
    } else if (data.status === "quota_exceeded") {
      addMessage(messages, "system", "Il limite di messaggi è stato raggiunto. Riprova più tardi o contatta il supporto.");
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
      res = await fetch(`${WPAI.backendUrl}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${WPAI.apiKey}` },
        body: JSON.stringify({
          visitor_id: visitorId(),
          message,
          conversation_id: conversationId ? Number(conversationId) : null,
          conversation_token: conversationId ? localStorage.getItem(CONV_TOKEN_KEY) : null,
          wp_user_token: await userToken(),
          site_url: WPAI.siteUrl,
          support_available: supportAvailable(),
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
          addMessage(messages, "system", "La tua richiesta è stata inoltrata a un operatore, ti risponderemo qui appena possibile.");
          addContactForm(messages, convId);
        }
      } else if (evt.type === "quota_exceeded") {
        setTyping(messages, false);
        addMessage(messages, "system", "Il limite di messaggi è stato raggiunto. Riprova più tardi o contatta il supporto.");
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
      el.textContent = `${name} sta scrivendo...`;
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
          `${WPAI.backendUrl}/conversations/${conversationId}/messages?after_id=${lastMessageId}`,
          {
            headers: {
              Authorization: `Bearer ${WPAI.apiKey}`,
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
        `${WPAI.backendUrl}/conversations/${conversationId}/messages?after_id=0`,
        {
          headers: {
            Authorization: `Bearer ${WPAI.apiKey}`,
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
    root.className = [
      WPAI.position === "left" ? "wpai-left" : "wpai-right",
      "wpai-theme-" + (["light", "dark", "auto"].includes(WPAI.theme) ? WPAI.theme : "light"),
      "wpai-motion-" + (["subtle", "playful", "none"].includes(WPAI.motion) ? WPAI.motion : "subtle"),
    ].join(" ");
    root.style.setProperty("--wpai-accent", /^#[0-9a-f]{6}$/i.test(WPAI.color || "") ? WPAI.color : "#635bff");
    document.body.appendChild(root);

    const toggle = document.createElement("button");
    toggle.id = "wpai-toggle";
    toggle.type = "button";
    toggle.setAttribute("aria-label", "Apri la chat");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "wpai-window");
    const toggleLabel = document.createElement("span");
    toggleLabel.textContent = WPAI.launcherLabel || "";
    const toggleIcon = document.createElement("i");
    toggleIcon.className = "fa-solid fa-comment-dots";
    toggleIcon.setAttribute("aria-hidden", "true");
    if (WPAI.launcherLabel) {
      toggle.classList.add("has-label");
      toggle.appendChild(toggleLabel);
    }
    toggle.appendChild(toggleIcon);
    root.appendChild(toggle);

    const win = document.createElement("div");
    win.id = "wpai-window";
    win.setAttribute("role", "dialog");
    win.setAttribute("aria-modal", "false");
    win.setAttribute("aria-label", "Chat con " + WPAI.title);

    const header = document.createElement("div");
    header.id = "wpai-header";
    const avatar = document.createElement("img");
    avatar.src = safeHttpUrl(WPAI.image);
    avatar.alt = "";
    const headerCopy = document.createElement("div");
    headerCopy.className = "wpai-header-copy";
    const heading = document.createElement("strong");
    heading.textContent = WPAI.title;
    const subtitle = document.createElement("small");
    subtitle.textContent = WPAI.subtitle;
    headerCopy.appendChild(heading);
    headerCopy.appendChild(subtitle);
    const close = document.createElement("button");
    close.id = "wpai-close";
    close.type = "button";
    close.setAttribute("aria-label", "Chiudi la chat");
    const closeIcon = document.createElement("i");
    closeIcon.className = "fa-solid fa-xmark";
    closeIcon.setAttribute("aria-hidden", "true");
    close.appendChild(closeIcon);
    header.appendChild(avatar);
    header.appendChild(headerCopy);
    header.appendChild(close);

    const messages = document.createElement("div");
    messages.id = "wpai-messages";
    messages.setAttribute("aria-live", "polite");
    const disclosure = document.createElement("div");
    disclosure.className = "wpai-disclosure";
    disclosure.appendChild(document.createTextNode(
      WPAI.aiDisclosure || "Stai parlando con un assistente virtuale basato su intelligenza artificiale."
    ));
    if (WPAI.privacyUrl) {
      disclosure.appendChild(document.createTextNode(" Proseguendo accetti la nostra "));
      const privacyLink = document.createElement("a");
      privacyLink.href = safeHttpUrl(WPAI.privacyUrl);
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
    input.placeholder = "Scrivi un messaggio…";
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
      toggle.setAttribute("aria-label", open ? "Chiudi la chat" : "Apri la chat");
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

    restoreConversation(messages).then((restored) => {
      if (!restored && WPAI.welcome) addMessage(messages, "assistant", WPAI.welcome);
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
        await sendMessageStream(text, messages);
      } catch (err) {
        // streaming unavailable (old backend / buffering proxy) — fall back to blocking /chat
        try {
          await sendMessage(text, messages);
        } catch (err2) {
          addMessage(messages, "system", "Errore di connessione, riprova tra poco.");
        }
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

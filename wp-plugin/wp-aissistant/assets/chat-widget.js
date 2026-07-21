(function () {
  const VISITOR_KEY = "wpai_visitor_id";
  const CONV_KEY = "wpai_conversation_id";
  const ESCALATED_KEY = "wpai_escalated_shown";

  function visitorId() {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  }

  function addMessage(container, role, text) {
    const el = document.createElement("div");
    el.className = "wpai-msg " + role;
    el.textContent = text;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  function addProducts(container, products) {
    if (!products || !products.length) return;
    const wrap = document.createElement("div");
    wrap.className = "wpai-products";
    for (const p of products) {
      const card = document.createElement("a");
      card.className = "wpai-product-card";
      card.href = p.product_url;
      card.target = "_blank";
      card.rel = "noopener";
      card.innerHTML = `
        <img src="${p.image_url}" alt="" />
        <div class="wpai-product-info">
          <div class="wpai-product-title">${p.title}</div>
          ${p.price ? `<div class="wpai-product-price">${p.price} €</div>` : ""}
        </div>
      `;
      wrap.appendChild(card);
    }
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
        el.textContent = `${WPAI.title} sta scrivendo...`;
        container.appendChild(el);
        container.scrollTop = container.scrollHeight;
      }
    } else if (el) {
      el.remove();
    }
  }

  let lastMessageId = 0;
  let pollTimer = null;

  async function sendMessage(message, messages) {
    const conversationId = localStorage.getItem(CONV_KEY);
    setTyping(messages, true);
    let res;
    try {
      res = await fetch(`${WPAI.backendUrl}/chat?api_key=${encodeURIComponent(WPAI.apiKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
        body: JSON.stringify({
          visitor_id: visitorId(),
          message,
          conversation_id: conversationId ? Number(conversationId) : null,
        }),
      });
    } finally {
      setTyping(messages, false);
    }
    const data = await res.json();
    localStorage.setItem(CONV_KEY, data.conversation_id);
    startPolling(data.conversation_id, messages);
    if (data.status === "escalated") {
      if (localStorage.getItem(ESCALATED_KEY) !== String(data.conversation_id)) {
        localStorage.setItem(ESCALATED_KEY, String(data.conversation_id));
        addMessage(messages, "system", "La tua richiesta è stata inoltrata a un operatore, ti risponderemo qui appena possibile.");
      }
    } else {
      localStorage.removeItem(ESCALATED_KEY);
      addMessage(messages, "assistant", data.reply);
      addProducts(messages, data.products);
    }
  }

  // ponytail: polling instead of websockets, good enough for occasional operator replies
  function startPolling(conversationId, messages) {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(
          `${WPAI.backendUrl}/conversations/${conversationId}/messages?api_key=${encodeURIComponent(WPAI.apiKey)}&after_id=${lastMessageId}`,
          { headers: { "ngrok-skip-browser-warning": "true" } }
        );
        const data = await res.json();
        for (const m of data.messages) {
          lastMessageId = Math.max(lastMessageId, m.id);
          if (m.role === "operator") addMessage(messages, "assistant", m.content);
        }
      } catch (err) {
        // silent: next tick retries
      }
    }, 5000);
  }

  function init() {
    const toggle = document.createElement("button");
    toggle.id = "wpai-toggle";
    toggle.textContent = "💬";
    document.body.appendChild(toggle);

    const win = document.createElement("div");
    win.id = "wpai-window";
    win.innerHTML = `
      <div id="wpai-header">
        <img src="${WPAI.image}" alt="" />
        <span>${WPAI.title}</span>
      </div>
      <div id="wpai-messages"></div>
      <form id="wpai-form">
        <input id="wpai-input" type="text" placeholder="Scrivi un messaggio..." autocomplete="off" />
        <button type="submit">Invia</button>
      </form>
    `;
    document.body.appendChild(win);

    toggle.addEventListener("click", () => win.classList.toggle("open"));

    const messages = win.querySelector("#wpai-messages");
    const form = win.querySelector("#wpai-form");
    const input = win.querySelector("#wpai-input");

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      addMessage(messages, "user", text);
      input.value = "";
      try {
        await sendMessage(text, messages);
      } catch (err) {
        addMessage(messages, "system", "Errore di connessione, riprova tra poco.");
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

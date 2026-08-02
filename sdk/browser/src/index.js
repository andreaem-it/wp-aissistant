const memoryStorage = () => {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: (key) => values.delete(key) };
};

export class WpAissistantError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message); this.name = "WpAissistantError"; this.status = status; this.payload = payload;
  }
}

export class WpAissistantClient {
  constructor({ apiBase, apiKey, storage, storagePrefix = "wpai_sdk", fetchImpl = globalThis.fetch, timeout = 30000 }) {
    if (!apiBase || !apiKey) throw new TypeError("apiBase and apiKey are required");
    const url = new URL(apiBase);
    if (url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) throw new TypeError("apiBase must use HTTPS");
    if (typeof fetchImpl !== "function") throw new TypeError("fetch is not available");
    this.apiBase = url.toString().replace(/\/$/, ""); this.apiKey = apiKey; this.fetchImpl = fetchImpl;
    this.timeout = timeout; this.storage = storage || globalThis.localStorage || memoryStorage(); this.prefix = storagePrefix;
  }
  get session() { return { visitorId: this.storage.getItem(`${this.prefix}:visitor`) || "", conversationId: Number(this.storage.getItem(`${this.prefix}:conversation`)) || null, conversationToken: this.storage.getItem(`${this.prefix}:token`) || "" }; }
  reset() { for (const key of ["visitor", "conversation", "token"]) this.storage.removeItem(`${this.prefix}:${key}`); }
  visitorId() {
    let value = this.session.visitorId;
    if (!value) { value = globalThis.crypto?.randomUUID?.() || `visitor_${Date.now()}_${Math.random().toString(36).slice(2)}`; this.storage.setItem(`${this.prefix}:visitor`, value); }
    return value;
  }
  async request(path, { method = "GET", body, query, conversationToken } = {}) {
    const url = new URL(`${this.apiBase}${path}`);
    for (const [key, value] of Object.entries(query || {})) if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const response = await this.fetchImpl(url, { method, signal: controller.signal, headers: { Authorization: `Bearer ${this.apiKey}`, ...(body ? { "Content-Type": "application/json" } : {}), ...(conversationToken ? { "X-Conversation-Token": conversationToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
      const text = await response.text(); let payload = null;
      try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
      if (!response.ok) throw new WpAissistantError(payload?.detail || `Request failed (${response.status})`, response.status, payload);
      return payload;
    } catch (error) { if (error?.name === "AbortError") throw new WpAissistantError("Request timed out"); throw error; }
    finally { clearTimeout(timer); }
  }
  remember(payload) {
    if (payload?.conversation_id) this.storage.setItem(`${this.prefix}:conversation`, payload.conversation_id);
    if (payload?.conversation_token) this.storage.setItem(`${this.prefix}:token`, payload.conversation_token);
    return payload;
  }
  send(message, options = {}) {
    const current = this.session;
    return this.request("/chat", { method: "POST", body: { visitor_id: this.visitorId(), message, ...(current.conversationId ? { conversation_id: current.conversationId, conversation_token: current.conversationToken } : {}), locale: options.locale || globalThis.navigator?.language || "it", support_available: options.supportAvailable ?? true, site_url: options.siteUrl || globalThis.location?.href || "", ...(options.wpUserToken ? { wp_user_token: options.wpUserToken } : {}) } }).then((payload) => this.remember(payload));
  }
  async *stream(message, options = {}) {
    const current = this.session;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const response = await this.fetchImpl(`${this.apiBase}/chat/stream`, {
        method: "POST", signal: controller.signal,
        headers: { Authorization: `Bearer ${this.apiKey}`, "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ visitor_id: this.visitorId(), message, ...(current.conversationId ? { conversation_id: current.conversationId, conversation_token: current.conversationToken } : {}), locale: options.locale || globalThis.navigator?.language || "it", support_available: options.supportAvailable ?? true, site_url: options.siteUrl || globalThis.location?.href || "", ...(options.wpUserToken ? { wp_user_token: options.wpUserToken } : {}) }),
      });
      if (!response.ok || !response.body) throw new WpAissistantError(`Stream failed (${response.status})`, response.status);
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { done, value } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const frames = buffer.split("\n\n"); buffer = frames.pop() || "";
        for (const frame of frames) {
          const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!data) continue;
          let event; try { event = JSON.parse(data); } catch { throw new WpAissistantError("Invalid stream event"); }
          this.remember(event); yield event;
        }
        if (done) break;
      }
    } catch (error) { if (error?.name === "AbortError") throw new WpAissistantError("Request timed out"); throw error; }
    finally { clearTimeout(timer); }
  }
  messages({ afterId = 0, limit = 200 } = {}) {
    const current = this.session;
    if (!current.conversationId || !current.conversationToken) return Promise.resolve({ status: "new", messages: [], rated: false });
    return this.request(`/conversations/${current.conversationId}/messages`, { query: { after_id: afterId, limit }, conversationToken: current.conversationToken });
  }
  feedback(messageId, value) { return this.conversationPost("/chat/feedback", { message_id: messageId, value }); }
  contact(email, url = globalThis.location?.href || "") { return this.conversationPost("/chat/contact", { email, url }); }
  ticket(reason) { return this.conversationPost("/chat/ticket", { reason }); }
  rating(score, comment = "") { return this.conversationPost("/chat/rating", { score, comment }); }
  conversationPost(path, fields) {
    const current = this.session;
    if (!current.conversationId || !current.conversationToken) throw new WpAissistantError("No active conversation");
    return this.request(path, { method: "POST", body: { conversation_id: current.conversationId, conversation_token: current.conversationToken, ...fields } });
  }
  leadForm(trigger = "escalation") { return this.request("/widget/lead-form", { query: { trigger } }); }
  submitLead(formId, data, consent = false) {
    const current = this.session;
    return this.request("/widget/leads", { method: "POST", body: { form_id: formId, data, consent, ...(current.conversationId ? { conversation_id: current.conversationId, conversation_token: current.conversationToken } : {}) } });
  }
}

export function createClient(options) { return new WpAissistantClient(options); }

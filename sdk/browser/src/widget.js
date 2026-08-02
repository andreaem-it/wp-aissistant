import { createClient } from "./index.js";

const BaseElement = globalThis.HTMLElement || class {};

function node(tag, className, text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

export class WpAissistantChatElement extends BaseElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const apiBase = this.getAttribute("api-base"); const apiKey = this.getAttribute("api-key");
    if (!apiBase || !apiKey) { this.textContent = "Configurazione assistente incompleta"; return; }
    this.client = createClient({ apiBase, apiKey, storagePrefix: this.getAttribute("storage-prefix") || "wpai_headless" });
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `<style>
      :host{--wpai-accent:#6657e8;--wpai-bg:#fff;--wpai-text:#171722;--wpai-muted:#737386;font:14px/1.45 system-ui,sans-serif;color:var(--wpai-text)}
      *{box-sizing:border-box}.toggle{border:0;border-radius:999px;background:var(--wpai-accent);color:#fff;padding:12px 17px;font:inherit;font-weight:700;cursor:pointer;box-shadow:0 8px 28px #0002}
      .panel{margin-top:10px;width:min(380px,calc(100vw - 32px));height:min(580px,70vh);border:1px solid #dedee8;border-radius:20px;background:var(--wpai-bg);box-shadow:0 20px 60px #0003;overflow:hidden;display:grid;grid-template-rows:auto auto 1fr auto}
      .panel[hidden]{display:none}.head{padding:15px 17px;font-weight:750;border-bottom:1px solid #ececf2}.notice{padding:7px 16px;text-align:center;color:var(--wpai-muted);font-size:10px}.notice a{color:inherit}.messages{padding:14px;overflow:auto;display:flex;flex-direction:column;gap:9px}.message{max-width:85%;padding:9px 12px;border-radius:14px;background:#f0eff8;white-space:pre-wrap}.message.user{align-self:flex-end;background:var(--wpai-accent);color:#fff}.message.error{background:#fff0f0;color:#9a2424}.composer{display:flex;gap:8px;padding:12px;border-top:1px solid #ececf2}.composer input{min-width:0;flex:1;border:1px solid #d8d8e3;border-radius:12px;padding:10px 12px;font:inherit}.composer button{border:0;border-radius:12px;background:var(--wpai-accent);color:#fff;padding:0 15px;font-weight:700}.composer button:disabled{opacity:.55}
    </style>`;
    this.toggle = node("button", "toggle", this.getAttribute("button-label") || "Chat");
    this.toggle.type = "button"; this.toggle.setAttribute("aria-expanded", "false");
    this.panel = node("section", "panel"); this.panel.hidden = true; this.panel.setAttribute("aria-label", this.getAttribute("title") || "Assistente virtuale");
    this.panel.append(node("header", "head", this.getAttribute("title") || "Come possiamo aiutarti?"));
    const notice = node("div", "notice", this.getAttribute("disclosure") || "Stai parlando con un assistente AI. Proseguendo accetti la nostra ");
    const privacy = this.getAttribute("privacy-url");
    if (privacy) { const link = node("a", "", "privacy policy"); link.href = privacy; link.target = "_blank"; link.rel = "noopener"; notice.append(link); }
    this.panel.append(notice); this.messages = node("div", "messages"); this.messages.setAttribute("aria-live", "polite"); this.panel.append(this.messages);
    this.form = node("form", "composer"); this.input = document.createElement("input"); this.input.name = "message"; this.input.required = true; this.input.maxLength = 4000; this.input.placeholder = this.getAttribute("placeholder") || "Scrivi un messaggio…"; this.input.setAttribute("aria-label", "Messaggio");
    this.submit = node("button", "", "Invia"); this.submit.type = "submit"; this.form.append(this.input, this.submit); this.panel.append(this.form); root.append(this.toggle, this.panel);
    this.toggle.addEventListener("click", () => this.setOpen(this.panel.hidden)); this.form.addEventListener("submit", (event) => this.onSubmit(event));
    this.restore();
  }

  setOpen(open) { this.panel.hidden = !open; this.toggle.setAttribute("aria-expanded", String(open)); if (open) this.input.focus(); }
  addMessage(role, text) { const message = node("div", `message ${role}`, text); this.messages.append(message); this.messages.scrollTop = this.messages.scrollHeight; return message; }
  async restore() {
    try { const result = await this.client.messages(); for (const message of result.messages || []) this.addMessage(message.role === "user" ? "user" : "assistant", message.content); }
    catch { this.client.reset(); }
  }
  async onSubmit(event) {
    event.preventDefault(); const text = this.input.value.trim(); if (!text || this.submit.disabled) return;
    this.input.value = ""; this.addMessage("user", text); this.submit.disabled = true; const answer = this.addMessage("assistant", "");
    try {
      for await (const item of this.client.stream(text, { locale: this.getAttribute("locale") || navigator.language })) {
        if (item.type === "token") answer.textContent += item.text;
        if (item.type === "escalated") answer.textContent = "Ti metto in contatto con il supporto umano.";
        if (item.type === "ticket_offered") answer.textContent = "Il supporto non è disponibile ora. Puoi lasciare una richiesta.";
        this.dispatchEvent(new CustomEvent("wpai-event", { detail: item }));
      }
    } catch (error) { answer.classList.add("error"); answer.textContent = "Non riesco a rispondere in questo momento. Riprova."; this.dispatchEvent(new CustomEvent("wpai-error", { detail: { message: error.message } })); }
    finally { this.submit.disabled = false; this.input.focus(); }
  }
}

export function registerWpAissistantChat(registry = globalThis.customElements) {
  if (registry && !registry.get("wpai-chat")) registry.define("wpai-chat", WpAissistantChatElement);
  return WpAissistantChatElement;
}

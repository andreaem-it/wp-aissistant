import { useEffect, useState } from "react";
import { Inbox, MessageCircle, Send, Save, CheckCircle2, RotateCcw } from "lucide-react";
import { api } from "./api.js";

function initialsOf(visitorId) {
  return (visitorId || "??").slice(0, 2).toUpperCase();
}

// replace {key} tokens with the operator-filled info value; leave unknown/empty ones as-is
function fillPlaceholders(body, values) {
  return body.replace(/\{(\w+)\}/g, (m, key) =>
    values && values[key] != null && values[key] !== "" ? values[key] : m
  );
}

export default function Conversations() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const [canned, setCanned] = useState([]);
  const [fields, setFields] = useState([]);
  const [infoValues, setInfoValues] = useState({});
  const [savingInfo, setSavingInfo] = useState(false);

  const loadList = () => api.conversations().then(setItems).catch(() => {});
  const loadMessages = (id) => api.messages(id).then((d) => setMessages(d.messages)).catch(() => {});

  // static-ish per-client config, loaded once
  useEffect(() => {
    api.cannedResponses().then(setCanned).catch(() => {});
    api.infoFields().then(setFields).catch(() => {});
  }, []);

  useEffect(() => {
    loadList();
    const id = setInterval(loadList, 10000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setDraft("");
    loadMessages(selected);
    api.conversationInfo(selected).then((d) => setInfoValues(d.info || {})).catch(() => setInfoValues({}));
    const id = setInterval(() => loadMessages(selected), 4000);
    return () => clearInterval(id);
  }, [selected]);

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected) return;
    setSending(true);
    try {
      await api.replyConversation(selected, text);
      setDraft("");
      await loadMessages(selected);
      loadList();
    } finally {
      setSending(false);
    }
  };

  // ping the "operator is typing" state at most once every 2.5s while typing
  const [lastTyping, setLastTyping] = useState(0);
  const pingTyping = () => {
    if (!selected) return;
    const now = Date.now();
    if (now - lastTyping > 2500) {
      setLastTyping(now);
      api.typing(selected).catch(() => {});
    }
  };

  const insertCanned = (body) => {
    const filled = fillPlaceholders(body, infoValues);
    setDraft((prev) => (prev ? prev + "\n" : "") + filled);
  };

  const saveInfo = async () => {
    if (!selected) return;
    setSavingInfo(true);
    try {
      await api.setConversationInfo(selected, infoValues);
    } finally {
      setSavingInfo(false);
    }
  };

  const selectedConv = items.find((x) => x.conversation.id === selected)?.conversation;
  const changeStatus = async (status) => {
    if (!selected) return;
    await api.setConversationStatus(selected, status);
    loadList();
  };

  return (
    <div>
      <h1 className="wpai-page-title">Conversazioni</h1>
      <div className="wpai-split">
        <div className="wpai-conv-list">
          {items.length === 0 && (
            <div className="wpai-empty">
              <Inbox size={28} strokeWidth={1.5} />
              <p>Nessuna conversazione ancora.</p>
            </div>
          )}
          {items.map(({ conversation: c, last_message }) => (
            <button
              key={c.id}
              className={"wpai-conv-item" + (c.id === selected ? " active" : "")}
              onClick={() => setSelected(c.id)}
            >
              <div className="wpai-conv-avatar">{initialsOf(c.visitor_id)}</div>
              <div className="wpai-conv-item-body">
                <div className="meta">
                  #{c.id} · <span className={`wpai-badge ${c.status}`}>{c.status}</span>
                </div>
                <div className="preview">{last_message || "—"}</div>
              </div>
            </button>
          ))}
        </div>

        <div className="wpai-conv-panel">
          {!selected ? (
            <div className="wpai-card wpai-thread">
              <div className="wpai-empty" style={{ margin: "auto" }}>
                <MessageCircle size={28} strokeWidth={1.5} />
                <p>Seleziona una conversazione per leggerla.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="wpai-conv-toolbar">
                <span className={`wpai-badge ${selectedConv?.status || "open"}`}>{selectedConv?.status || "—"}</span>
                {selectedConv?.status === "closed" ? (
                  <button className="wpai-btn ghost" onClick={() => changeStatus("open")}>
                    <RotateCcw size={14} /> Riapri
                  </button>
                ) : (
                  <button className="wpai-btn ghost" onClick={() => changeStatus("closed")}>
                    <CheckCircle2 size={14} /> Chiudi
                  </button>
                )}
              </div>
              <div className="wpai-card wpai-thread">
                {messages.map((m) => (
                  <div key={m.id} className={`wpai-bubble ${m.role}`}>{m.content}</div>
                ))}
              </div>
              <form className="wpai-reply-bar" onSubmit={(e) => { e.preventDefault(); send(); }}>
                <textarea
                  rows={1}
                  value={draft}
                  onChange={(e) => { setDraft(e.target.value); pingTyping(); }}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Rispondi come operatore… (Invio per inviare, Shift+Invio a capo)"
                />
                <button className="wpai-btn" type="submit" disabled={sending || !draft.trim()}>
                  <Send size={15} /> {sending ? "Invio…" : "Invia"}
                </button>
              </form>
            </>
          )}
        </div>

        {selected && (
          <aside className="wpai-conv-side">
            {fields.length > 0 && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>Informazioni</div>
                {fields.map((f) => (
                  <div key={f.id} className="wpai-field" style={{ marginBottom: 8 }}>
                    <label>{f.label}</label>
                    <input
                      value={infoValues[f.key] || ""}
                      onChange={(e) => setInfoValues((v) => ({ ...v, [f.key]: e.target.value }))}
                      placeholder={`{${f.key}}`}
                    />
                  </div>
                ))}
                <button className="wpai-btn ghost" onClick={saveInfo} disabled={savingInfo}>
                  <Save size={14} /> {savingInfo ? "Salvataggio…" : "Salva"}
                </button>
              </div>
            )}

            {canned.length > 0 && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>Risposte predefinite</div>
                <div className="wpai-canned-list">
                  {canned.map((c) => (
                    <button
                      key={c.id}
                      className="wpai-canned-btn"
                      title={c.body}
                      onClick={() => insertCanned(c.body)}
                    >
                      {c.title}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {fields.length === 0 && canned.length === 0 && (
              <div className="wpai-card" style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                Configura risposte predefinite e campi info in <b>Configurazione</b>.
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

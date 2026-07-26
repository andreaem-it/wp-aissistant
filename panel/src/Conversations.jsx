import { useEffect, useState } from "react";
import { Inbox, MessageCircle, Send } from "lucide-react";
import { api } from "./api.js";

function initialsOf(visitorId) {
  return (visitorId || "??").slice(0, 2).toUpperCase();
}

export default function Conversations() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const loadList = () => api.conversations().then(setItems);
  const loadMessages = (id) => api.messages(id).then((d) => setMessages(d.messages));

  useEffect(() => { loadList(); }, []);

  useEffect(() => {
    if (!selected) return;
    loadMessages(selected);
    setDraft("");
  }, [selected]);

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected) return;
    setSending(true);
    try {
      await api.replyConversation(selected, text);
      setDraft("");
      await loadMessages(selected);
      loadList(); // status may have changed (escalated -> open)
    } finally {
      setSending(false);
    }
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
              <div className="wpai-card wpai-thread">
                {messages.map((m) => (
                  <div key={m.id} className={`wpai-bubble ${m.role}`}>
                    {m.content}
                  </div>
                ))}
              </div>
              <form
                className="wpai-reply-bar"
                onSubmit={(e) => { e.preventDefault(); send(); }}
              >
                <textarea
                  rows={1}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                  }}
                  placeholder="Rispondi come operatore… (Invio per inviare, Shift+Invio a capo)"
                />
                <button className="wpai-btn" type="submit" disabled={sending || !draft.trim()}>
                  <Send size={15} /> {sending ? "Invio…" : "Invia"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

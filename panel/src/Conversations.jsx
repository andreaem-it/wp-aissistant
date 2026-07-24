import { useEffect, useState } from "react";
import { Inbox, MessageCircle } from "lucide-react";
import { api } from "./api.js";

function initialsOf(visitorId) {
  return (visitorId || "??").slice(0, 2).toUpperCase();
}

export default function Conversations() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    api.conversations().then(setItems);
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.messages(selected).then((d) => setMessages(d.messages));
  }, [selected]);

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
        <div className="wpai-card wpai-thread">
          {!selected && (
            <div className="wpai-empty" style={{ margin: "auto" }}>
              <MessageCircle size={28} strokeWidth={1.5} />
              <p>Seleziona una conversazione per leggerla.</p>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`wpai-bubble ${m.role}`}>
              {m.content}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "./api.js";

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
      <h1>Conversazioni</h1>
      <div className="wpai-split">
        <div className="wpai-conv-list">
          {items.length === 0 && <p>Nessuna conversazione ancora.</p>}
          {items.map(({ conversation: c, last_message }) => (
            <button
              key={c.id}
              className={"wpai-conv-item" + (c.id === selected ? " active" : "")}
              onClick={() => setSelected(c.id)}
            >
              <div className="meta">
                #{c.id} · {c.visitor_id.slice(0, 8)} ·{" "}
                <span className={`wpai-badge ${c.status}`}>{c.status}</span>
              </div>
              <div className="preview">{last_message || "—"}</div>
            </button>
          ))}
        </div>
        <div className="wpai-card wpai-thread">
          {!selected && <p>Seleziona una conversazione.</p>}
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

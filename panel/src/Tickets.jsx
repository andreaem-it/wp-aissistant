import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function Tickets() {
  const [items, setItems] = useState([]);
  const [drafts, setDrafts] = useState({});

  const load = () => api.tickets("open").then(setItems);
  useEffect(() => { load(); }, []);

  const send = async (id) => {
    await api.replyTicket(id, drafts[id] || "");
    setDrafts((d) => ({ ...d, [id]: "" }));
    load();
  };

  return (
    <div>
      <h1>Ticket aperti</h1>
      {items.length === 0 && <p>Nessun ticket aperto.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {items.map(({ ticket, conversation }) => (
          <div key={ticket.id} className="wpai-card">
            <p style={{ marginTop: 0 }}>
              <b>#{ticket.id}</b> conversazione #{conversation.id} — {ticket.reason}
            </p>
            <textarea
              rows={2}
              style={{ width: "100%", marginBottom: 8 }}
              value={drafts[ticket.id] || ""}
              onChange={(e) => setDrafts((d) => ({ ...d, [ticket.id]: e.target.value }))}
              placeholder="Scrivi la risposta per il cliente..."
            />
            <button className="wpai-btn" onClick={() => send(ticket.id)}>Rispondi</button>
          </div>
        ))}
      </div>
    </div>
  );
}

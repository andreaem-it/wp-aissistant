import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
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
      <h1 className="wpai-page-title">Ticket aperti</h1>
      {items.length === 0 && (
        <div className="wpai-empty">
          <CheckCircle2 size={28} strokeWidth={1.5} />
          <p>Nessun ticket aperto — tutto gestito.</p>
        </div>
      )}
      <div className="wpai-ticket-list">
        {items.map(({ ticket, conversation }) => (
          <div key={ticket.id} className="wpai-card">
            <p className="wpai-ticket-head">
              <b>#{ticket.id}</b> · conversazione #{conversation.id}
            </p>
            <p className="wpai-ticket-reason">{ticket.reason}</p>
            <textarea
              rows={2}
              style={{ marginTop: 10, marginBottom: 10 }}
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

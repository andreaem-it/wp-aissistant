import { useEffect, useState } from "react";
import { CheckCircle2, Mail, ExternalLink } from "lucide-react";
import { api } from "./api.js";

const ROLE_LABEL = { user: "Visitatore", assistant: "AI", operator: "Operatore" };

function TicketCard({ ticket, conversation, draft, setDraft, onReply, sending }) {
  const [messages, setMessages] = useState(null);

  useEffect(() => {
    api.messages(conversation.id).then((d) => setMessages(d.messages || [])).catch(() => setMessages([]));
  }, [conversation.id]);

  return (
    <div className="wpai-card">
      <p className="wpai-ticket-head">
        <b>#{ticket.id}</b> · conversazione #{conversation.id}
      </p>
      <p className="wpai-ticket-reason">{ticket.reason}</p>

      {(conversation.visitor_email || conversation.visitor_url) && (
        <div className="wpai-ticket-meta">
          {conversation.visitor_email && (
            <a href={`mailto:${conversation.visitor_email}`}><Mail size={13} /> {conversation.visitor_email}</a>
          )}
          {conversation.visitor_url && (
            <a href={conversation.visitor_url} target="_blank" rel="noopener"><ExternalLink size={13} /> pagina</a>
          )}
        </div>
      )}

      <div className="wpai-ticket-thread">
        {messages === null && <p className="dim">Caricamento conversazione…</p>}
        {messages && messages.length === 0 && <p className="dim">Nessun messaggio nella conversazione.</p>}
        {messages && messages.map((m) => (
          <div key={m.id} className={"wpai-tmsg " + m.role}>
            <span className="wpai-tmsg-role">{ROLE_LABEL[m.role] || m.role}</span>
            <span className="wpai-tmsg-text">{m.content}</span>
          </div>
        ))}
      </div>

      <textarea
        rows={2}
        style={{ marginTop: 10, marginBottom: 10 }}
        value={draft || ""}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="Scrivi la risposta per il cliente..."
      />
      <button className="wpai-btn" onClick={() => onReply(ticket.id)} disabled={sending || !(draft || "").trim()}>
        {sending ? "Invio…" : "Rispondi"}
      </button>
    </div>
  );
}

export default function Tickets() {
  const [items, setItems] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [sendingId, setSendingId] = useState(null);

  const load = () => api.tickets("open").then(setItems).catch(() => {});
  useEffect(() => {
    load();
    const id = setInterval(load, 10000); // surface new tickets without a manual reload
    return () => clearInterval(id);
  }, []);

  const send = async (id) => {
    if (sendingId) return; // guard against double-submit -> duplicate replies
    setSendingId(id);
    try {
      await api.replyTicket(id, drafts[id] || "");
      setDrafts((d) => ({ ...d, [id]: "" }));
      load();
    } finally {
      setSendingId(null);
    }
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
          <TicketCard
            key={ticket.id}
            ticket={ticket}
            conversation={conversation}
            draft={drafts[ticket.id]}
            setDraft={(v) => setDrafts((d) => ({ ...d, [ticket.id]: v }))}
            onReply={send}
            sending={sendingId === ticket.id}
          />
        ))}
      </div>
    </div>
  );
}

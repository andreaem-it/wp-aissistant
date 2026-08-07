import { useEffect, useState } from "react";
import { CheckCircle2, Mail, ExternalLink, LifeBuoy, Send, Trash2 } from "lucide-react";
import { api } from "./api.js";
import Loading from "./Loading.jsx";

const ROLE_LABEL = { user: "Visitatore", assistant: "AI", operator: "Operatore" };

const PROVIDER_LABEL = { zendesk: "Zendesk", freshdesk: "Freshdesk" };

function TicketCard({ ticket, conversation, helpdeskExports = {}, connections, draft, setDraft, onReply, sending, onExport, exporting }) {
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
        {messages === null && <Loading inline label="Caricamento della conversazione…" />}
        {messages && messages.length === 0 && <p className="dim">Nessun messaggio nella conversazione.</p>}
        {messages && messages.map((m) => (
          <div key={m.id} className={"wpai-tmsg " + m.role}>
            <span className="wpai-tmsg-role">{ROLE_LABEL[m.role] || m.role}</span>
            <span className="wpai-tmsg-text">{m.content}</span>
          </div>
        ))}
      </div>

      {connections.length > 0 && (
        <div className="wpai-ticket-handoff">
          <span><LifeBuoy size={14} /> Passa al tuo helpdesk</span>
          <div>
            {connections.map((connection) => {
              const result = helpdeskExports[connection.provider];
              return (
                <button
                  key={connection.provider}
                  className="wpai-btn wpai-btn-secondary wpai-btn-small"
                  onClick={() => onExport(ticket.id, connection.provider)}
                  disabled={exporting}
                  title={result?.error || ""}
                >
                  {result?.status === "delivered" ? <CheckCircle2 size={13} /> : <Send size={13} />}
                  {result?.status === "delivered" ? `${PROVIDER_LABEL[connection.provider]} · inviato` :
                    result?.status === "failed" ? `Riprova ${PROVIDER_LABEL[connection.provider]}` :
                    `Invia a ${PROVIDER_LABEL[connection.provider]}`}
                </button>
              );
            })}
          </div>
        </div>
      )}

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
  const [connections, setConnections] = useState([]);
  const [accounts, setAccounts] = useState({ zendesk: "", freshdesk: "" });
  const [savingProvider, setSavingProvider] = useState(null);
  const [exportingKey, setExportingKey] = useState("");

  const load = () => api.tickets("open").then(setItems).catch(() => {});
  const loadConnections = () => api.helpdeskConnections().then((data) => {
    setConnections((data.connections || []).filter((row) => row.enabled));
    setAccounts((current) => ({
      ...current,
      ...(data.connections || []).reduce((result, row) => ({ ...result, [row.provider]: row.external_account_id }), {}),
    }));
  }).catch(() => {});
  useEffect(() => {
    load();
    loadConnections();
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

  const saveConnection = async (provider) => {
    const external_account_id = (accounts[provider] || "").trim();
    if (!external_account_id) return;
    setSavingProvider(provider);
    try {
      await api.setHelpdeskConnection(provider, { external_account_id, enabled: true });
      await loadConnections();
    } finally { setSavingProvider(null); }
  };

  const removeConnection = async (provider) => {
    setSavingProvider(provider);
    try {
      await api.deleteHelpdeskConnection(provider);
      setAccounts((value) => ({ ...value, [provider]: "" }));
      await loadConnections();
      await load();
    } finally { setSavingProvider(null); }
  };

  const exportTicket = async (ticketId, provider) => {
    const key = `${ticketId}:${provider}`;
    setExportingKey(key);
    try {
      await api.exportTicketToHelpdesk(ticketId, provider);
      await load();
    } finally { setExportingKey(""); }
  };

  return (
    <div>
      <h1 className="wpai-page-title">Ticket aperti</h1>
      <section className="wpai-card wpai-helpdesk-settings">
        <div className="wpai-section-heading">
          <div className="icon"><LifeBuoy size={18} /></div>
          <div><h2>Collega il tuo helpdesk</h2><p>Trasferisci un ticket con contatto e conversazione completa, senza copia e incolla.</p></div>
        </div>
        <div className="wpai-helpdesk-grid">
          {["zendesk", "freshdesk"].map((provider) => {
            const connected = connections.some((row) => row.provider === provider);
            return <div className="wpai-helpdesk-provider" key={provider}>
              <div><b>{PROVIDER_LABEL[provider]}</b><span className={`wpai-badge ${connected ? "ok" : ""}`}>{connected ? "collegato" : "non collegato"}</span></div>
              <p>{provider === "zendesk" ? "Sottodominio o account Zendesk" : "Dominio o account Freshdesk"}</p>
              <div className="wpai-helpdesk-form">
                <input value={accounts[provider] || ""} onChange={(event) => setAccounts((value) => ({ ...value, [provider]: event.target.value }))} placeholder={provider === "zendesk" ? "azienda.zendesk.com" : "azienda.freshdesk.com"} />
                <button className="wpai-btn" disabled={savingProvider === provider || !(accounts[provider] || "").trim()} onClick={() => saveConnection(provider)}>{connected ? "Aggiorna" : "Collega"}</button>
                {connected && <button className="wpai-icon-btn" aria-label={`Scollega ${PROVIDER_LABEL[provider]}`} onClick={() => removeConnection(provider)}><Trash2 size={15} /></button>}
              </div>
            </div>;
          })}
        </div>
        <p className="wpai-helpdesk-note">Le credenziali del provider vengono custodite dall’adapter sicuro; qui salvi solo l’account di destinazione.</p>
      </section>
      {items.length === 0 && (
        <div className="wpai-empty">
          <CheckCircle2 size={28} strokeWidth={1.5} />
          <p>Nessun ticket aperto — tutto gestito.</p>
        </div>
      )}
      <div className="wpai-ticket-list">
        {items.map(({ ticket, conversation, helpdesk_exports }) => (
          <TicketCard
            key={ticket.id}
            ticket={ticket}
            conversation={conversation}
            helpdeskExports={helpdesk_exports}
            connections={connections}
            draft={drafts[ticket.id]}
            setDraft={(v) => setDrafts((d) => ({ ...d, [ticket.id]: v }))}
            onReply={send}
            sending={sendingId === ticket.id}
            onExport={exportTicket}
            exporting={exportingKey.startsWith(`${ticket.id}:`)}
          />
        ))}
      </div>
    </div>
  );
}

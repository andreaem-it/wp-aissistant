import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckCircle2, Mail, ExternalLink, LifeBuoy, Send, Trash2, Inbox, Search,
  MessagesSquare, Plug, ArrowLeft,
} from "lucide-react";
import { api } from "./api.js";
import { formatMoment } from "./activity.js";
import Loading from "./Loading.jsx";
import { PageHeader, SectionTabs, TabPanel } from "./PageLayout.jsx";
import { filterTickets } from "./ticketFilters.js";

const ROLE_LABEL = { user: "Cliente", assistant: "Assistente AI", operator: "Operatore" };
const PROVIDER_LABEL = { zendesk: "Zendesk", freshdesk: "Freshdesk" };
const STATUS_LABEL = { open: "Da gestire", answered: "Con risposta", closed: "Chiusi" };
const CHANNEL_LABEL = { web: "Sito web", email: "Email", whatsapp: "WhatsApp", messenger: "Messenger", instagram: "Instagram" };

const TICKET_SECTIONS = [
  { key: "queue", label: "Coda ticket", description: "Richieste da gestire", Icon: MessagesSquare },
  { key: "helpdesk", label: "Helpdesk collegati", description: "Zendesk e Freshdesk", Icon: Plug },
];

function TicketDetail({ item, connections, draft, setDraft, onReply, sending, onExport, exporting, onBack }) {
  const { ticket, conversation, helpdesk_exports: helpdeskExports = {} } = item;
  const [messages, setMessages] = useState(null);

  useEffect(() => {
    setMessages(null);
    api.messages(conversation.id).then((data) => setMessages(data.messages || [])).catch(() => setMessages([]));
  }, [conversation.id]);

  return (
    <article className="wpai-ticket-detail wpai-card">
      <button className="wpai-ticket-back" type="button" onClick={onBack}>
        <ArrowLeft size={15} /> Torna alla coda
      </button>
      <header className="wpai-ticket-detail-head">
        <div>
          <div className="wpai-ticket-kicker">Ticket #{ticket.id} · Conversazione #{conversation.id}</div>
          <h2>{ticket.reason || "Richiesta di assistenza"}</h2>
          <div className="wpai-ticket-detail-meta">
            <span className={`wpai-badge ${ticket.status === "open" ? "escalated" : ticket.status === "closed" ? "closed" : "open"}`}>
              {STATUS_LABEL[ticket.status] || ticket.status}
            </span>
            <span>{CHANNEL_LABEL[conversation.channel] || conversation.channel || "Sito web"}</span>
            <span>Aperto {formatMoment(ticket.created_at)}</span>
          </div>
        </div>
      </header>

      {(conversation.visitor_email || conversation.visitor_url) && (
        <div className="wpai-ticket-customer">
          <div><strong>Cliente</strong><small>Informazioni disponibili per ricontattarlo</small></div>
          <div>
            {conversation.visitor_email && (
              <a href={`mailto:${conversation.visitor_email}`}><Mail size={13} /> {conversation.visitor_email}</a>
            )}
            {conversation.visitor_url && (
              <a href={conversation.visitor_url} target="_blank" rel="noopener noreferrer"><ExternalLink size={13} /> Pagina visitata</a>
            )}
          </div>
        </div>
      )}

      <section className="wpai-ticket-conversation" aria-label="Conversazione del ticket">
        <div className="wpai-ticket-section-title">Conversazione</div>
        <div className="wpai-ticket-thread">
          {messages === null && <Loading inline label="Caricamento della conversazione…" />}
          {messages?.length === 0 && <p className="dim">Non sono presenti messaggi.</p>}
          {messages?.map((message) => (
            <div key={message.id} className={`wpai-tmsg ${message.role}`}>
              <span className="wpai-tmsg-role">{ROLE_LABEL[message.role] || message.role}</span>
              <span className="wpai-tmsg-text">{message.content}</span>
            </div>
          ))}
        </div>
      </section>

      {ticket.status === "open" ? (
        <section className="wpai-ticket-reply">
          <label htmlFor={`ticket-reply-${ticket.id}`}>Rispondi al cliente</label>
          <p>La risposta verrà aggiunta alla conversazione e il ticket passerà tra quelli con risposta.</p>
          <textarea
            id={`ticket-reply-${ticket.id}`}
            rows={4}
            value={draft || ""}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Scrivi una risposta chiara e completa…"
          />
          <div className="wpai-ticket-reply-actions">
            <span>{(draft || "").length} caratteri</span>
            <button className="wpai-btn" onClick={() => onReply(ticket.id)} disabled={sending || !(draft || "").trim()}>
              <Send size={14} /> {sending ? "Invio in corso…" : "Invia risposta"}
            </button>
          </div>
        </section>
      ) : (
        <div className="wpai-ticket-readonly-note">
          <CheckCircle2 size={17} />
          <span>{ticket.status === "closed" ? "Questo ticket è chiuso." : "È già stata inviata una risposta. Puoi consultare lo storico qui sopra."}</span>
        </div>
      )}

      {connections.length > 0 && (
        <section className="wpai-ticket-handoff">
          <span><LifeBuoy size={14} /> Invia a un helpdesk esterno</span>
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
        </section>
      )}
    </article>
  );
}

function HelpdeskSettings({ connections, accounts, setAccounts, savingProvider, onSave, onRemove }) {
  return (
    <section className="wpai-card wpai-helpdesk-settings">
      <div className="wpai-section-heading">
        <div className="icon"><LifeBuoy size={18} /></div>
        <div><h2>Collega il tuo helpdesk</h2><p>Trasferisci contatto e conversazione completa senza copia e incolla.</p></div>
      </div>
      <div className="wpai-helpdesk-grid">
        {["zendesk", "freshdesk"].map((provider) => {
          const connected = connections.some((row) => row.provider === provider);
          return (
            <div className="wpai-helpdesk-provider" key={provider}>
              <div><b>{PROVIDER_LABEL[provider]}</b><span className={`wpai-badge ${connected ? "ok" : ""}`}>{connected ? "Collegato" : "Non collegato"}</span></div>
              <p>{provider === "zendesk" ? "Inserisci il dominio del tuo account Zendesk." : "Inserisci il dominio del tuo account Freshdesk."}</p>
              <div className="wpai-helpdesk-form">
                <input
                  aria-label={`Account ${PROVIDER_LABEL[provider]}`}
                  value={accounts[provider] || ""}
                  onChange={(event) => setAccounts((value) => ({ ...value, [provider]: event.target.value }))}
                  placeholder={provider === "zendesk" ? "azienda.zendesk.com" : "azienda.freshdesk.com"}
                />
                <button className="wpai-btn" disabled={savingProvider === provider || !(accounts[provider] || "").trim()} onClick={() => onSave(provider)}>
                  {savingProvider === provider ? "Salvataggio…" : connected ? "Aggiorna" : "Collega"}
                </button>
                {connected && <button className="wpai-icon-btn" aria-label={`Scollega ${PROVIDER_LABEL[provider]}`} onClick={() => onRemove(provider)}><Trash2 size={15} /></button>}
              </div>
            </div>
          );
        })}
      </div>
      <p className="wpai-helpdesk-note">Le credenziali restano nell’adapter sicuro; qui viene salvato soltanto l’account di destinazione.</p>
    </section>
  );
}

export default function Tickets() {
  const [section, setSection] = useState("queue");
  const [status, setStatus] = useState("open");
  const [items, setItems] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [drafts, setDrafts] = useState({});
  const [sendingId, setSendingId] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [connections, setConnections] = useState([]);
  const [accounts, setAccounts] = useState({ zendesk: "", freshdesk: "" });
  const [savingProvider, setSavingProvider] = useState(null);
  const [exportingKey, setExportingKey] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    return api.tickets(status)
      .then((rows) => {
        setItems(rows);
        setLoadError("");
        setSelectedId((current) => rows.some(({ ticket }) => ticket.id === current) ? current : rows[0]?.ticket.id || null);
      })
      .catch(() => setLoadError("Non è stato possibile caricare i ticket. Riprova tra poco."))
      .finally(() => setLoading(false));
  }, [status]);

  const loadConnections = useCallback(() => api.helpdeskConnections().then((data) => {
    setConnections((data.connections || []).filter((row) => row.enabled));
    setAccounts((current) => ({
      ...current,
      ...(data.connections || []).reduce((result, row) => ({ ...result, [row.provider]: row.external_account_id }), {}),
    }));
  }).catch(() => {}), []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);
  useEffect(() => { loadConnections(); }, [loadConnections]);

  const filtered = useMemo(() => filterTickets(items, query), [items, query]);
  const selected = items.find(({ ticket }) => ticket.id === selectedId) || null;

  const send = async (id) => {
    if (sendingId) return;
    setSendingId(id);
    setFeedback(null);
    try {
      await api.replyTicket(id, drafts[id] || "");
      setDrafts((value) => ({ ...value, [id]: "" }));
      setFeedback({ type: "success", text: "Risposta inviata. Il ticket è stato spostato tra quelli con risposta." });
      await load();
    } catch (error) {
      setFeedback({
        type: "error",
        text: error?.status === 409
          ? "La finestra di risposta WhatsApp è scaduta. Per ricontattare il cliente usa un modello WhatsApp approvato."
          : "Non è stato possibile inviare la risposta. Riprova tra poco.",
      });
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
    if (!window.confirm(`Scollegare ${PROVIDER_LABEL[provider]}? Non potrai più inviare ticket a questo helpdesk.`)) return;
    setSavingProvider(provider);
    try {
      await api.deleteHelpdeskConnection(provider);
      setAccounts((value) => ({ ...value, [provider]: "" }));
      await loadConnections();
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
      <PageHeader
        eyebrow="Assistenza"
        title="Ticket"
        description="Gestisci le richieste che richiedono l’intervento del team, rispondi al cliente e consulta quelle già lavorate."
      />
      <SectionTabs items={TICKET_SECTIONS} active={section} onChange={setSection} label="Aree dei ticket" />

      <TabPanel active={section} name="queue">
        <div className="wpai-ticket-toolbar">
          <div className="wpai-ticket-statuses" aria-label="Stato dei ticket">
            {Object.entries(STATUS_LABEL).map(([value, label]) => (
              <button key={value} type="button" className={status === value ? "active" : ""} onClick={() => { setStatus(value); setItems([]); setSelectedId(null); setQuery(""); setFeedback(null); }}>
                {label}
              </button>
            ))}
          </div>
          <label className="wpai-ticket-search">
            <Search size={15} />
            <span className="wpai-sr-only">Cerca ticket</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cerca per numero, motivo o email…" />
          </label>
        </div>
        {loadError && <div className="wpai-error" role="alert">{loadError} <button type="button" onClick={load}>Riprova</button></div>}
        {feedback && <div className={`wpai-callout wpai-ticket-feedback ${feedback.type === "error" ? "danger" : ""}`} role="status">{feedback.text}</div>}

        {loading && items.length === 0 ? <Loading /> : items.length === 0 ? (
          <div className="wpai-empty-card">
            {status === "open" ? <CheckCircle2 size={24} /> : <Inbox size={24} />}
            <strong>{status === "open" ? "Nessun ticket da gestire" : `Nessun ticket tra “${STATUS_LABEL[status]}”`}</strong>
            <span>{status === "open" ? "Ottimo: al momento non ci sono richieste in attesa del team." : "Quando un ticket raggiungerà questo stato, lo troverai qui."}</span>
          </div>
        ) : (
          <div className={`wpai-ticket-workspace ${selected ? "has-selection" : ""}`}>
            <aside className="wpai-ticket-queue" aria-label={`${STATUS_LABEL[status]} (${filtered.length})`}>
              <div className="wpai-ticket-queue-head"><strong>{STATUS_LABEL[status]}</strong><span>{filtered.length}</span></div>
              {filtered.map(({ ticket, conversation }) => (
                <button
                  key={ticket.id}
                  type="button"
                  className={ticket.id === selectedId ? "active" : ""}
                  onClick={() => { setSelectedId(ticket.id); setFeedback(null); }}
                >
                  <span className="wpai-ticket-list-top"><b>#{ticket.id}</b><time>{formatMoment(ticket.created_at)}</time></span>
                  <strong>{ticket.reason || "Richiesta di assistenza"}</strong>
                  <small>{conversation.visitor_email || CHANNEL_LABEL[conversation.channel] || "Cliente dal sito"}</small>
                </button>
              ))}
              {filtered.length === 0 && <div className="wpai-ticket-no-results">Nessun ticket corrisponde alla ricerca.</div>}
            </aside>
            {selected ? (
              <TicketDetail
                item={selected}
                connections={connections}
                draft={drafts[selected.ticket.id]}
                setDraft={(value) => setDrafts((current) => ({ ...current, [selected.ticket.id]: value }))}
                onReply={send}
                sending={sendingId === selected.ticket.id}
                onExport={exportTicket}
                exporting={exportingKey.startsWith(`${selected.ticket.id}:`)}
                onBack={() => setSelectedId(null)}
              />
            ) : <div className="wpai-ticket-placeholder"><Inbox size={25} /><span>Seleziona un ticket per vedere i dettagli.</span></div>}
          </div>
        )}
      </TabPanel>

      <TabPanel active={section} name="helpdesk" className="wpai-single-col wide">
        <div className="wpai-section-intro">
          <h2>Integrazioni helpdesk</h2>
          <p>Collega gli strumenti già usati dal team. Dopo il collegamento potrai inviare ogni ticket direttamente dal suo dettaglio.</p>
        </div>
        <HelpdeskSettings
          connections={connections}
          accounts={accounts}
          setAccounts={setAccounts}
          savingProvider={savingProvider}
          onSave={saveConnection}
          onRemove={removeConnection}
        />
      </TabPanel>
    </div>
  );
}

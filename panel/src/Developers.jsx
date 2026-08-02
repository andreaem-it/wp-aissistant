import { Fragment, useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, Trash2, Webhook, Send, RefreshCw } from "lucide-react";
import { api } from "./api.js";
import { formatMoment } from "./activity.js";

const SCOPES = [
  { value: "conversations:read", label: "Leggere le conversazioni" },
  { value: "conversations:write", label: "Rispondere, chiudere ed etichettare" },
  { value: "knowledge:write", label: "Aggiungere contenuti alla knowledge base" },
  { value: "stats:read", label: "Leggere le statistiche" },
];

const DELIVERY_LABELS = { success: "Consegnato", pending: "In attesa di riprova", failed: "Fallito" };
const DELIVERY_CLASS = { success: "ok", pending: "warn", failed: "breach" };

function ApiKeys() {
  const [keys, setKeys] = useState([]);
  const [form, setForm] = useState({ name: "", scopes: ["conversations:read"] });
  const [created, setCreated] = useState(null); // chiave in chiaro, mostrata una sola volta
  const [state, setState] = useState({ loading: true, error: "" });

  const load = useCallback(
    () =>
      api
        .apiKeys()
        .then((rows) => { setKeys(rows); setState({ loading: false, error: "" }); })
        .catch(() => setState({ loading: false, error: "Impossibile caricare le chiavi API." })),
    [],
  );
  useEffect(() => { load(); }, [load]);

  const toggleScope = (scope) =>
    setForm((f) => ({
      ...f,
      scopes: f.scopes.includes(scope) ? f.scopes.filter((s) => s !== scope) : [...f.scopes, scope],
    }));

  const create = async (e) => {
    e.preventDefault();
    if (form.scopes.length === 0) return;
    try {
      const key = await api.createApiKey(form.name.trim(), form.scopes);
      setCreated(key);
      setForm({ name: "", scopes: ["conversations:read"] });
      setState((s) => ({ ...s, error: "" }));
      load();
    } catch {
      setState((s) => ({ ...s, error: "Creazione della chiave non riuscita." }));
    }
  };

  const revoke = async (key) => {
    if (!window.confirm(`Revocare la chiave ${key.prefix}? Le integrazioni che la usano smetteranno di funzionare.`)) return;
    await api.revokeApiKey(key.id);
    if (created && created.id === key.id) setCreated(null);
    load();
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><KeyRound size={15} /> Chiavi API</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Credenziali server-to-server per l'API pubblica <code>/v1</code>, diverse dalla chiave del
        widget: hanno permessi limitati e si possono revocare. La chiave in chiaro viene mostrata
        una sola volta.
      </p>

      {created && (
        <div className="wpai-callout warn" role="status" style={{ display: "block" }}>
          <b>Copia adesso la chiave: non sarà più visibile.</b>
          <code style={{ display: "block", marginTop: 6, wordBreak: "break-all" }}>{created.token}</code>
          <button className="wpai-btn ghost" style={{ marginTop: 8 }} onClick={() => setCreated(null)}>
            Ho copiato la chiave
          </button>
        </div>
      )}

      {state.loading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>}
      {state.error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{state.error}</p>}

      {!state.loading && (
        <table className="wpai-table" style={{ marginBottom: 12 }}>
          <tbody>
            {keys.map((key) => (
              <tr key={key.id} style={key.revoked_at ? { opacity: 0.55 } : undefined}>
                <td>
                  <div style={{ fontWeight: 600 }}>{key.name || "Senza nome"}</div>
                  <code style={{ fontSize: 11.5 }}>{key.prefix}…</code>
                </td>
                <td style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                  {key.scopes.join(", ")}
                  <br />
                  {key.revoked_at
                    ? `Revocata il ${formatMoment(key.revoked_at)}`
                    : key.last_used_at
                      ? `Ultimo uso ${formatMoment(key.last_used_at)}`
                      : "Mai usata"}
                </td>
                <td style={{ textAlign: "right" }}>
                  {!key.revoked_at && (
                    <button className="wpai-icon-btn" title="Revoca" onClick={() => revoke(key)}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {keys.length === 0 && <tr><td style={{ color: "var(--text-muted)" }}>Nessuna chiave.</td></tr>}
          </tbody>
        </table>
      )}

      <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
        <input
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="Nome, es. Integrazione CRM"
          aria-label="Nome della chiave"
        />
        <fieldset style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
          <legend style={{ fontSize: 12, color: "var(--text-muted)" }}>Permessi</legend>
          {SCOPES.map((scope) => (
            <label key={scope.value} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "2px 0" }}>
              <input
                type="checkbox"
                checked={form.scopes.includes(scope.value)}
                onChange={() => toggleScope(scope.value)}
              />
              {scope.label} <code style={{ fontSize: 11 }}>{scope.value}</code>
            </label>
          ))}
        </fieldset>
        <button className="wpai-btn" type="submit" disabled={form.scopes.length === 0} style={{ justifySelf: "start" }}>
          <Plus size={14} /> Crea chiave
        </button>
      </form>
    </div>
  );
}

function Deliveries({ endpointId, availableEvents }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const [replaying, setReplaying] = useState(null);
  const [error, setError] = useState("");
  const [payloadOpen, setPayloadOpen] = useState(null);
  const [filters, setFilters] = useState({ status: "", event: "" });

  const load = useCallback(
    () => api.webhookDeliveries(endpointId, filters).then(setRows).catch(() => setRows([])),
    [endpointId, filters],
  );
  useEffect(() => { if (open) load(); }, [open, load]);
  const replay = async (deliveryId) => {
    setReplaying(deliveryId);
    setError("");
    try {
      const result = await api.replayWebhookDelivery(endpointId, deliveryId);
      await load();
      if (!result.ok) setError(`Nuovo tentativo non riuscito${result.error ? `: ${result.error}` : "."}`);
    } catch {
      setError("Impossibile riprovare la consegna. Verifica che il webhook sia attivo.");
    } finally {
      setReplaying(null);
    }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <button className="wpai-btn ghost" onClick={() => setOpen((v) => !v)}>
        {open ? "Nascondi consegne" : "Mostra consegne"}
      </button>
      {open && (
        <>
          <button className="wpai-btn ghost" style={{ marginLeft: 8 }} onClick={load}>
            <RefreshCw size={13} /> Aggiorna
          </button>
          <div className="wpai-delivery-filters">
            <select aria-label="Filtra consegne per stato" value={filters.status} onChange={(e) => setFilters((value) => ({ ...value, status: e.target.value }))}>
              <option value="">Tutti gli stati</option>
              <option value="success">Consegnati</option>
              <option value="pending">In attesa</option>
              <option value="failed">Falliti</option>
            </select>
            <select aria-label="Filtra consegne per evento" value={filters.event} onChange={(e) => setFilters((value) => ({ ...value, event: e.target.value }))}>
              <option value="">Tutti gli eventi</option>
              {availableEvents.map((event) => <option value={event} key={event}>{event}</option>)}
            </select>
          </div>
          <table className="wpai-table" style={{ marginTop: 8 }}>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.id}>
                <tr>
                  <td style={{ fontSize: 12 }}>{row.event}</td>
                  <td>
                    <span className={`wpai-badge ${DELIVERY_CLASS[row.status] || "ok"}`}>
                      {DELIVERY_LABELS[row.status] || row.status}
                    </span>
                  </td>
                  <td style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                    {row.attempts} tentativi{row.response_status ? ` · HTTP ${row.response_status}` : ""}
                    {row.error ? ` · ${row.error}` : ""}
                    <br />
                    {formatMoment(row.delivered_at || row.created_at)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button className="wpai-btn ghost" onClick={() => setPayloadOpen((id) => id === row.id ? null : row.id)}>
                      {payloadOpen === row.id ? "Nascondi JSON" : "Vedi JSON"}
                    </button>
                    {row.status === "failed" && (
                      <button className="wpai-btn ghost" disabled={replaying === row.id} onClick={() => replay(row.id)}>
                        <RefreshCw size={13} /> {replaying === row.id ? "Riprovo…" : "Riprova"}
                      </button>
                    )}
                  </td>
                </tr>
                {payloadOpen === row.id && <tr className="wpai-payload-row"><td colSpan="4">
                  <div className="wpai-payload-head"><span>Payload inviato</span><code>schema {row.payload?.schema_version || "legacy"}</code></div>
                  <pre>{JSON.stringify(row.payload, null, 2)}</pre>
                </td></tr>}
                </Fragment>
              ))}
              {rows.length === 0 && <tr><td colSpan="4" style={{ color: "var(--text-muted)" }}>Nessuna consegna.</td></tr>}
            </tbody>
          </table>
          {error && <p style={{ color: "var(--red)", fontSize: 12.5, margin: "8px 0 0" }}>{error}</p>}
        </>
      )}
    </div>
  );
}

function Webhooks() {
  const [events, setEvents] = useState([]);
  const [endpoints, setEndpoints] = useState([]);
  const [form, setForm] = useState({ url: "", description: "", events: [] });
  const [created, setCreated] = useState(null); // segreto mostrato una sola volta
  const [error, setError] = useState("");
  const [testing, setTesting] = useState(0);
  const [testResult, setTestResult] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    () =>
      api
        .webhooks()
        .then((data) => { setEvents(data.events); setEndpoints(data.endpoints); setError(""); })
        .catch(() => setError("Impossibile caricare i webhook."))
        .finally(() => setLoading(false)),
    [],
  );
  useEffect(() => { load(); }, [load]);

  const toggleEvent = (event) =>
    setForm((f) => ({
      ...f,
      events: f.events.includes(event) ? f.events.filter((e) => e !== event) : [...f.events, event],
    }));

  const create = async (e) => {
    e.preventDefault();
    if (!form.url.trim()) return;
    try {
      const endpoint = await api.createWebhook(form.url.trim(), form.events, form.description.trim());
      setCreated(endpoint);
      setForm({ url: "", description: "", events: [] });
      setError("");
      load();
    } catch (err) {
      setError(
        err.status === 400
          ? "URL non valido: serve un indirizzo HTTPS pubblico."
          : "Creazione del webhook non riuscita.",
      );
    }
  };

  const toggleActive = async (endpoint) => {
    await api.updateWebhook(endpoint.id, { active: !endpoint.active });
    load();
  };
  const remove = async (endpoint) => {
    if (!window.confirm("Eliminare il webhook e il suo storico consegne?")) return;
    await api.deleteWebhook(endpoint.id);
    load();
  };
  const sendTest = async (endpoint) => {
    setTesting(endpoint.id);
    setTestResult(null);
    try {
      const result = await api.testWebhook(endpoint.id);
      setTestResult({
        id: endpoint.id,
        ok: result.ok,
        text: result.ok
          ? `Consegna riuscita (HTTP ${result.response_status}).`
          : `Consegna non riuscita: ${result.error || `HTTP ${result.response_status}`}.`,
      });
    } catch {
      setTestResult({ id: endpoint.id, ok: false, text: "Invio non riuscito." });
    } finally {
      setTesting(0);
    }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><Webhook size={15} /> Webhook</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Ricevi gli eventi in tempo reale sul tuo endpoint HTTPS. Ogni richiesta è firmata con
        HMAC-SHA256 nell'header <code>X-WPAI-Signature</code> e viene ritentata con backoff fino a
        5 volte.
      </p>

      {created && (
        <div className="wpai-callout warn" role="status" style={{ display: "block" }}>
          <b>Segreto di firma: copialo adesso, non sarà più visibile.</b>
          <code style={{ display: "block", marginTop: 6, wordBreak: "break-all" }}>{created.secret}</code>
          <button className="wpai-btn ghost" style={{ marginTop: 8 }} onClick={() => setCreated(null)}>
            Ho copiato il segreto
          </button>
        </div>
      )}

      {loading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>}
      {error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}

      <div style={{ display: "grid", gap: 12, marginBottom: 12 }}>
        {endpoints.map((endpoint) => (
          <div key={endpoint.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 12 }}>
            <div className="wpai-canned-row">
              <div>
                <div style={{ fontWeight: 600, fontSize: 13, wordBreak: "break-all" }}>{endpoint.url}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                  {endpoint.description ? `${endpoint.description} · ` : ""}
                  {endpoint.events.length ? endpoint.events.join(", ") : "tutti gli eventi"}
                  {!endpoint.active && " · disattivato"}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <button className="wpai-btn ghost" onClick={() => sendTest(endpoint)} disabled={testing === endpoint.id}>
                  <Send size={13} /> {testing === endpoint.id ? "Invio…" : "Test"}
                </button>
                <button className="wpai-btn ghost" onClick={() => toggleActive(endpoint)}>
                  {endpoint.active ? "Disattiva" : "Attiva"}
                </button>
                <button className="wpai-icon-btn" title="Elimina" onClick={() => remove(endpoint)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            {testResult && testResult.id === endpoint.id && (
              <p role="status" style={{ fontSize: 12.5, color: testResult.ok ? "var(--green)" : "var(--red)", margin: "6px 0 0" }}>
                {testResult.text}
              </p>
            )}
            <Deliveries endpointId={endpoint.id} availableEvents={events} />
          </div>
        ))}
        {!loading && endpoints.length === 0 && (
          <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessun webhook configurato.</span>
        )}
      </div>

      <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
        <input
          value={form.url}
          onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))}
          placeholder="https://tuo-sistema.it/webhook"
          aria-label="URL del webhook"
        />
        <input
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          placeholder="Descrizione (facoltativa)"
          aria-label="Descrizione del webhook"
        />
        <fieldset style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
          <legend style={{ fontSize: 12, color: "var(--text-muted)" }}>
            Eventi (nessuna selezione = tutti)
          </legend>
          {events.map((event) => (
            <label key={event} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, padding: "2px 0" }}>
              <input type="checkbox" checked={form.events.includes(event)} onChange={() => toggleEvent(event)} />
              <code style={{ fontSize: 11.5 }}>{event}</code>
            </label>
          ))}
        </fieldset>
        <button className="wpai-btn" type="submit" disabled={!form.url.trim()} style={{ justifySelf: "start" }}>
          <Plus size={14} /> Aggiungi webhook
        </button>
      </form>
    </div>
  );
}

export default function Developers() {
  return (
    <div>
      <h1 className="wpai-page-title">API e webhook</h1>
      <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 16px", maxWidth: 640 }}>
        Collega WP AIssistant al tuo CRM o alle tue automazioni: l'API <code>/v1</code> legge e
        aggiorna le conversazioni, i webhook ti avvisano quando succede qualcosa.
      </p>
      <div className="wpai-two-col">
        <ApiKeys />
        <Webhooks />
      </div>
    </div>
  );
}

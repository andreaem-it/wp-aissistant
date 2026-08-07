import { useCallback, useEffect, useState } from "react";
import { UserPlus, Plus, Trash2, Download, ClipboardList, PlugZap, Send } from "lucide-react";
import { api, getToken } from "./api.js";
import { formatMoment } from "./activity.js";
import Loading from "./Loading.jsx";

const TRIGGER_LABELS = {
  escalation: "Quando la chat passa a un operatore",
  chat_start: "All'inizio della chat",
};

const TYPE_LABELS = { text: "Testo", email: "Email", tel: "Telefono", select: "Scelta" };

const EMPTY_FIELD = { label: "", type: "text", required: false, points: 10, options: "" };
const EMPTY_FORM = {
  name: "",
  trigger: "escalation",
  intro: "Lasciaci due informazioni e ti ricontattiamo.",
  consent_text: "Acconsento al trattamento dei dati per essere ricontattato.",
  fields: [{ ...EMPTY_FIELD, label: "Email", type: "email", required: true, points: 40 }],
};

const CRM_LABELS = { brevo: "Brevo", zoho: "Zoho CRM", pipedrive: "Pipedrive" };

function CrmManager({ connections, onChanged }) {
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState("");
  const brevo = connections.find((row) => row.provider === "brevo" && row.enabled);

  const save = async (e) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setSaving(true);
    try {
      await api.connectBrevo(apiKey.trim());
      setApiKey("");
      setFeedback("Brevo collegato e verificato.");
      onChanged();
    } catch {
      setFeedback("Collegamento non riuscito. Controlla la chiave API Brevo.");
    } finally { setSaving(false); }
  };

  const removeBrevo = async () => {
    if (!brevo || !window.confirm("Scollegare Brevo?")) return;
    await api.deleteCrmConnection("brevo");
    setFeedback("Brevo scollegato.");
    onChanged();
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><PlugZap size={15} /> Collegamenti CRM</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Collega il CRM senza salvare credenziali nel database di WP AIssistant. La chiave viene
        verificata e custodita nell’adapter Cloudflare.
      </p>
      <form onSubmit={save} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <strong style={{ fontSize: 13 }}>Brevo</strong>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={brevo ? "Nuova chiave API per aggiornare" : "Incolla la chiave API Brevo"}
          aria-label="Chiave API Brevo"
          autoComplete="off"
          style={{ minWidth: 240, flex: 1 }}
        />
        <button className="wpai-btn" type="submit" disabled={saving || !apiKey.trim()}>
          <PlugZap size={14} /> {saving ? "Verifica…" : brevo ? "Aggiorna chiave" : "Verifica e collega"}
        </button>
        {brevo && <button className="wpai-btn ghost" type="button" onClick={removeBrevo}>Scollega</button>}
      </form>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <span className={`wpai-badge ${brevo ? "ok" : ""}`}>Brevo · {brevo ? "collegato" : "da collegare"}</span>
        <span className="wpai-badge">Zoho CRM · OAuth in arrivo</span>
        <span className="wpai-badge">Pipedrive · in arrivo</span>
      </div>
      {feedback && <p role="status" style={{ fontSize: 12.5, margin: "10px 0 0", color: "var(--text-muted)" }}>{feedback}</p>}
    </div>
  );
}

function FormsManager({ onChanged }) {
  const [forms, setForms] = useState([]);
  const [catalog, setCatalog] = useState({ triggers: [], field_types: [] });
  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState("");

  const load = useCallback(
    () =>
      api
        .leadForms()
        .then((data) => {
          setForms(data.forms);
          setCatalog({ triggers: data.triggers, field_types: data.field_types });
          setError("");
        })
        .catch(() => setError("Impossibile caricare i form.")),
    [],
  );
  useEffect(() => { load(); }, [load]);

  const updateField = (index, patch) =>
    setForm((f) => ({ ...f, fields: f.fields.map((x, i) => (i === index ? { ...x, ...patch } : x)) }));
  const addField = () => setForm((f) => ({ ...f, fields: [...f.fields, { ...EMPTY_FIELD }] }));
  const removeField = (index) =>
    setForm((f) => ({ ...f, fields: f.fields.filter((_, i) => i !== index) }));

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    try {
      await api.createLeadForm({
        ...form,
        name: form.name.trim(),
        fields: form.fields.map((field) => ({
          label: field.label,
          type: field.type,
          required: field.required,
          points: Number(field.points) || 0,
          options: field.type === "select"
            ? String(field.options || "").split(",").map((o) => o.trim()).filter(Boolean)
            : [],
        })),
      });
      setForm(EMPTY_FORM);
      setError("");
      load();
      onChanged?.();
    } catch {
      setError("Creazione non riuscita: controlla etichette, tipi e opzioni.");
    }
  };
  const toggle = async (row) => { await api.updateLeadForm(row.id, { active: !row.active }); load(); };
  const remove = async (row) => {
    if (!window.confirm(`Eliminare il form "${row.name}"? I lead già raccolti restano.`)) return;
    await api.deleteLeadForm(row.id);
    load();
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><ClipboardList size={15} /> Form di qualificazione</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        I punti per campo determinano il punteggio del lead: è la somma dei punti dei campi
        compilati, niente di nascosto. Il consenso, se lo chiedi, è obbligatorio anche lato
        server.
      </p>
      {error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}

      <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
        {forms.map((row) => (
          <div key={row.id} className="wpai-canned-row">
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>
                {row.name} {!row.active && <span className="wpai-badge warn">disattivato</span>}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                {TRIGGER_LABELS[row.trigger] || row.trigger} ·{" "}
                {row.fields.map((f) => `${f.label}${f.required ? "*" : ""} (${f.points}p)`).join(", ")}
                {row.consent_text ? " · con consenso" : " · senza consenso"}
              </div>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <button className="wpai-btn ghost" onClick={() => toggle(row)}>
                {row.active ? "Disattiva" : "Attiva"}
              </button>
              <button className="wpai-icon-btn" title="Elimina" onClick={() => remove(row)}>
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        ))}
        {forms.length === 0 && <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessun form.</span>}
      </div>

      <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
        <input
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="Nome interno, es. Qualificazione vendite"
          aria-label="Nome del form"
        />
        <select
          aria-label="Quando mostrarlo"
          value={form.trigger}
          onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value }))}
        >
          {catalog.triggers.map((trigger) => (
            <option key={trigger} value={trigger}>{TRIGGER_LABELS[trigger] || trigger}</option>
          ))}
        </select>
        <input
          value={form.intro}
          onChange={(e) => setForm((f) => ({ ...f, intro: e.target.value }))}
          placeholder="Testo introduttivo"
          aria-label="Introduzione"
        />
        <input
          value={form.consent_text}
          onChange={(e) => setForm((f) => ({ ...f, consent_text: e.target.value }))}
          placeholder="Testo del consenso (vuoto = nessun consenso richiesto)"
          aria-label="Testo del consenso"
        />

        <fieldset style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
          <legend style={{ fontSize: 12, color: "var(--text-muted)" }}>Campi</legend>
          {form.fields.map((field, index) => (
            <div key={index} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
              <input
                aria-label="Etichetta del campo"
                value={field.label}
                onChange={(e) => updateField(index, { label: e.target.value })}
                placeholder="Etichetta"
                style={{ flex: 1, minWidth: 120 }}
              />
              <select aria-label="Tipo" value={field.type} onChange={(e) => updateField(index, { type: e.target.value })}>
                {catalog.field_types.map((type) => (
                  <option key={type} value={type}>{TYPE_LABELS[type] || type}</option>
                ))}
              </select>
              {field.type === "select" && (
                <input
                  aria-label="Opzioni separate da virgola"
                  value={field.options}
                  onChange={(e) => updateField(index, { options: e.target.value })}
                  placeholder="opzioni, separate, da virgole"
                  style={{ minWidth: 160 }}
                />
              )}
              <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4 }}>
                <input
                  type="checkbox"
                  checked={field.required}
                  onChange={(e) => updateField(index, { required: e.target.checked })}
                />
                obbligatorio
              </label>
              <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4 }}>
                punti
                <input
                  type="number"
                  min="0"
                  max="50"
                  value={field.points}
                  onChange={(e) => updateField(index, { points: e.target.value })}
                  style={{ width: 70 }}
                  aria-label="Punti del campo"
                />
              </label>
              {form.fields.length > 1 && (
                <button className="wpai-icon-btn" type="button" aria-label="Rimuovi campo" onClick={() => removeField(index)}>
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
          <button className="wpai-btn ghost" type="button" onClick={addField}>
            <Plus size={13} /> Campo
          </button>
        </fieldset>

        <button className="wpai-btn" type="submit" disabled={!form.name.trim()} style={{ justifySelf: "start" }}>
          <Plus size={14} /> Crea form
        </button>
      </form>
    </div>
  );
}

function LeadsList({ reloadKey, connections }) {
  const [leads, setLeads] = useState([]);
  const [filters, setFilters] = useState({ min_score: "", days: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState("");

  const load = useCallback(() => {
    const params = {};
    if (filters.min_score) params.min_score = filters.min_score;
    if (filters.days) params.days = filters.days;
    return api
      .leads(params)
      .then((rows) => { setLeads(rows); setError(""); })
      .catch(() => setError("Impossibile caricare i lead."))
      .finally(() => setLoading(false));
  }, [filters]);
  useEffect(() => { load(); }, [load, reloadKey]);

  const exportCsv = async () => {
    // il download passa dall'endpoint autenticato: costruiamo il blob a mano invece di un <a>
    const params = new URLSearchParams();
    if (filters.min_score) params.set("min_score", filters.min_score);
    if (filters.days) params.set("days", filters.days);
    const base = import.meta.env.VITE_API_BASE || "http://localhost:8000";
    try {
      const res = await fetch(`${base}/leads/export?${params}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (!res.ok) throw new Error("export non riuscito");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "lead.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Esportazione non riuscita.");
    }
  };

  const columns = [...new Set(leads.flatMap((lead) => Object.keys(lead.data)))];
  const activeConnections = connections.filter((row) => row.enabled);

  const syncLead = async (leadId, provider) => {
    const key = `${leadId}:${provider}`;
    setSyncing(key);
    try {
      const result = await api.syncLeadToCrm(leadId, provider);
      if (!result.ok) setError(result.error || "Invio al CRM non riuscito.");
      else setError("");
      await load();
    } catch {
      setError("Invio al CRM non riuscito.");
    } finally { setSyncing(""); }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><UserPlus size={15} /> Lead raccolti</div>
      <div className="wpai-filters" style={{ margin: "10px 0" }}>
        <select
          aria-label="Punteggio minimo"
          value={filters.min_score}
          onChange={(e) => setFilters((f) => ({ ...f, min_score: e.target.value }))}
        >
          <option value="">Tutti i punteggi</option>
          <option value="80">Da 80 in su</option>
          <option value="50">Da 50 in su</option>
          <option value="20">Da 20 in su</option>
        </select>
        <select
          aria-label="Periodo"
          value={filters.days}
          onChange={(e) => setFilters((f) => ({ ...f, days: e.target.value }))}
        >
          <option value="">Sempre</option>
          <option value="7">Ultimi 7 giorni</option>
          <option value="30">Ultimi 30 giorni</option>
        </select>
        <button className="wpai-btn ghost" onClick={exportCsv} disabled={leads.length === 0}>
          <Download size={14} /> Esporta CSV
        </button>
      </div>

      {loading && <Loading inline />}
      {error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}
      {!loading && leads.length === 0 && !error && (
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          Nessun lead con questi filtri. Il form viene mostrato nel widget secondo il trigger scelto.
        </p>
      )}

      {leads.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table className="wpai-table">
            <thead>
              <tr>
                <th>Punteggio</th>
                {columns.map((column) => <th key={column}>{column}</th>)}
                <th>Consenso</th>
                <th>Data</th>
                <th>CRM</th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <tr key={lead.id}>
                  <td style={{ fontWeight: 700 }}>{lead.score}</td>
                  {columns.map((column) => <td key={column}>{lead.data[column] || "—"}</td>)}
                  <td title={lead.consent_text}>{lead.consent ? "sì" : "no"}</td>
                  <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>
                    {formatMoment(lead.created_at)}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {activeConnections.length === 0 ? (
                      <span style={{ color: "var(--text-muted)" }}>Non collegato</span>
                    ) : activeConnections.map((connection) => {
                      const status = lead.crm_syncs?.[connection.provider]?.status;
                      return (
                        <button
                          key={connection.provider}
                          className="wpai-btn ghost"
                          style={{ marginRight: 6 }}
                          onClick={() => syncLead(lead.id, connection.provider)}
                          disabled={syncing === `${lead.id}:${connection.provider}`}
                          title={lead.crm_syncs?.[connection.provider]?.error || "Invia il lead al CRM"}
                        >
                          <Send size={13} /> {syncing === `${lead.id}:${connection.provider}`
                            ? "Invio…"
                            : status === "delivered" ? `${CRM_LABELS[connection.provider]} ✓`
                              : status === "failed" ? `${CRM_LABELS[connection.provider]} · Riprova`
                                : CRM_LABELS[connection.provider]}
                        </button>
                      );
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Leads() {
  const [reloadKey, setReloadKey] = useState(0);
  const [connections, setConnections] = useState([]);
  const loadConnections = useCallback(() => api.crmConnections().then((data) => setConnections(data.connections)).catch(() => setConnections([])), []);
  useEffect(() => { loadConnections(); }, [loadConnections]);
  return (
    <div>
      <h1 className="wpai-page-title">Lead</h1>
      <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 16px", maxWidth: 660 }}>
        Trasforma le conversazioni in contatti qualificati: un form breve nel widget, un
        punteggio trasparente e l'export per il CRM. Ogni lead conserva il testo del consenso
        che il visitatore ha effettivamente accettato.
      </p>
      <div style={{ display: "grid", gap: 16 }}>
        <CrmManager connections={connections} onChanged={loadConnections} />
        <LeadsList reloadKey={reloadKey} connections={connections} />
        <FormsManager onChanged={() => setReloadKey((k) => k + 1)} />
      </div>
    </div>
  );
}

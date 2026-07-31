import { useCallback, useEffect, useState } from "react";
import { UserPlus, Plus, Trash2, Download, ClipboardList } from "lucide-react";
import { api, getToken } from "./api.js";
import { formatMoment } from "./activity.js";

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

function LeadsList({ reloadKey }) {
  const [leads, setLeads] = useState([]);
  const [filters, setFilters] = useState({ min_score: "", days: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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

      {loading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>}
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
  return (
    <div>
      <h1 className="wpai-page-title">Lead</h1>
      <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 16px", maxWidth: 660 }}>
        Trasforma le conversazioni in contatti qualificati: un form breve nel widget, un
        punteggio trasparente e l'export per il CRM. Ogni lead conserva il testo del consenso
        che il visitatore ha effettivamente accettato.
      </p>
      <div style={{ display: "grid", gap: 16 }}>
        <LeadsList reloadKey={reloadKey} />
        <FormsManager onChanged={() => setReloadKey((k) => k + 1)} />
      </div>
    </div>
  );
}

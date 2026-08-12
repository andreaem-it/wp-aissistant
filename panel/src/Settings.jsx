import { useCallback, useEffect, useState } from "react";
import {
  Download, Plus, Trash2, MessageSquareText, ListChecks, ShieldX, Timer, Shuffle, Tag as TagIcon, Clock3,
  MessagesSquare, Users, Headphones, ShieldCheck, Globe, Code2,
} from "lucide-react";
import { api } from "./api.js";
import Loading from "./Loading.jsx";
import { PageHeader, SectionTabs, TabPanel } from "./PageLayout.jsx";
import Sites from "./Sites.jsx";
import Install from "./Install.jsx";

const SETTINGS_TABS = [
  // Primo, e non in fondo fra le voci avanzate: senza un dominio registrato il widget non parte
  // su nessun sito, quindi è il punto di partenza dell'installazione.
  { key: "sites", label: "Siti e licenza", description: "Dove funziona il widget", Icon: Globe },
  { key: "install", label: "Installazione", description: "Plugin o JavaScript", Icon: Code2 },
  { key: "content", label: "Conversazioni", description: "Campi, risposte e tag", Icon: MessagesSquare },
  { key: "team", label: "Team e reparti", description: "Code e assegnazioni", Icon: Users },
  { key: "service", label: "Orari e SLA", description: "Tempi del supporto", Icon: Headphones },
  { key: "privacy", label: "Privacy", description: "Richieste sui dati", Icon: ShieldCheck },
];

function GdprCard() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState("");

  const exportData = async () => {
    if (!email.trim()) return;
    setBusy("export");
    setResult(null);
    try {
      const data = await api.gdprExport(email.trim());
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `wp-aissistant-export-${email.trim().replace(/[^a-z0-9]+/gi, "-")}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setResult(`Esportate ${data.conversations.length} conversazioni per ${email}.`);
    } catch {
      setResult("Errore durante l'esportazione.");
    } finally {
      setBusy("");
    }
  };

  const erase = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    if (!window.confirm(`Eliminare definitivamente TUTTE le conversazioni lasciate da ${email}? Non è reversibile.`)) return;
    setBusy("erase");
    setResult(null);
    try {
      const r = await api.gdprErase(email.trim());
      setResult(`Eliminate ${r.deleted} conversazioni per ${email}.`);
      setEmail("");
    } catch {
      setResult("Errore durante la cancellazione.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><ShieldX size={15} /> Gestione dati (GDPR)</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Esporta i dati portabili o applica il diritto all'oblio alle conversazioni collegate
        all'email lasciata dal visitatore. La cancellazione è irreversibile e viene registrata.
      </p>
      <form onSubmit={erase} style={{ display: "flex", gap: 8 }}>
        <input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setResult(null); }} placeholder="email@visitatore.it" style={{ flex: 1 }} />
        <button className="wpai-btn" type="button" onClick={exportData} disabled={Boolean(busy)}>
          <Download size={14} /> {busy === "export" ? "Esportazione…" : "Esporta"}
        </button>
        <button className="wpai-btn danger" type="submit" disabled={Boolean(busy)}>{busy === "erase" ? "Cancellazione…" : "Elimina"}</button>
      </form>
      {result && <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0 0" }}>{result}</p>}
    </div>
  );
}

function InfoFieldsManager() {
  const [fields, setFields] = useState([]);
  const [label, setLabel] = useState("");

  const load = () => api.infoFields().then(setFields).catch(() => {});
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!label.trim()) return;
    await api.createInfoField(label.trim());
    setLabel("");
    load();
  };
  const remove = async (id) => { await api.deleteInfoField(id); load(); };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><ListChecks size={15} /> Campi info</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Campi che l'operatore compila su ogni conversazione. La <code>chiave</code> si usa nei
        placeholder delle risposte predefinite, es. <code>{"{nome_cliente}"}</code>.
      </p>
      <table className="wpai-table" style={{ marginBottom: 12 }}>
        <tbody>
          {fields.map((f) => (
            <tr key={f.id}>
              <td>{f.label}</td>
              <td><code>{f.key}</code></td>
              <td style={{ textAlign: "right" }}>
                <button className="wpai-icon-btn" title="Rimuovi" onClick={() => remove(f.id)}><Trash2 size={14} /></button>
              </td>
            </tr>
          ))}
          {fields.length === 0 && <tr><td style={{ color: "var(--text-muted)" }}>Nessun campo.</td></tr>}
        </tbody>
      </table>
      <form onSubmit={add} style={{ display: "flex", gap: 8 }}>
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Es. Nome cliente" style={{ flex: 1 }} />
        <button className="wpai-btn" type="submit"><Plus size={14} /> Aggiungi</button>
      </form>
    </div>
  );
}

function DepartmentMembers({ departmentId, operators }) {
  const [members, setMembers] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    () => api.departmentMembers(departmentId).then(setMembers).catch(() => setMembers([])),
    [departmentId],
  );
  useEffect(() => { load(); }, [load]);

  const add = async (operatorId) => {
    if (!operatorId) return;
    setBusy(true);
    try {
      await api.addDepartmentMember(departmentId, Number(operatorId));
      await load();
    } finally {
      setBusy(false);
    }
  };
  const remove = async (operatorId) => {
    setBusy(true);
    try {
      await api.removeDepartmentMember(departmentId, operatorId);
      await load();
    } finally {
      setBusy(false);
    }
  };

  const available = operators.filter((op) => !members.some((m) => m.id === op.id));
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
        {members.map((m) => (
          <span key={m.id} className="wpai-chip">
            {m.name}
            <button
              className="wpai-chip-x"
              aria-label={`Rimuovi ${m.name} dal reparto`}
              disabled={busy}
              onClick={() => remove(m.id)}
            >
              ×
            </button>
          </span>
        ))}
        {members.length === 0 && (
          <span style={{ color: "var(--text-muted)", fontSize: 12.5 }}>
            Nessun operatore: le conversazioni restano nella coda del reparto.
          </span>
        )}
      </div>
      {available.length > 0 && (
        <select
          aria-label="Aggiungi operatore al reparto"
          value=""
          disabled={busy}
          onChange={(e) => add(e.target.value)}
        >
          <option value="">Aggiungi operatore…</option>
          {available.map((op) => <option key={op.id} value={op.id}>{op.name}</option>)}
        </select>
      )}
    </div>
  );
}

function DepartmentsManager({ departments, operators, reload }) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await api.createDepartment(name.trim());
      setName("");
      setError("");
      reload();
    } catch (err) {
      setError(err.status === 409 ? "Esiste già un reparto con questo nome." : "Impossibile creare il reparto.");
    }
  };
  const remove = async (id) => {
    if (!window.confirm("Eliminare il reparto? Le conversazioni tornano nella coda generale e le regole SLA collegate vengono rimosse.")) return;
    await api.deleteDepartment(id);
    reload();
  };
  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><ListChecks size={15} /> Reparti</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Organizza l'inbox in code come Vendite, Ordini o Resi. Gli operatori assegnati a un
        reparto formano il turno usato dall'instradamento automatico.
      </p>
      <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
        {departments.map((item) => (
          <div key={item.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
            <div className="wpai-canned-row">
              <span style={{ fontSize: 13, fontWeight: 600 }}>{item.name}</span>
              <button className="wpai-icon-btn" title="Rimuovi" onClick={() => remove(item.id)}><Trash2 size={14} /></button>
            </div>
            <DepartmentMembers departmentId={item.id} operators={operators} />
          </div>
        ))}
        {departments.length === 0 && <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessun reparto.</span>}
      </div>
      <form onSubmit={add} style={{ display: "flex", gap: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Es. Resi" style={{ flex: 1 }} />
        <button className="wpai-btn" type="submit"><Plus size={14} /> Aggiungi</button>
      </form>
      {error && <p style={{ fontSize: 12.5, color: "var(--red)", margin: "8px 0 0" }}>{error}</p>}
    </div>
  );
}

const PRIORITY_LABELS = { "": "Tutte le priorità", urgent: "Urgente", high: "Alta", normal: "Normale", low: "Bassa" };
const DAY_LABELS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"];

function SupportScheduleManager() {
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Rome";
  const [form, setForm] = useState(null);
  const [closure, setClosure] = useState("");
  const [state, setState] = useState({ saving: false, message: "" });

  useEffect(() => {
    api.supportSchedule().then((data) => setForm({ ...data, timezone: data.timezone || browserTimezone }))
      .catch(() => setState({ saving: false, message: "Impossibile caricare gli orari." }));
  }, [browserTimezone]);

  const toggleDay = (day) => setForm((value) => ({
    ...value,
    weekdays: value.weekdays.includes(day) ? value.weekdays.filter((item) => item !== day) : [...value.weekdays, day].sort(),
  }));
  const save = async (event) => {
    event.preventDefault();
    setState({ saving: true, message: "" });
    try {
      const saved = await api.setSupportSchedule(form);
      setForm(saved);
      setState({ saving: false, message: "Orari salvati. Le scadenze SLA aperte sono state ricalcolate." });
    } catch {
      setState({ saving: false, message: "Controlla giorni, orari e fuso orario." });
    }
  };
  const addClosure = () => {
    if (!closure || form.closed_dates.includes(closure)) return;
    setForm((value) => ({ ...value, closed_dates: [...value.closed_dates, closure].sort() }));
    setClosure("");
  };
  const removeClosure = (date) => setForm((value) => ({
    ...value, closed_dates: value.closed_dates.filter((item) => item !== date),
  }));
  if (!form) return <div className="wpai-card"><div className="wpai-card-title"><Clock3 size={15} /> Orari di supporto</div><Loading inline /></div>;
  return <form className="wpai-card" onSubmit={save}>
    <div className="wpai-card-title"><Clock3 size={15} /> Orari di supporto</div>
    <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
      Quando sono attivi, il tempo fuori orario non consuma lo SLA. Il fuso sarà sincronizzato
      automaticamente dal plugin WordPress; qui puoi già verificarlo o correggerlo.
    </p>
    <label className="wpai-switch-row" style={{ marginBottom: 12 }}>
      <span><b>Conta solo le ore lavorative</b><small>Valido per prima risposta e risoluzione</small></span>
      <input type="checkbox" checked={form.enabled} onChange={(event) => setForm((value) => ({ ...value, enabled: event.target.checked }))} />
    </label>
    <div className="wpai-day-picker">
      {DAY_LABELS.map((label, index) => <button type="button" key={label} className={form.weekdays.includes(index + 1) ? "active" : ""} onClick={() => toggleDay(index + 1)}>{label}</button>)}
    </div>
    <div className="wpai-schedule-fields">
      <label>Da<input type="time" value={form.start_time} onChange={(event) => setForm((value) => ({ ...value, start_time: event.target.value }))} /></label>
      <label>A<input type="time" value={form.end_time} onChange={(event) => setForm((value) => ({ ...value, end_time: event.target.value }))} /></label>
      <label>Fuso orario<input value={form.timezone} onChange={(event) => setForm((value) => ({ ...value, timezone: event.target.value }))} placeholder="Europe/Rome" /></label>
    </div>
    <div className="wpai-closures">
      <div>
        <b>Festività e chiusure</b>
        <small>In queste date lo SLA resta completamente in pausa.</small>
      </div>
      <div className="wpai-closure-add">
        <input aria-label="Data di chiusura" type="date" value={closure} onChange={(event) => setClosure(event.target.value)} />
        <button className="wpai-btn wpai-btn-secondary" type="button" disabled={!closure} onClick={addClosure}>Aggiungi</button>
      </div>
      <label className="wpai-holiday-toggle">
        <input type="checkbox" checked={form.include_italian_holidays} onChange={(event) => setForm((value) => ({ ...value, include_italian_holidays: event.target.checked }))} />
        <span><b>Festività nazionali italiane</b><small>Capodanno, Epifania, Pasqua e Pasquetta, 25 aprile, 1 maggio, 2 giugno, Ferragosto, Ognissanti, Immacolata, Natale e Santo Stefano.</small></span>
      </label>
      {form.closed_dates.length > 0 && <div className="wpai-closure-list">
        {form.closed_dates.map((date) => <span key={date}>{new Intl.DateTimeFormat("it-IT", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${date}T00:00:00Z`))}<button type="button" aria-label={`Rimuovi chiusura ${date}`} onClick={() => removeClosure(date)}>×</button></span>)}
      </div>}
    </div>
    <button className="wpai-btn" type="submit" disabled={state.saving || form.weekdays.length === 0}>{state.saving ? "Salvataggio…" : "Salva orari"}</button>
    {state.message && <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "9px 0 0" }}>{state.message}</p>}
  </form>;
}

function SlaManager({ departments }) {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ name: "", first: "60", resolution: "480", priority: "", department_id: "" });
  const [state, setState] = useState({ loading: true, error: "" });

  const load = () =>
    api.slaPolicies()
      .then((rows) => { setItems(rows); setState({ loading: false, error: "" }); })
      .catch(() => setState({ loading: false, error: "Impossibile caricare le regole SLA." }));
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    await api.createSlaPolicy({
      name: form.name.trim(),
      first_response_minutes: Number(form.first) || 0,
      resolution_minutes: Number(form.resolution) || 0,
      priority: form.priority,
      department_id: form.department_id ? Number(form.department_id) : null,
    });
    setForm({ name: "", first: "60", resolution: "480", priority: "", department_id: "" });
    load();
  };
  const toggle = async (policy) => { await api.updateSlaPolicy(policy.id, { active: !policy.active }); load(); };
  const remove = async (id) => { await api.deleteSlaPolicy(id); load(); };

  const departmentName = (id) => departments.find((d) => d.id === id)?.name || "Tutti i reparti";

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><Timer size={15} /> Regole SLA</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Le scadenze partono quando la conversazione passa a un operatore. Vince la regola più
        specifica (reparto + priorità). <code>0</code> minuti disattiva quella scadenza.
      </p>
      {state.loading && <Loading inline />}
      {state.error && <p style={{ fontSize: 12.5, color: "var(--red)" }}>{state.error}</p>}
      {!state.loading && !state.error && (
        <table className="wpai-table" style={{ marginBottom: 12 }}>
          <tbody>
            {items.map((policy) => (
              <tr key={policy.id}>
                <td>
                  <div style={{ fontWeight: 600 }}>{policy.name}</div>
                  <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
                    {departmentName(policy.department_id)} · {PRIORITY_LABELS[policy.priority] || policy.priority}
                  </div>
                </td>
                <td style={{ fontSize: 12.5 }}>
                  1ª risposta {policy.first_response_minutes || "—"} min<br />
                  Risoluzione {policy.resolution_minutes || "—"} min
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <button className="wpai-btn ghost" onClick={() => toggle(policy)}>
                    {policy.active ? "Disattiva" : "Attiva"}
                  </button>
                  <button className="wpai-icon-btn" title="Rimuovi" onClick={() => remove(policy.id)}><Trash2 size={14} /></button>
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td style={{ color: "var(--text-muted)" }}>Nessuna regola SLA.</td></tr>}
          </tbody>
        </table>
      )}
      <form onSubmit={add} style={{ display: "grid", gap: 8 }}>
        <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Nome regola, es. Urgenti" />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12.5, display: "grid", gap: 4 }}>
            Prima risposta (min)
            <input type="number" min="0" value={form.first} onChange={(e) => setForm((f) => ({ ...f, first: e.target.value }))} style={{ width: 120 }} />
          </label>
          <label style={{ fontSize: 12.5, display: "grid", gap: 4 }}>
            Risoluzione (min)
            <input type="number" min="0" value={form.resolution} onChange={(e) => setForm((f) => ({ ...f, resolution: e.target.value }))} style={{ width: 120 }} />
          </label>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select aria-label="Reparto della regola" value={form.department_id} onChange={(e) => setForm((f) => ({ ...f, department_id: e.target.value }))}>
            <option value="">Tutti i reparti</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <select aria-label="Priorità della regola" value={form.priority} onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}>
            {Object.entries(PRIORITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
        <button className="wpai-btn" type="submit" style={{ justifySelf: "flex-start" }}><Plus size={14} /> Aggiungi regola</button>
      </form>
    </div>
  );
}

function RoutingManager({ departments }) {
  const [setting, setSetting] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.routingSettings().then(setSetting).catch(() => setError("Impossibile caricare l'instradamento."));
  }, []);

  const save = async (next) => {
    setSaving(true);
    setError("");
    try {
      const saved = await api.setRoutingSettings(next.mode, next.fallback_department_id);
      setSetting(saved);
    } catch {
      setError("Salvataggio non riuscito. Riprova.");
    } finally {
      setSaving(false);
    }
  };

  if (!setting) {
    return (
      <div className="wpai-card">
        <div className="wpai-card-title"><Shuffle size={15} /> Instradamento automatico</div>
        {error ? <p style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p> : <Loading inline />}
      </div>
    );
  }

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><Shuffle size={15} /> Instradamento automatico</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        All'escalation la conversazione può essere assegnata a turno agli operatori del reparto.
        Se il reparto non ha operatori, resta nella coda non assegnata.
      </p>
      <div className="wpai-field" style={{ marginBottom: 8 }}>
        <label htmlFor="routing-mode">Modalità</label>
        <select
          id="routing-mode"
          value={setting.mode}
          disabled={saving}
          onChange={(e) => save({ ...setting, mode: e.target.value })}
        >
          <option value="off">Manuale (nessuna assegnazione)</option>
          <option value="round_robin">A turno tra gli operatori</option>
        </select>
      </div>
      <div className="wpai-field" style={{ marginBottom: 0 }}>
        <label htmlFor="routing-fallback">Reparto predefinito</label>
        <select
          id="routing-fallback"
          value={setting.fallback_department_id || ""}
          disabled={saving}
          onChange={(e) => save({ ...setting, fallback_department_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">Nessuno</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      {error && <p style={{ fontSize: 12.5, color: "var(--red)", margin: "10px 0 0" }}>{error}</p>}
    </div>
  );
}

function CannedManager() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ title: "", body: "" });

  const load = () => api.cannedResponses().then(setItems).catch(() => {});
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!form.title.trim() || !form.body.trim()) return;
    await api.createCanned(form.title.trim(), form.body.trim());
    setForm({ title: "", body: "" });
    load();
  };
  const remove = async (id) => { await api.deleteCanned(id); load(); };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><MessageSquareText size={15} /> Risposte predefinite</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Il testo può contenere placeholder <code>{"{chiave}"}</code> che vengono sostituiti con i
        valori dei campi info compilati.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
        {items.map((c) => (
          <div key={c.id} className="wpai-canned-row">
            <div>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{c.title}</div>
              <div style={{ fontSize: 12.5, color: "var(--text-muted)", whiteSpace: "pre-wrap" }}>{c.body}</div>
            </div>
            <button className="wpai-icon-btn" title="Rimuovi" onClick={() => remove(c.id)}><Trash2 size={14} /></button>
          </div>
        ))}
        {items.length === 0 && <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessuna risposta predefinita.</p>}
      </div>
      <form onSubmit={add} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <input value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} placeholder="Titolo (etichetta del bottone)" />
        <textarea rows={3} value={form.body} onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))} placeholder="Testo della risposta, es. Ciao {nome_cliente}, riguardo l'ordine {id_ordine}…" />
        <button className="wpai-btn" type="submit" style={{ alignSelf: "flex-start" }}><Plus size={14} /> Aggiungi</button>
      </form>
    </div>
  );
}

function TagsManager() {
  const [items, setItems] = useState([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const load = () => api.tags().then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await api.createTag(name.trim());
      setName("");
      setError("");
      load();
    } catch (err) {
      setError(err.status === 409 ? "Esiste già un tag con questo nome." : "Impossibile creare il tag.");
    }
  };
  const remove = async (id) => {
    if (!window.confirm("Eliminare il tag? Verrà rimosso da tutte le conversazioni.")) return;
    await api.deleteTag(id);
    load();
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><TagIcon size={15} /> Tag</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Etichette per classificare le conversazioni. Quelle marcate <b>AI</b> sono state create
        dalla classificazione automatica: puoi rimuoverle come le altre.
      </p>
      <div className="wpai-tag-row" style={{ marginBottom: 12 }}>
        {items.map((tag) => (
          <span key={tag.id} className={"wpai-tag" + (tag.source === "ai" ? " ai" : "")}>
            {tag.name}
            <button className="wpai-chip-x" aria-label={`Elimina il tag ${tag.name}`} onClick={() => remove(tag.id)}>×</button>
          </span>
        ))}
        {items.length === 0 && <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessun tag.</span>}
      </div>
      <form onSubmit={add} style={{ display: "flex", gap: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Es. VIP" style={{ flex: 1 }} />
        <button className="wpai-btn" type="submit"><Plus size={14} /> Aggiungi</button>
      </form>
      {error && <p style={{ fontSize: 12.5, color: "var(--red)", margin: "8px 0 0" }}>{error}</p>}
    </div>
  );
}

export default function Settings() {
  const [departments, setDepartments] = useState([]);
  const [operators, setOperators] = useState([]);
  // La prima scheda è anche quella predefinita: è dove si finisce quando il widget non compare.
  const [section, setSection] = useState("sites");

  const loadDepartments = useCallback(
    () => api.departments().then(setDepartments).catch(() => setDepartments([])),
    [],
  );
  useEffect(() => {
    loadDepartments();
    api.teamOperators().then(setOperators).catch(() => setOperators([]));
  }, [loadDepartments]);

  return (
    <div>
      <PageHeader
        eyebrow="Gestione"
        title="Impostazioni"
        description="Personalizza il lavoro del team e il modo in cui vengono gestite le richieste dei clienti. Le impostazioni sono raggruppate per obiettivo."
      />
      <SectionTabs items={SETTINGS_TABS} active={section} onChange={setSection} label="Aree delle impostazioni" />

      <TabPanel active={section} name="sites" className="wpai-single-col">
        <div className="wpai-section-intro">
          <h2>Dove funziona il widget</h2>
          <p>
            La licenza copre un sito di produzione e uno di staging. Su un dominio non registrato
            il widget non parte: se hai appena cambiato indirizzo, aggiornalo qui.
          </p>
        </div>
        <Sites />
      </TabPanel>

      <TabPanel active={section} name="install" className="wpai-single-col">
        <div className="wpai-section-intro">
          <h2>Metti l'assistente sul tuo sito</h2>
          <p>
            Due strade, stesso assistente: il plugin WordPress o due righe di JavaScript. La
            seconda si configura da qui e ti dà lo snippet già personalizzato.
          </p>
        </div>
        <Install />
      </TabPanel>

      <TabPanel active={section} name="content" className="wpai-two-col">
        <div className="wpai-section-intro">
          <h2>Strumenti per rispondere meglio</h2>
          <p>Prepara le informazioni che gli operatori usano ogni giorno e organizza le conversazioni in modo coerente.</p>
        </div>
        <InfoFieldsManager />
        <CannedManager />
        <TagsManager />
      </TabPanel>

      <TabPanel active={section} name="team" className="wpai-two-col">
        <div className="wpai-section-intro">
          <h2>Organizza il lavoro del team</h2>
          <p>Crea reparti come Vendite o Resi e scegli come distribuire automaticamente le nuove richieste.</p>
        </div>
        <DepartmentsManager departments={departments} operators={operators} reload={loadDepartments} />
        <RoutingManager departments={departments} />
      </TabPanel>

      <TabPanel active={section} name="service" className="wpai-two-col">
        <div className="wpai-section-intro">
          <h2>Definisci i tempi del supporto</h2>
          <p>Imposta quando il team è disponibile e gli obiettivi di risposta. Fuori orario le scadenze vengono messe in pausa.</p>
        </div>
        <SupportScheduleManager />
        <SlaManager departments={departments} />
      </TabPanel>

      <TabPanel active={section} name="privacy" className="wpai-single-col">
        <div className="wpai-section-intro">
          <h2>Gestisci le richieste privacy</h2>
          <p>Esporta o elimina i dati collegati a un visitatore. Le operazioni vengono registrate per mantenere una traccia verificabile.</p>
        </div>
        <GdprCard />
      </TabPanel>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { Workflow as WorkflowIcon, Plus, Trash2, Play, History } from "lucide-react";
import { api } from "./api.js";
import { formatMoment } from "./activity.js";
import Proactive from "./Proactive.jsx";

// Etichette italiane del vocabolario chiuso esposto dal backend in /workflows.catalog.
const TRIGGER_LABELS = {
  "conversation.created": "Quando inizia una conversazione",
  "conversation.escalated": "Quando passa a un operatore",
  "conversation.replied": "Quando un operatore risponde",
  "conversation.closed": "Quando viene chiusa",
  "conversation.rated": "Quando arriva una valutazione",
  "conversation.classified": "Quando l'AI la classifica",
  "sla.breached": "Quando uno SLA viene violato",
};

const FIELD_LABELS = {
  status: "Stato",
  priority: "Priorità",
  department_id: "Reparto",
  assigned: "Ha un assegnatario",
  intent: "Intento rilevato",
  urgency: "Urgenza rilevata",
  tag: "Tag",
  rating_score: "Voto CSAT",
  sla_target: "Scadenza SLA",
  visitor_email: "Email del visitatore",
};

const OP_LABELS = {
  eq: "è",
  neq: "non è",
  in: "è uno tra",
  contains: "contiene",
  gt: "maggiore di",
  lt: "minore di",
  is_set: "è presente",
  is_empty: "è assente",
};

const ACTION_LABELS = {
  set_priority: "Imposta priorità",
  set_department: "Assegna al reparto",
  assign_operator: "Assegna all'operatore",
  assign_round_robin: "Assegna a turno",
  add_tag: "Aggiungi tag",
  close_conversation: "Chiudi la conversazione",
  escalate: "Passa a un operatore",
  send_email: "Invia email",
  send_webhook: "Invia al webhook",
};

const VALUELESS_OPS = ["is_set", "is_empty"];

function describeCondition(condition) {
  const field = FIELD_LABELS[condition.field] || condition.field;
  const op = OP_LABELS[condition.op] || condition.op;
  if (VALUELESS_OPS.includes(condition.op)) return `${field} ${op}`;
  const value = Array.isArray(condition.value) ? condition.value.join(", ") : condition.value;
  return `${field} ${op} «${value}»`;
}

function describeAction(action, { departments, operators, endpoints }) {
  const label = ACTION_LABELS[action.type] || action.type;
  if (action.type === "set_priority") return `${label}: ${action.value}`;
  if (action.type === "set_department") {
    return `${label}: ${departments.find((d) => d.id === action.department_id)?.name || action.department_id}`;
  }
  if (action.type === "assign_operator") {
    return `${label}: ${operators.find((o) => o.id === action.operator_id)?.name || action.operator_id}`;
  }
  if (action.type === "add_tag") return `${label}: ${action.name}`;
  if (action.type === "send_email") return `${label} a ${action.to}`;
  if (action.type === "send_webhook") {
    return `${label}: ${endpoints.find((e) => e.id === action.endpoint_id)?.url || action.endpoint_id}`;
  }
  return label;
}

function Runs({ workflowId }) {
  const [rows, setRows] = useState([]);
  const [open, setOpen] = useState(false);
  const load = useCallback(
    () => api.workflowRuns(workflowId).then(setRows).catch(() => setRows([])),
    [workflowId],
  );
  useEffect(() => { if (open) load(); }, [open, load]);

  return (
    <div style={{ marginTop: 8 }}>
      <button className="wpai-btn ghost" onClick={() => setOpen((v) => !v)}>
        <History size={13} /> {open ? "Nascondi esecuzioni" : "Esecuzioni"}
      </button>
      {open && (
        <table className="wpai-table" style={{ marginTop: 8 }}>
          <tbody>
            {rows.map((run) => (
              <tr key={run.id}>
                <td style={{ fontSize: 12 }}>
                  #{run.conversation_id ?? "—"}
                  <br />
                  <span style={{ color: "var(--text-muted)", fontSize: 11 }}>{formatMoment(run.created_at)}</span>
                </td>
                <td>
                  <span className={`wpai-badge ${run.error ? "breach" : run.matched ? "ok" : "warn"}`}>
                    {run.error ? "Errore" : run.matched ? "Applicata" : "Condizioni non soddisfatte"}
                  </span>
                </td>
                <td style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                  {run.error || run.applied.join(" · ") || "—"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td style={{ color: "var(--text-muted)" }}>Nessuna esecuzione.</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}

const EMPTY_RULE = {
  name: "",
  trigger: "conversation.escalated",
  conditions: [],
  actions: [{ type: "set_priority", value: "urgent" }],
};

export default function Automations() {
  const [catalog, setCatalog] = useState(null);
  const [rules, setRules] = useState([]);
  const [form, setForm] = useState(EMPTY_RULE);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [departments, setDepartments] = useState([]);
  const [operators, setOperators] = useState([]);
  const [endpoints, setEndpoints] = useState([]);

  const load = useCallback(
    () =>
      api
        .workflows()
        .then((data) => { setCatalog(data.catalog); setRules(data.workflows); setError(""); })
        .catch(() => setError("Impossibile caricare le automazioni."))
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    load();
    api.departments().then(setDepartments).catch(() => setDepartments([]));
    api.teamOperators().then(setOperators).catch(() => setOperators([]));
    api.webhooks().then((d) => setEndpoints(d.endpoints)).catch(() => setEndpoints([]));
  }, [load]);

  const addCondition = () =>
    setForm((f) => ({ ...f, conditions: [...f.conditions, { field: "priority", op: "eq", value: "" }] }));
  const updateCondition = (index, patch) =>
    setForm((f) => ({
      ...f,
      conditions: f.conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    }));
  const removeCondition = (index) =>
    setForm((f) => ({ ...f, conditions: f.conditions.filter((_, i) => i !== index) }));

  const updateAction = (index, patch) =>
    setForm((f) => ({ ...f, actions: f.actions.map((a, i) => (i === index ? { ...a, ...patch } : a)) }));
  const addAction = () =>
    setForm((f) => ({ ...f, actions: [...f.actions, { type: "add_tag", name: "" }] }));
  const removeAction = (index) =>
    setForm((f) => ({ ...f, actions: f.actions.filter((_, i) => i !== index) }));

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return;
    try {
      await api.createWorkflow({
        name: form.name.trim(),
        trigger: form.trigger,
        conditions: form.conditions,
        actions: form.actions,
      });
      setForm(EMPTY_RULE);
      setError("");
      load();
    } catch (err) {
      setError(
        err.status === 400
          ? "Regola non valida: controlla condizioni e azioni (i valori devono essere fra quelli previsti)."
          : "Creazione della regola non riuscita.",
      );
    }
  };

  const toggle = async (rule) => {
    await api.updateWorkflow(rule.id, { active: !rule.active });
    load();
  };
  const remove = async (rule) => {
    if (!window.confirm(`Eliminare l'automazione "${rule.name}" e il suo storico?`)) return;
    await api.deleteWorkflow(rule.id);
    load();
  };

  const describeArgs = { departments, operators, endpoints };

  const actionFields = (action, index) => {
    if (action.type === "set_priority") {
      return (
        <select aria-label="Priorità" value={action.value || "urgent"} onChange={(e) => updateAction(index, { value: e.target.value })}>
          {["urgent", "high", "normal", "low"].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      );
    }
    if (action.type === "set_department") {
      return (
        <select aria-label="Reparto" value={action.department_id || ""} onChange={(e) => updateAction(index, { department_id: Number(e.target.value) })}>
          <option value="">Scegli…</option>
          {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      );
    }
    if (action.type === "assign_operator") {
      return (
        <select aria-label="Operatore" value={action.operator_id || ""} onChange={(e) => updateAction(index, { operator_id: Number(e.target.value) })}>
          <option value="">Scegli…</option>
          {operators.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
      );
    }
    if (action.type === "add_tag") {
      return (
        <input aria-label="Nome del tag" value={action.name || ""} onChange={(e) => updateAction(index, { name: e.target.value })} placeholder="Nome tag" />
      );
    }
    if (action.type === "send_email") {
      return (
        <>
          <input aria-label="Destinatario" value={action.to || ""} onChange={(e) => updateAction(index, { to: e.target.value })} placeholder="destinatario@azienda.it" />
          <input aria-label="Oggetto" value={action.subject || ""} onChange={(e) => updateAction(index, { subject: e.target.value })} placeholder="Oggetto" />
        </>
      );
    }
    if (action.type === "send_webhook") {
      return (
        <select aria-label="Webhook" value={action.endpoint_id || ""} onChange={(e) => updateAction(index, { endpoint_id: Number(e.target.value) })}>
          <option value="">Scegli…</option>
          {endpoints.map((endpoint) => <option key={endpoint.id} value={endpoint.id}>{endpoint.url}</option>)}
        </select>
      );
    }
    return null;
  };

  return (
    <div>
      <h1 className="wpai-page-title">Automazioni</h1>
      <p style={{ fontSize: 13, color: "var(--text-muted)", margin: "0 0 16px", maxWidth: 660 }}>
        Regole «quando succede X, se vale Y, fai Z». Ogni esecuzione viene registrata — anche
        quando le condizioni non sono soddisfatte — così si vede sempre perché una regola è
        scattata o no.
      </p>

      {loading && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>}
      {error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}

      <div style={{ display: "grid", gap: 12, marginBottom: 20 }}>
        {rules.map((rule) => (
          <div key={rule.id} className="wpai-card">
            <div className="wpai-canned-row">
              <div>
                <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                  {rule.name} {!rule.active && <span className="wpai-badge warn">disattivata</span>}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 3 }}>
                  {TRIGGER_LABELS[rule.trigger] || rule.trigger}
                  {rule.conditions.length > 0 && ` · se ${rule.conditions.map(describeCondition).join(" e ")}`}
                </div>
                <div style={{ fontSize: 12, marginTop: 3 }}>
                  → {rule.actions.map((a) => describeAction(a, describeArgs)).join(" · ")}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 3 }}>
                  {rule.run_count} applicazioni
                  {rule.last_run_at ? ` · ultima ${formatMoment(rule.last_run_at)}` : ""}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <button className="wpai-btn ghost" onClick={() => toggle(rule)}>
                  {rule.active ? "Disattiva" : "Attiva"}
                </button>
                <button className="wpai-icon-btn" title="Elimina" onClick={() => remove(rule)}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
            <Runs workflowId={rule.id} />
          </div>
        ))}
        {!loading && rules.length === 0 && (
          <div className="wpai-card" style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
            Nessuna automazione. Creane una qui sotto: per esempio «quando passa a un operatore,
            se l'intento è reclamo, imposta priorità urgente».
          </div>
        )}
      </div>

      <div style={{ marginBottom: 20 }}>
        <Proactive />
      </div>

      <div className="wpai-card">
        <div className="wpai-card-title"><WorkflowIcon size={15} /> Nuova automazione</div>
        <form onSubmit={create} style={{ display: "grid", gap: 10, marginTop: 10 }}>
          <input
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="Nome, es. Reclami urgenti"
            aria-label="Nome dell'automazione"
          />

          <label style={{ fontSize: 12.5, display: "grid", gap: 4 }}>
            Quando
            <select value={form.trigger} onChange={(e) => setForm((f) => ({ ...f, trigger: e.target.value }))}>
              {(catalog?.triggers || []).map((trigger) => (
                <option key={trigger} value={trigger}>{TRIGGER_LABELS[trigger] || trigger}</option>
              ))}
            </select>
          </label>

          <fieldset style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
            <legend style={{ fontSize: 12, color: "var(--text-muted)" }}>Se (tutte le condizioni)</legend>
            {form.conditions.map((condition, index) => (
              <div key={index} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                <select aria-label="Campo" value={condition.field} onChange={(e) => updateCondition(index, { field: e.target.value })}>
                  {(catalog?.condition_fields || []).map((field) => (
                    <option key={field} value={field}>{FIELD_LABELS[field] || field}</option>
                  ))}
                </select>
                <select aria-label="Operatore" value={condition.op} onChange={(e) => updateCondition(index, { op: e.target.value })}>
                  {(catalog?.condition_ops || []).map((op) => (
                    <option key={op} value={op}>{OP_LABELS[op] || op}</option>
                  ))}
                </select>
                {!VALUELESS_OPS.includes(condition.op) && (
                  <input
                    aria-label="Valore"
                    value={condition.value ?? ""}
                    onChange={(e) => updateCondition(index, { value: e.target.value })}
                    placeholder="valore"
                  />
                )}
                <button className="wpai-icon-btn" type="button" aria-label="Rimuovi condizione" onClick={() => removeCondition(index)}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button className="wpai-btn ghost" type="button" onClick={addCondition}>
              <Plus size={13} /> Condizione
            </button>
          </fieldset>

          <fieldset style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
            <legend style={{ fontSize: 12, color: "var(--text-muted)" }}>Allora (in ordine)</legend>
            {form.actions.map((action, index) => (
              <div key={index} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                <select aria-label="Azione" value={action.type} onChange={(e) => updateAction(index, { type: e.target.value })}>
                  {(catalog?.action_types || []).map((type) => (
                    <option key={type} value={type}>{ACTION_LABELS[type] || type}</option>
                  ))}
                </select>
                {actionFields(action, index)}
                {form.actions.length > 1 && (
                  <button className="wpai-icon-btn" type="button" aria-label="Rimuovi azione" onClick={() => removeAction(index)}>
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
            <button className="wpai-btn ghost" type="button" onClick={addAction}>
              <Plus size={13} /> Azione
            </button>
          </fieldset>

          <button className="wpai-btn" type="submit" disabled={!form.name.trim()} style={{ justifySelf: "start" }}>
            <Play size={14} /> Crea automazione
          </button>
        </form>
      </div>
    </div>
  );
}

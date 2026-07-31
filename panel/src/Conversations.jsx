import { useCallback, useEffect, useState } from "react";
import { Inbox, MessageCircle, Send, Save, CheckCircle2, RotateCcw, Trash2, Timer } from "lucide-react";
import { api } from "./api.js";
import { SLA_STATE_CLASS, SLA_STATE_LABELS, describeSla } from "./sla.js";

function initialsOf(visitorId) {
  return (visitorId || "??").slice(0, 2).toUpperCase();
}

// replace {key} tokens with the operator-filled info value; leave unknown/empty ones as-is
function fillPlaceholders(body, values) {
  return body.replace(/\{(\w+)\}/g, (m, key) =>
    values && values[key] != null && values[key] !== "" ? values[key] : m
  );
}

function SlaBadge({ sla }) {
  if (!sla || !sla.state) return null;
  const lines = describeSla(sla);
  return (
    <span
      className={`wpai-badge ${SLA_STATE_CLASS[sla.state] || "ok"}`}
      title={lines.join(" · ")}
    >
      {SLA_STATE_LABELS[sla.state] || sla.state}
    </span>
  );
}

export default function Conversations() {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const [canned, setCanned] = useState([]);
  const [fields, setFields] = useState([]);
  const [infoValues, setInfoValues] = useState({});
  const [savingInfo, setSavingInfo] = useState(false);
  const [operators, setOperators] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [filters, setFilters] = useState({ status: "", priority: "", assignment: "", department_id: "", sla_state: "" });
  const [listError, setListError] = useState("");
  const [loadingList, setLoadingList] = useState(true);

  const loadList = useCallback(() => {
    const params = {};
    if (filters.status) params.status = filters.status;
    if (filters.priority) params.priority = filters.priority;
    if (filters.department_id) params.department_id = filters.department_id;
    if (filters.sla_state) params.sla_state = filters.sla_state;
    if (filters.assignment === "unassigned") params.unassigned = true;
    else if (filters.assignment) params.assigned_operator_id = filters.assignment;
    return api
      .conversations(params)
      .then((rows) => { setItems(rows); setListError(""); })
      .catch(() => setListError("Impossibile caricare le conversazioni. Riprova."))
      .finally(() => setLoadingList(false));
  }, [filters.status, filters.priority, filters.assignment, filters.department_id, filters.sla_state]);
  const loadMessages = (id) => api.messages(id).then((d) => setMessages(d.messages)).catch(() => {});

  // static-ish per-client config, loaded once
  useEffect(() => {
    api.cannedResponses().then(setCanned).catch(() => {});
    api.infoFields().then(setFields).catch(() => {});
    api.teamOperators().then(setOperators).catch(() => {});
    api.departments().then(setDepartments).catch(() => {});
  }, []);

  useEffect(() => {
    loadList();
    const id = setInterval(loadList, 10000);
    return () => clearInterval(id);
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    setDraft("");
    loadMessages(selected);
    api.conversationInfo(selected).then((d) => setInfoValues(d.info || {})).catch(() => setInfoValues({}));
    const id = setInterval(() => loadMessages(selected), 4000);
    return () => clearInterval(id);
  }, [selected]);

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected) return;
    setSending(true);
    try {
      await api.replyConversation(selected, text);
      setDraft("");
      await loadMessages(selected);
      loadList();
    } finally {
      setSending(false);
    }
  };

  // ping the "operator is typing" state at most once every 2.5s while typing
  const [lastTyping, setLastTyping] = useState(0);
  const pingTyping = () => {
    if (!selected) return;
    const now = Date.now();
    if (now - lastTyping > 2500) {
      setLastTyping(now);
      api.typing(selected).catch(() => {});
    }
  };

  const insertCanned = (body) => {
    const filled = fillPlaceholders(body, infoValues);
    setDraft((prev) => (prev ? prev + "\n" : "") + filled);
  };

  const saveInfo = async () => {
    if (!selected) return;
    setSavingInfo(true);
    try {
      await api.setConversationInfo(selected, infoValues);
    } finally {
      setSavingInfo(false);
    }
  };

  const selectedConv = items.find((x) => x.conversation.id === selected)?.conversation;
  const selectedRow = items.find((x) => x.conversation.id === selected);
  const updateRouting = async (body) => {
    if (!selected) return;
    await api.setConversationRouting(selected, body);
    await loadList();
  };
  const changeStatus = async (status) => {
    if (!selected) return;
    await api.setConversationStatus(selected, status);
    loadList();
  };
  const deleteConv = async () => {
    if (!selected) return;
    if (!window.confirm("Eliminare definitivamente questa conversazione e tutti i suoi messaggi? L'operazione non è reversibile.")) return;
    await api.deleteConversation(selected);
    setSelected(null);
    setMessages([]);
    loadList();
  };

  return (
    <div>
      <h1 className="wpai-page-title">Conversazioni</h1>
      <div className="wpai-filters" style={{ marginBottom: 14 }}>
        <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
          <option value="">Tutti gli stati</option><option value="open">Aperte</option><option value="escalated">Escalation</option><option value="closed">Chiuse</option>
        </select>
        <select value={filters.priority} onChange={(e) => setFilters((f) => ({ ...f, priority: e.target.value }))}>
          <option value="">Tutte le priorità</option><option value="urgent">Urgente</option><option value="high">Alta</option><option value="normal">Normale</option><option value="low">Bassa</option>
        </select>
        <select value={filters.assignment} onChange={(e) => setFilters((f) => ({ ...f, assignment: e.target.value }))}>
          <option value="">Tutte le assegnazioni</option><option value="unassigned">Non assegnate</option>
          {operators.map((op) => <option key={op.id} value={op.id}>{op.name}</option>)}
        </select>
        <select value={filters.department_id} onChange={(e) => setFilters((f) => ({ ...f, department_id: e.target.value }))}>
          <option value="">Tutti i reparti</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <select aria-label="Stato SLA" value={filters.sla_state} onChange={(e) => setFilters((f) => ({ ...f, sla_state: e.target.value }))}>
          <option value="">Tutti gli SLA</option><option value="violato">SLA violati</option><option value="in_scadenza">In scadenza</option><option value="ok">Nei tempi</option>
        </select>
      </div>
      <div className="wpai-split">
        <div className="wpai-conv-list">
          {loadingList && <div className="wpai-empty"><p>Caricamento…</p></div>}
          {!loadingList && listError && (
            <div className="wpai-empty">
              <p>{listError}</p>
              <button className="wpai-btn ghost" onClick={loadList}>Riprova</button>
            </div>
          )}
          {!loadingList && !listError && items.length === 0 && (
            <div className="wpai-empty">
              <Inbox size={28} strokeWidth={1.5} />
              <p>Nessuna conversazione con questi filtri.</p>
            </div>
          )}
          {items.map(({ conversation: c, last_message, sla }) => (
            <button
              key={c.id}
              className={"wpai-conv-item" + (c.id === selected ? " active" : "")}
              onClick={() => setSelected(c.id)}
            >
              <div className="wpai-conv-avatar">{initialsOf(c.visitor_id)}</div>
              <div className="wpai-conv-item-body">
                <div className="meta">
                  #{c.id} · <span className={`wpai-badge ${c.status}`}>{c.status}</span> · {c.priority}
                  {sla && <> · <SlaBadge sla={sla} /></>}
                </div>
                <div className="preview">{last_message || "—"}</div>
                <div className="meta">{departments.find((d) => d.id === c.department_id)?.name || "Nessun reparto"} · {operators.find((o) => o.id === c.assigned_operator_id)?.name || "Non assegnata"}</div>
              </div>
            </button>
          ))}
        </div>

        <div className="wpai-conv-panel">
          {!selected ? (
            <div className="wpai-card wpai-thread">
              <div className="wpai-empty" style={{ margin: "auto" }}>
                <MessageCircle size={28} strokeWidth={1.5} />
                <p>Seleziona una conversazione per leggerla.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="wpai-conv-toolbar">
                <span className={`wpai-badge ${selectedConv?.status || "open"}`}>{selectedConv?.status || "—"}</span>
                <select aria-label="Priorità" value={selectedConv?.priority || "normal"} onChange={(e) => updateRouting({ priority: e.target.value })}>
                  <option value="urgent">Urgente</option><option value="high">Alta</option><option value="normal">Normale</option><option value="low">Bassa</option>
                </select>
                {selectedConv?.status === "closed" ? (
                  <button className="wpai-btn ghost" onClick={() => changeStatus("open")}>
                    <RotateCcw size={14} /> Riapri
                  </button>
                ) : (
                  <button className="wpai-btn ghost" onClick={() => changeStatus("closed")}>
                    <CheckCircle2 size={14} /> Chiudi
                  </button>
                )}
                <button className="wpai-icon-btn" title="Elimina (GDPR)" onClick={deleteConv}>
                  <Trash2 size={15} />
                </button>
              </div>
              <div className="wpai-card wpai-thread">
                {messages.map((m) => (
                  <div key={m.id} className={`wpai-bubble ${m.role}`}>{m.content}</div>
                ))}
              </div>
              <form className="wpai-reply-bar" onSubmit={(e) => { e.preventDefault(); send(); }}>
                <textarea
                  rows={1}
                  value={draft}
                  onChange={(e) => { setDraft(e.target.value); pingTyping(); }}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Rispondi come operatore… (Invio per inviare, Shift+Invio a capo)"
                />
                <button className="wpai-btn" type="submit" disabled={sending || !draft.trim()}>
                  <Send size={15} /> {sending ? "Invio…" : "Invia"}
                </button>
              </form>
            </>
          )}
        </div>

        {selected && (
          <aside className="wpai-conv-side">
            {selectedRow?.sla && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>
                  <Timer size={15} /> SLA <SlaBadge sla={selectedRow.sla} />
                </div>
                <ul className="wpai-sla-list">
                  {describeSla(selectedRow.sla).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            <div className="wpai-card">
              <div className="wpai-card-title" style={{ marginBottom: 10 }}>Instradamento</div>
              <div className="wpai-field" style={{ marginBottom: 8 }}>
                <label>Operatore</label>
                <select value={selectedRow?.conversation.assigned_operator_id || ""} onChange={(e) => updateRouting(e.target.value ? { assigned_operator_id: Number(e.target.value) } : { clear_assignee: true })}>
                  <option value="">Non assegnata</option>{operators.map((op) => <option key={op.id} value={op.id}>{op.name}</option>)}
                </select>
              </div>
              <div className="wpai-field" style={{ marginBottom: 0 }}>
                <label>Reparto</label>
                <select value={selectedRow?.conversation.department_id || ""} onChange={(e) => updateRouting(e.target.value ? { department_id: Number(e.target.value) } : { clear_department: true })}>
                  <option value="">Nessun reparto</option>{departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
            </div>
            {fields.length > 0 && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>Informazioni</div>
                {fields.map((f) => (
                  <div key={f.id} className="wpai-field" style={{ marginBottom: 8 }}>
                    <label>{f.label}</label>
                    <input
                      value={infoValues[f.key] || ""}
                      onChange={(e) => setInfoValues((v) => ({ ...v, [f.key]: e.target.value }))}
                      placeholder={`{${f.key}}`}
                    />
                  </div>
                ))}
                <button className="wpai-btn ghost" onClick={saveInfo} disabled={savingInfo}>
                  <Save size={14} /> {savingInfo ? "Salvataggio…" : "Salva"}
                </button>
              </div>
            )}

            {canned.length > 0 && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>Risposte predefinite</div>
                <div className="wpai-canned-list">
                  {canned.map((c) => (
                    <button
                      key={c.id}
                      className="wpai-canned-btn"
                      title={c.body}
                      onClick={() => insertCanned(c.body)}
                    >
                      {c.title}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {fields.length === 0 && canned.length === 0 && (
              <div className="wpai-card" style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                Configura risposte predefinite e campi info in <b>Configurazione</b>.
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

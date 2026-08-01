import { useCallback, useEffect, useRef, useState } from "react";
import {
  Inbox, MessageCircle, Send, Save, CheckCircle2, RotateCcw, Trash2, Timer, Bookmark, Users,
  StickyNote, AtSign, History, AlertTriangle, Tag as TagIcon, Sparkles, Star,
} from "lucide-react";
import { api } from "./api.js";
import { SLA_STATE_CLASS, SLA_STATE_LABELS, describeSla } from "./sla.js";
import { actionLabel, actorLabel, formatMoment } from "./activity.js";
import {
  EMPTY_FILTERS,
  INTENT_LABELS,
  LANGUAGE_LABELS,
  URGENCY_LABELS,
  fromApiFilters,
  hasActiveFilters,
  matchesView,
  toApiFilters,
  toQueryParams,
} from "./inboxFilters.js";

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
  const [deliveryError, setDeliveryError] = useState("");

  const [canned, setCanned] = useState([]);
  const [fields, setFields] = useState([]);
  const [infoValues, setInfoValues] = useState({});
  const [savingInfo, setSavingInfo] = useState(false);
  const [operators, setOperators] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [listError, setListError] = useState("");
  const [loadingList, setLoadingList] = useState(true);
  const [views, setViews] = useState([]);
  const [viewForm, setViewForm] = useState(null); // {name, shared} mentre si salva una vista
  const [viewError, setViewError] = useState("");

  const loadList = useCallback(() => {
    return api
      .conversations(toQueryParams(filters))
      .then((rows) => { setItems(rows); setListError(""); })
      .catch(() => setListError("Impossibile caricare le conversazioni. Riprova."))
      .finally(() => setLoadingList(false));
  }, [filters]);

  const loadViews = useCallback(
    () => api.savedViews().then(setViews).catch(() => setViews([])),
    [],
  );

  // collaborazione: note interne, menzioni, presenza e audit della conversazione
  const [notes, setNotes] = useState([]);
  const [noteDraft, setNoteDraft] = useState("");
  const [noteMentions, setNoteMentions] = useState([]);
  const [savingNote, setSavingNote] = useState(false);
  const [noteError, setNoteError] = useState("");
  const [activity, setActivity] = useState([]);
  const [presence, setPresence] = useState({ others: [], conflict: false });
  const [mentions, setMentions] = useState([]);

  const [tags, setTags] = useState([]);
  const [tagDraft, setTagDraft] = useState("");
  const [classifying, setClassifying] = useState(false);
  const [tagError, setTagError] = useState("");

  const loadTags = useCallback(() => api.tags().then(setTags).catch(() => setTags([])), []);
  const loadMentions = useCallback(
    () => api.mentions().then(setMentions).catch(() => setMentions([])),
    [],
  );
  const loadNotes = useCallback((id) => {
    api.notes(id).then(setNotes).catch(() => setNotes([]));
    api.conversationActivity(id).then(setActivity).catch(() => setActivity([]));
  }, []);
  const loadMessages = (id) => api.messages(id).then((d) => setMessages(d.messages)).catch(() => {});

  // static-ish per-client config, loaded once
  useEffect(() => {
    api.cannedResponses().then(setCanned).catch(() => {});
    api.infoFields().then(setFields).catch(() => {});
    api.teamOperators().then(setOperators).catch(() => {});
    api.departments().then(setDepartments).catch(() => {});
    loadViews();
    loadMentions();
    loadTags();
  }, [loadViews, loadMentions, loadTags]);

  const addTag = async (e) => {
    e.preventDefault();
    const name = tagDraft.trim();
    if (!name || !selected) return;
    try {
      await api.tagConversation(selected, { name });
      setTagDraft("");
      setTagError("");
      await Promise.all([loadList(), loadTags()]);
    } catch {
      setTagError("Impossibile aggiungere il tag.");
    }
  };
  const attachTag = async (tagId) => {
    if (!tagId || !selected) return;
    try {
      await api.tagConversation(selected, { tag_id: Number(tagId) });
      setTagError("");
      await loadList();
    } catch {
      setTagError("Impossibile aggiungere il tag.");
    }
  };
  const removeTag = async (tagId) => {
    if (!selected) return;
    await api.untagConversation(selected, tagId);
    await loadList();
  };
  const classify = async () => {
    if (!selected) return;
    setClassifying(true);
    setTagError("");
    try {
      await api.classifyConversation(selected);
      await Promise.all([loadList(), loadTags()]);
    } catch (err) {
      setTagError(
        err.status === 503
          ? "Classificazione non disponibile in questo momento: la conversazione resta invariata."
          : "Classificazione non riuscita.",
      );
    } finally {
      setClassifying(false);
    }
  };

  const applyView = (view) => {
    setViewForm(null);
    setViewError("");
    setFilters(fromApiFilters(view.filters, view.sort));
  };
  const saveView = async (e) => {
    e.preventDefault();
    const name = (viewForm?.name || "").trim();
    if (!name) return;
    try {
      await api.createSavedView({
        name,
        filters: toApiFilters(filters),
        sort: filters.sort || "recent",
        shared: Boolean(viewForm.shared),
      });
      setViewForm(null);
      setViewError("");
      loadViews();
    } catch {
      setViewError("Impossibile salvare la vista.");
    }
  };
  const removeView = async (view) => {
    if (!window.confirm(`Eliminare la vista "${view.name}"?`)) return;
    try {
      await api.deleteSavedView(view.id);
      loadViews();
    } catch {
      setViewError("Solo chi ha creato la vista può eliminarla.");
    }
  };

  useEffect(() => {
    loadList();
    const id = setInterval(loadList, 10000);
    return () => clearInterval(id);
  }, [loadList]);

  useEffect(() => {
    if (!selected) return;
    setDraft("");
    setNoteDraft("");
    setNoteMentions([]);
    setNoteError("");
    setDeliveryError("");
    setPresence({ others: [], conflict: false });
    loadMessages(selected);
    loadNotes(selected);
    loadMentions();
    api.conversationInfo(selected).then((d) => setInfoValues(d.info || {})).catch(() => setInfoValues({}));
    const id = setInterval(() => loadMessages(selected), 4000);
    return () => clearInterval(id);
  }, [selected, loadNotes, loadMentions]);

  // battito di presenza: segnala che questa conversazione è aperta e raccoglie chi altro la sta
  // guardando, così due operatori non rispondono in contemporanea
  const draftRef = useRef("");
  draftRef.current = draft;
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    const beat = () => {
      api
        .presence(selected, draftRef.current.trim().length > 0)
        .then((data) => { if (!cancelled) setPresence(data); })
        .catch(() => {});
    };
    beat();
    const id = setInterval(beat, 10000);
    return () => { cancelled = true; clearInterval(id); };
  }, [selected]);

  const send = async () => {
    const text = draft.trim();
    if (!text || !selected) return;
    setSending(true);
    setDeliveryError("");
    try {
      const result = await api.replyConversation(selected, text);
      setDraft("");
      if (result.delivered === false) {
        setDeliveryError(
          selectedRow?.conversation.channel === "whatsapp"
            ? "Risposta salvata ma non consegnata. La finestra WhatsApp di 24 ore potrebbe essere scaduta oppure il canale non è ancora configurato."
            : "Risposta salvata ma non consegnata al destinatario. Verifica la configurazione del canale."
        );
      }
      await loadMessages(selected);
      loadNotes(selected);
      loadList();
    } finally {
      setSending(false);
    }
  };

  const addNote = async (e) => {
    e.preventDefault();
    const text = noteDraft.trim();
    if (!text || !selected) return;
    setSavingNote(true);
    try {
      await api.createNote(selected, text, noteMentions);
      setNoteDraft("");
      setNoteMentions([]);
      setNoteError("");
      loadNotes(selected);
    } catch {
      setNoteError("Impossibile salvare la nota.");
    } finally {
      setSavingNote(false);
    }
  };
  const removeNote = async (noteId) => {
    try {
      await api.deleteNote(selected, noteId);
      loadNotes(selected);
    } catch {
      setNoteError("Solo chi ha scritto la nota può eliminarla.");
    }
  };
  const mentionOperator = (operatorId) => {
    const member = operators.find((op) => String(op.id) === String(operatorId));
    if (!member) return;
    setNoteMentions((prev) => (prev.includes(member.id) ? prev : [...prev, member.id]));
    setNoteDraft((prev) => (prev ? `${prev} ` : "") + `@${member.name} `);
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

      {mentions.length > 0 && (
        <div className="wpai-callout" role="status">
          <AtSign size={15} aria-hidden="true" />
          <div>
            <b>Ti hanno citato in {mentions.length} {mentions.length === 1 ? "nota" : "note"}.</b>{" "}
            {mentions.slice(0, 3).map((m) => (
              <button key={m.id} className="wpai-link-btn" onClick={() => setSelected(m.conversation_id)}>
                #{m.conversation_id}
              </button>
            ))}
          </div>
          <button
            className="wpai-btn ghost"
            onClick={() => api.markMentionsRead([]).then(loadMentions).catch(() => {})}
          >
            Segna come lette
          </button>
        </div>
      )}

      <div className="wpai-views" role="group" aria-label="Viste salvate">
        <button
          className={"wpai-view-chip" + (!hasActiveFilters(filters) && filters.sort === "recent" ? " active" : "")}
          onClick={() => { setFilters(EMPTY_FILTERS); setViewForm(null); }}
        >
          Tutte
        </button>
        {views.map((view) => (
          <span key={view.id} className={"wpai-view-chip" + (matchesView(filters, view) ? " active" : "")}>
            <button onClick={() => applyView(view)} title={view.shared ? `Condivisa da ${view.owner_name}` : "Vista personale"}>
              {view.shared && <Users size={12} aria-hidden="true" />} {view.name}
            </button>
            {view.mine && (
              <button
                className="wpai-chip-x"
                aria-label={`Elimina la vista ${view.name}`}
                onClick={() => removeView(view)}
              >
                ×
              </button>
            )}
          </span>
        ))}
        {viewForm ? (
          <form className="wpai-view-form" onSubmit={saveView}>
            <input
              autoFocus
              aria-label="Nome della vista"
              value={viewForm.name}
              onChange={(e) => setViewForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="Nome vista"
            />
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 5 }}>
              <input
                type="checkbox"
                checked={Boolean(viewForm.shared)}
                onChange={(e) => setViewForm((f) => ({ ...f, shared: e.target.checked }))}
              />
              Condivisa
            </label>
            <button className="wpai-btn" type="submit" disabled={!viewForm.name.trim()}>Salva</button>
            <button className="wpai-btn ghost" type="button" onClick={() => { setViewForm(null); setViewError(""); }}>Annulla</button>
          </form>
        ) : (
          <button className="wpai-view-chip" onClick={() => setViewForm({ name: "", shared: false })}>
            <Bookmark size={12} aria-hidden="true" /> Salva vista
          </button>
        )}
      </div>
      {viewError && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)", margin: "0 0 10px" }}>{viewError}</p>}

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
        <select aria-label="Tag" value={filters.tag_id} onChange={(e) => setFilters((f) => ({ ...f, tag_id: e.target.value }))}>
          <option value="">Tutti i tag</option>{tags.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <select aria-label="Intento" value={filters.intent} onChange={(e) => setFilters((f) => ({ ...f, intent: e.target.value }))}>
          <option value="">Tutti gli intenti</option>
          {Object.entries(INTENT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <select aria-label="Urgenza rilevata" value={filters.urgency} onChange={(e) => setFilters((f) => ({ ...f, urgency: e.target.value }))}>
          <option value="">Tutte le urgenze</option>
          {Object.entries(URGENCY_LABELS).map(([value, label]) => <option key={value} value={value}>Urgenza {label.toLowerCase()}</option>)}
        </select>
        <select aria-label="Lingua" value={filters.conversation_language} onChange={(e) => setFilters((f) => ({ ...f, conversation_language: e.target.value }))}>
          <option value="">Tutte le lingue</option>
          {Object.entries(LANGUAGE_LABELS).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
        </select>
        <select aria-label="Canale" value={filters.channel} onChange={(e) => setFilters((f) => ({ ...f, channel: e.target.value }))}>
          <option value="">Tutti i canali</option><option value="web">Web</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option><option value="messenger">Messenger</option>
        </select>
        <select aria-label="Ordinamento" value={filters.sort} onChange={(e) => setFilters((f) => ({ ...f, sort: e.target.value }))}>
          <option value="recent">Più recenti</option><option value="oldest">Meno recenti</option><option value="priority">Priorità</option><option value="sla">Scadenza SLA</option>
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
          {items.map(({ conversation: c, last_message, sla, tags: convTags = [], rating }) => (
            <button
              key={c.id}
              className={"wpai-conv-item" + (c.id === selected ? " active" : "")}
              onClick={() => setSelected(c.id)}
            >
              <div className="wpai-conv-avatar">{initialsOf(c.visitor_id)}</div>
              <div className="wpai-conv-item-body">
                <div className="meta">
                  #{c.id} · <span className={`wpai-badge ${c.status}`}>{c.status}</span> · {c.priority}
                  {c.language && c.language !== "it" && ` · ${LANGUAGE_LABELS[c.language] || c.language}`}
                  {c.channel && c.channel !== "web" && ` · ${c.channel}`}
                  {sla && <> · <SlaBadge sla={sla} /></>}
                </div>
                <div className="preview">{last_message || "—"}</div>
                <div className="meta">{departments.find((d) => d.id === c.department_id)?.name || "Nessun reparto"} · {operators.find((o) => o.id === c.assigned_operator_id)?.name || "Non assegnata"}</div>
                {rating && (
                  <div className="meta" title={rating.comment || ""}>
                    Valutazione: {"★".repeat(rating.score)}{"☆".repeat(5 - rating.score)}
                  </div>
                )}
                {convTags.length > 0 && (
                  <div className="wpai-tag-row">
                    {convTags.map((t) => (
                      <span key={t.id} className={"wpai-tag" + (t.source === "ai" ? " ai" : "")}>{t.name}</span>
                    ))}
                  </div>
                )}
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
              {presence.others.length > 0 && (
                <div className={"wpai-callout" + (presence.conflict ? " warn" : "")} role="status">
                  {presence.conflict ? <AlertTriangle size={15} aria-hidden="true" /> : <Users size={15} aria-hidden="true" />}
                  <div>
                    {presence.conflict
                      ? `${presence.others.filter((o) => o.composing).map((o) => o.name).join(", ")} sta già scrivendo una risposta.`
                      : `Anche ${presence.others.map((o) => o.name).join(", ")} sta guardando questa conversazione.`}
                  </div>
                </div>
              )}
              {deliveryError && (
                <div className="wpai-callout warn" role="alert">
                  <AlertTriangle size={15} aria-hidden="true" />
                  <div>{deliveryError}</div>
                </div>
              )}
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
            {selectedRow?.rating && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 8 }}>
                  <Star size={15} /> Valutazione del visitatore
                </div>
                <div style={{ fontSize: 16 }}>
                  {"★".repeat(selectedRow.rating.score)}
                  <span style={{ color: "var(--text-faint)" }}>{"☆".repeat(5 - selectedRow.rating.score)}</span>
                </div>
                {selectedRow.rating.comment && (
                  <p style={{ fontSize: 12.5, margin: "8px 0 0", whiteSpace: "pre-wrap" }}>
                    “{selectedRow.rating.comment}”
                  </p>
                )}
                <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "8px 0 0" }}>
                  Risolta da {selectedRow.rating.resolved_by === "ai" ? "AI" : "operatore"} ·{" "}
                  {formatMoment(selectedRow.rating.created_at)}
                </p>
              </div>
            )}

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
            <div className="wpai-card">
              <div className="wpai-card-title" style={{ marginBottom: 10 }}>
                <TagIcon size={15} /> Tag e classificazione
              </div>
              <div className="wpai-tag-row" style={{ marginBottom: 8 }}>
                {(selectedRow?.tags || []).map((t) => (
                  <span key={t.id} className={"wpai-tag" + (t.source === "ai" ? " ai" : "")}>
                    {t.name}
                    <button className="wpai-chip-x" aria-label={`Rimuovi il tag ${t.name}`} onClick={() => removeTag(t.id)}>×</button>
                  </span>
                ))}
                {(selectedRow?.tags || []).length === 0 && (
                  <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Nessun tag.</span>
                )}
              </div>
              <form onSubmit={addTag} style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                <input
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  placeholder="Nuovo tag"
                  aria-label="Nuovo tag"
                  style={{ flex: 1, minWidth: 120 }}
                />
                <button className="wpai-btn ghost" type="submit" disabled={!tagDraft.trim()}>Aggiungi</button>
              </form>
              {tags.length > 0 && (
                <select aria-label="Tag esistenti" value="" onChange={(e) => attachTag(e.target.value)} style={{ marginBottom: 8 }}>
                  <option value="">Tag esistente…</option>
                  {tags
                    .filter((t) => !(selectedRow?.tags || []).some((x) => x.id === t.id))
                    .map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              )}
              {selectedRow?.classification ? (
                <ul className="wpai-sla-list">
                  <li>Intento: <b>{INTENT_LABELS[selectedRow.classification.intent] || "—"}</b></li>
                  <li>Argomento: <b>{selectedRow.classification.topic || "—"}</b></li>
                  <li>Urgenza rilevata: <b>{URGENCY_LABELS[selectedRow.classification.urgency] || "—"}</b></li>
                </ul>
              ) : (
                <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 8px" }}>
                  Nessuna classificazione AI. È solo un suggerimento: non cambia stato, priorità o assegnazione.
                </p>
              )}
              <button className="wpai-btn ghost" onClick={classify} disabled={classifying} style={{ marginTop: 8 }}>
                <Sparkles size={14} /> {classifying ? "Classificazione…" : "Classifica con AI"}
              </button>
              {tagError && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)", margin: "8px 0 0" }}>{tagError}</p>}
            </div>

            <div className="wpai-card">
              <div className="wpai-card-title" style={{ marginBottom: 10 }}>
                <StickyNote size={15} /> Note interne
              </div>
              <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 10px" }}>
                Visibili solo al team: il visitatore non le riceve mai.
              </p>
              <div className="wpai-note-list">
                {notes.map((note) => (
                  <div key={note.id} className="wpai-note">
                    <div className="wpai-note-head">
                      <span>{note.author}</span>
                      <span>{formatMoment(note.created_at)}</span>
                      <button
                        className="wpai-chip-x"
                        aria-label="Elimina la nota"
                        onClick={() => removeNote(note.id)}
                      >
                        ×
                      </button>
                    </div>
                    <div className="wpai-note-body">{note.body}</div>
                    {note.mentions.length > 0 && (
                      <div className="wpai-note-mentions">
                        <AtSign size={11} aria-hidden="true" /> {note.mentions.map((m) => m.name).join(", ")}
                      </div>
                    )}
                  </div>
                ))}
                {notes.length === 0 && (
                  <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: 0 }}>Nessuna nota.</p>
                )}
              </div>
              <form onSubmit={addNote} style={{ display: "grid", gap: 6, marginTop: 10 }}>
                <textarea
                  rows={2}
                  value={noteDraft}
                  onChange={(e) => setNoteDraft(e.target.value)}
                  placeholder="Nota interna… usa @nome per citare un collega"
                />
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {operators.length > 1 && (
                    <select
                      aria-label="Cita un operatore"
                      value=""
                      onChange={(e) => mentionOperator(e.target.value)}
                    >
                      <option value="">Cita…</option>
                      {operators.map((op) => <option key={op.id} value={op.id}>{op.name}</option>)}
                    </select>
                  )}
                  <button className="wpai-btn" type="submit" disabled={savingNote || !noteDraft.trim()}>
                    {savingNote ? "Salvataggio…" : "Aggiungi nota"}
                  </button>
                </div>
              </form>
              {noteError && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)", margin: "8px 0 0" }}>{noteError}</p>}
            </div>

            {activity.length > 0 && (
              <div className="wpai-card">
                <div className="wpai-card-title" style={{ marginBottom: 10 }}>
                  <History size={15} /> Attività
                </div>
                <ul className="wpai-activity">
                  {activity.slice(0, 12).map((entry) => (
                    <li key={entry.id}>
                      <span>{actionLabel(entry.action)}</span>
                      <span className="dim">{actorLabel(entry)} · {formatMoment(entry.created_at)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

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

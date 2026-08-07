import { useCallback, useEffect, useState } from "react";
import { History, MessageCircleMore, Plus, Trash2, Trophy } from "lucide-react";
import { api } from "./api.js";
import Loading from "./Loading.jsx";

const TRIGGER_LABELS = {
  url: "Su una pagina specifica",
  time_on_page: "Dopo un po' sulla pagina",
  exit_intent: "Quando sta per uscire",
  cart: "Con il carrello pieno",
};

const FREQUENCY_LABELS = {
  once_per_session: "Una volta per sessione",
  once_per_day: "Una volta al giorno",
  always: "Ogni volta",
};

const EMPTY = {
  name: "",
  message: "",
  message_b: "",
  trigger_type: "time_on_page",
  url_pattern: "",
  delay_seconds: 20,
  frequency: "once_per_day",
};

function pct(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

export default function Proactive() {
  const [rules, setRules] = useState([]);
  const [catalog, setCatalog] = useState({ triggers: [], frequencies: [] });
  const [experiments, setExperiments] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(
    () =>
      api
        .proactiveRules()
        .then((data) => {
          setRules(data.rules);
          setCatalog({ triggers: data.triggers, frequencies: data.frequencies });
          setExperiments(data.experiments || []);
          setError("");
        })
        .catch(() => setError("Impossibile caricare i messaggi proattivi."))
        .finally(() => setLoading(false)),
    [],
  );
  useEffect(() => { load(); }, [load]);

  const create = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.message.trim()) return;
    try {
      await api.createProactiveRule({
        ...form,
        name: form.name.trim(),
        message: form.message.trim(),
        delay_seconds: Number(form.delay_seconds) || 0,
      });
      setForm(EMPTY);
      setError("");
      load();
    } catch {
      setError("Creazione del messaggio non riuscita: controlla i campi.");
    }
  };
  const toggle = async (rule) => { await api.updateProactiveRule(rule.id, { active: !rule.active }); load(); };
  const remove = async (rule) => {
    if (!window.confirm(`Eliminare il messaggio "${rule.name}"?`)) return;
    await api.deleteProactiveRule(rule.id);
    load();
  };
  const finishExperiment = async (rule, action) => {
    const label = action === "promote" ? `promuovere la variante ${rule.ab_test.winner.toUpperCase()}` : "terminare il test senza un vincitore";
    if (!window.confirm(`Vuoi ${label}? I risultati resteranno nello storico.`)) return;
    try {
      await api.finishProactiveExperiment(rule.id, action);
      await load();
    } catch {
      setError("Impossibile chiudere l’esperimento.");
    }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><MessageCircleMore size={15} /> Messaggi proattivi</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Il widget propone il messaggio prima che il visitatore scriva. Ne mostra al massimo uno
        per pagina, mai a chat aperta o su una conversazione già avviata, e chi sceglie «Non
        mostrare più» non lo rivede.
      </p>

      {loading && <Loading inline />}
      {error && <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}

      <div style={{ display: "grid", gap: 10, marginBottom: 12 }}>
        {rules.map((rule) => (
          <div key={rule.id} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
            <div className="wpai-canned-row">
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {rule.name} {!rule.active && <span className="wpai-badge warn">disattivato</span>}
                </div>
                <div style={{ fontSize: 12.5, margin: "3px 0" }}>«{rule.message}»</div>
                {rule.message_b && (
                  <div style={{ fontSize: 12.5, margin: "3px 0" }}>B · «{rule.message_b}»</div>
                )}
                <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
                  {TRIGGER_LABELS[rule.trigger_type] || rule.trigger_type}
                  {rule.trigger_type === "time_on_page" && ` (${rule.delay_seconds}s)`}
                  {rule.url_pattern && ` · URL contiene «${rule.url_pattern}»`}
                  {` · ${FREQUENCY_LABELS[rule.frequency] || rule.frequency}`}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--text-faint)", marginTop: 2 }}>
                  {rule.impressions} visualizzazioni · {rule.engagements} chat aperte ·{" "}
                  {pct(rule.engagement_rate)} di conversione
                  {rule.message_b && ` · B: ${rule.impressions_b} visualizzazioni, ${rule.engagements_b} chat, ${pct(rule.engagement_rate_b)}`}
                </div>
                {rule.message_b && rule.ab_test.status === "collecting" && (
                  <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 5 }}>
                    Test in raccolta dati · servono ancora almeno {rule.ab_test.remaining} visualizzazioni per variante
                  </div>
                )}
                {rule.message_b && rule.ab_test.status === "inconclusive" && (
                  <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 5 }}>
                    Nessun vincitore affidabile: continua il test
                  </div>
                )}
                {rule.ab_test.status === "winner" && (
                  <div style={{ marginTop: 6 }}>
                    <span className="wpai-badge ok">
                      Variante {rule.ab_test.winner.toUpperCase()} vincente
                      {rule.ab_test.lift_percent !== null && ` · +${rule.ab_test.lift_percent}%`}
                    </span>
                    <button className="wpai-btn ghost" style={{ marginLeft: 6 }} onClick={() => finishExperiment(rule, "promote")}>
                      <Trophy size={13} /> Promuovi vincitore
                    </button>
                  </div>
                )}
                {rule.message_b && rule.ab_test.status === "inconclusive" && (
                  <button className="wpai-btn ghost" style={{ marginTop: 6 }} onClick={() => finishExperiment(rule, "stop")}>
                    Termina test
                  </button>
                )}
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
          </div>
        ))}
        {!loading && rules.length === 0 && (
          <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Nessun messaggio proattivo.</span>
        )}
      </div>

      {experiments.length > 0 && (
        <details style={{ marginBottom: 14 }}>
          <summary style={{ cursor: "pointer", fontSize: 12.5, fontWeight: 600 }}>
            <History size={13} style={{ verticalAlign: "-2px", marginRight: 5 }} /> Storico esperimenti ({experiments.length})
          </summary>
          <div style={{ display: "grid", gap: 7, marginTop: 9 }}>
            {experiments.map((item) => (
              <div key={item.id} style={{ fontSize: 11.5, color: "var(--text-muted)", paddingBottom: 7, borderBottom: "1px solid var(--border)" }}>
                <strong style={{ color: "var(--text)" }}>{item.rule_name}</strong> · {item.outcome === "promoted" ? `promossa ${item.selected_variant.toUpperCase()}` : "interrotto"}
                {` · A ${item.engagements_a}/${item.impressions_a} · B ${item.engagements_b}/${item.impressions_b}`}
                {item.operator_email && ` · ${item.operator_email}`}
              </div>
            ))}
          </div>
        </details>
      )}

      <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
        <input
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="Nome interno, es. Recupero carrello"
          aria-label="Nome del messaggio"
        />
        <textarea
          rows={2}
          value={form.message}
          onChange={(e) => setForm((f) => ({ ...f, message: e.target.value }))}
          placeholder="Messaggio mostrato al visitatore, es. Posso aiutarti a completare l'ordine?"
          aria-label="Messaggio"
        />
        <textarea
          rows={2}
          value={form.message_b}
          onChange={(e) => setForm((f) => ({ ...f, message_b: e.target.value }))}
          placeholder="Variante B facoltativa per un test A/B"
          aria-label="Variante B"
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <select
            aria-label="Quando mostrarlo"
            value={form.trigger_type}
            onChange={(e) => setForm((f) => ({ ...f, trigger_type: e.target.value }))}
          >
            {catalog.triggers.map((trigger) => (
              <option key={trigger} value={trigger}>{TRIGGER_LABELS[trigger] || trigger}</option>
            ))}
          </select>
          {form.trigger_type === "time_on_page" && (
            <label style={{ fontSize: 12.5, display: "flex", alignItems: "center", gap: 6 }}>
              dopo
              <input
                type="number"
                min="1"
                max="3600"
                value={form.delay_seconds}
                onChange={(e) => setForm((f) => ({ ...f, delay_seconds: e.target.value }))}
                style={{ width: 80 }}
                aria-label="Secondi sulla pagina"
              />
              s
            </label>
          )}
          <select
            aria-label="Frequenza"
            value={form.frequency}
            onChange={(e) => setForm((f) => ({ ...f, frequency: e.target.value }))}
          >
            {catalog.frequencies.map((frequency) => (
              <option key={frequency} value={frequency}>{FREQUENCY_LABELS[frequency] || frequency}</option>
            ))}
          </select>
        </div>
        <input
          value={form.url_pattern}
          onChange={(e) => setForm((f) => ({ ...f, url_pattern: e.target.value }))}
          placeholder="Solo se l'URL contiene… (facoltativo, es. /spedizioni)"
          aria-label="Filtro URL"
        />
        <button className="wpai-btn" type="submit" disabled={!form.name.trim() || !form.message.trim()} style={{ justifySelf: "start" }}>
          <Plus size={14} /> Aggiungi messaggio
        </button>
      </form>
    </div>
  );
}

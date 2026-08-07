import { useCallback, useEffect, useState } from "react";
import {
  Shield, Building2, Plus, Eye, EyeOff, Copy, Check, RefreshCw,
  Trash2, MessageSquare, Users, FileText, Package, Sparkles, CreditCard,
  LayoutDashboard, Activity, ScrollText, AlertTriangle, Search,
  ThumbsUp, ThumbsDown, X, TrendingUp,
} from "lucide-react";
import { getAdminKey, setAdminKey, clearAdminKey, adminApi } from "./adminApi.js";
import { MiniBars, Breakdown } from "./Charts.jsx";
import ThemeToggle from "./ThemeToggle.jsx";
import Loading from "./Loading.jsx";

function formatPrice(cents, currency) {
  if (!cents) return "Gratis";
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: currency || "eur" }).format(cents / 100);
}

function NewClientForm({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [origins, setOrigins] = useState("");
  const [result, setResult] = useState(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const client = await adminApi.createClient(name, origins);
      setResult(client);
      setName("");
      setOrigins("");
      onCreated();
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button className="wpai-btn" onClick={() => setOpen(true)}>
        <Plus size={15} /> Nuovo cliente
      </button>
    );
  }

  return (
    <div className="wpai-card" style={{ marginBottom: 16 }}>
      {result ? (
        <>
          <div className="wpai-success" style={{ marginBottom: 10 }}>
            Cliente "{result.name}" creato. Copia l'API key ora — non sarà più visibile in chiaro.
          </div>
          <code className="wpai-key-value" style={{ display: "block", padding: 10, background: "var(--surface-sunken)", borderRadius: "var(--radius-sm)" }}>
            {result.api_key}
          </code>
          <button className="wpai-btn ghost" style={{ marginTop: 12 }} onClick={() => { setResult(null); setOpen(false); }}>
            Fatto
          </button>
        </>
      ) : (
        <form onSubmit={submit}>
          <div className="wpai-field">
            <label>Nome cliente</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required autoFocus />
          </div>
          <div className="wpai-field">
            <label>Origin consentiti (opzionale, separati da virgola)</label>
            <input value={origins} onChange={(e) => setOrigins(e.target.value)} placeholder="https://sito-cliente.it" />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="wpai-btn" type="submit" disabled={saving}>{saving ? "Creazione…" : "Crea"}</button>
            <button className="wpai-btn ghost" type="button" onClick={() => setOpen(false)}>Annulla</button>
          </div>
        </form>
      )}
    </div>
  );
}

function OperatorsPanel({ clientId }) {
  const [operators, setOperators] = useState(null);
  const [form, setForm] = useState({ email: "", password: "" });
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => adminApi.operators(clientId).then(setOperators), [clientId]);
  useEffect(() => { load(); }, [load]);

  const add = async (e) => {
    e.preventDefault();
    setAdding(true);
    try {
      await adminApi.createOperator(clientId, form.email, form.password);
      setForm({ email: "", password: "" });
      load();
    } finally {
      setAdding(false);
    }
  };

  const remove = async (id) => {
    await adminApi.deleteOperator(id);
    load();
  };

  return (
    <div className="wpai-card" style={{ marginTop: 16 }}>
      <div className="wpai-card-title" style={{ marginBottom: 12 }}><Users size={15} /> Operatori</div>
      {operators?.length > 0 && (
        <div className="wpai-kb-list" style={{ marginBottom: 14 }}>
          {operators.map((o) => (
            <div key={o.id} className="wpai-kb-row">
              <span className="wpai-kb-label">{o.email}</span>
              <button className="wpai-icon-btn" title="Rimuovi" onClick={() => remove(o.id)}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
      <form onSubmit={add} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
        <div className="wpai-field" style={{ flex: 1, marginBottom: 0 }}>
          <label>Email</label>
          <input type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} required />
        </div>
        <div className="wpai-field" style={{ flex: 1, marginBottom: 0 }}>
          <label>Password</label>
          <input type="password" minLength={8} value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} required />
        </div>
        <button className="wpai-btn" type="submit" disabled={adding}>Aggiungi</button>
      </form>
    </div>
  );
}

function PlanPicker({ client, plans, onChanged }) {
  const [saving, setSaving] = useState(false);

  const change = async (e) => {
    const planId = Number(e.target.value);
    setSaving(true);
    try {
      await adminApi.setClientPlan(client.id, planId);
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="wpai-card" style={{ marginTop: 16 }}>
      <div className="wpai-card-title" style={{ marginBottom: 12 }}><CreditCard size={15} /> Piano</div>
      <select value={client.plan_id || ""} onChange={change} disabled={saving || !plans}>
        {plans?.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} — {formatPrice(p.price_cents, p.currency)}/mese
          </option>
        ))}
      </select>
    </div>
  );
}

function CommercialActions({ client }) {
  const [days, setDays] = useState("7");
  const [coupon, setCoupon] = useState("");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);

  // every action lands at Stripe; our row only changes when the webhook arrives, so the
  // feedback says "richiesto", never "fatto"
  const run = async (name, fn) => {
    setBusy(name);
    setResult(null);
    try {
      await fn();
      setResult({ ok: true, text: "Richiesta inviata a Stripe. Lo stato si aggiorna appena arriva il webhook." });
    } catch (e) {
      setResult({
        ok: false,
        text: e?.status === 409
          ? "Stripe ha rifiutato l'operazione: verifica che il cliente abbia un abbonamento e che il codice esista."
          : e?.status === 503
            ? "Billing non configurato su questo ambiente."
            : `Operazione non riuscita${e?.status ? ` (errore ${e.status})` : ""}.`,
      });
    } finally {
      setBusy("");
    }
  };

  if (!client.billing_status || client.billing_status === "canceled") {
    return (
      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title" style={{ marginBottom: 8 }}><CreditCard size={15} /> Azioni commerciali</div>
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
          Nessun abbonamento attivo su cui agire.
        </p>
      </div>
    );
  }

  return (
    <div className="wpai-card" style={{ marginTop: 16 }}>
      <div className="wpai-card-title" style={{ marginBottom: 10 }}><CreditCard size={15} /> Azioni commerciali</div>
      {result && <p className={result.ok ? "wpai-success" : "wpai-error"}>{result.text}</p>}

      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "0 1 130px" }}>
          Proroga prova (giorni)
          <input type="number" min="1" max="90" value={days} onChange={(e) => setDays(e.target.value)} />
        </label>
        <button className="wpai-btn ghost" disabled={busy === "trial"}
                onClick={() => run("trial", () => adminApi.extendTrial(client.id, Number(days) || 0))}>
          {busy === "trial" ? "Invio…" : "Prolunga"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "1 1 160px" }}>
          Codice sconto Stripe
          <input value={coupon} onChange={(e) => setCoupon(e.target.value)} placeholder="NATALE20" />
        </label>
        <button className="wpai-btn ghost" disabled={busy === "discount" || !coupon.trim()}
                onClick={() => run("discount", () => adminApi.applyDiscount(client.id, coupon.trim()))}>
          {busy === "discount" ? "Invio…" : "Applica"}
        </button>
        <button className="wpai-btn ghost" disabled={busy === "undiscount"}
                onClick={() => run("undiscount", () => adminApi.removeDiscount(client.id))}>
          Rimuovi sconto
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="wpai-btn ghost" disabled={busy === "pause"}
                onClick={() => run("pause", () => adminApi.pauseSubscription(client.id, true))}>
          Sospendi addebiti
        </button>
        <button className="wpai-btn ghost" disabled={busy === "resume"}
                onClick={() => run("resume", () => adminApi.pauseSubscription(client.id, false))}>
          Riattiva addebiti
        </button>
        <button className="wpai-btn danger" disabled={busy === "cancel"}
                onClick={() => run("cancel", () => adminApi.cancelSubscription(client.id, true))}>
          Disdici a fine periodo
        </button>
        <button className="wpai-btn ghost" disabled={busy === "uncancel"}
                onClick={() => run("uncancel", () => adminApi.cancelSubscription(client.id, false))}>
          Annulla disdetta
        </button>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "10px 0 0" }}>
        I codici sconto si creano nella dashboard Stripe. La disdetta è sempre a fine periodo
        pagato, mai immediata. La sospensione ferma gli addebiti senza togliere il piano.
      </p>
    </div>
  );
}

function ClientDetail({ client, plans, onChanged }) {
  const [origins, setOrigins] = useState(client.allowed_origins || "");
  const [savingOrigins, setSavingOrigins] = useState(false);
  const [newKey, setNewKey] = useState(null);
  const [keyVisible, setKeyVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmingRotate, setConfirmingRotate] = useState(false);

  useEffect(() => {
    setOrigins(client.allowed_origins || "");
    setNewKey(null);
    setConfirmingRotate(false);
  }, [client.id, client.allowed_origins]);

  const saveOrigins = async () => {
    setSavingOrigins(true);
    try {
      await adminApi.setOrigins(client.id, origins);
      onChanged();
    } finally {
      setSavingOrigins(false);
    }
  };

  const rotate = async () => {
    const { api_key } = await adminApi.rotateKey(client.id);
    setNewKey(api_key);
    setKeyVisible(true);
    setConfirmingRotate(false);
  };

  const copy = async () => {
    await navigator.clipboard.writeText(newKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>{client.name}</h2>

      <div className="wpai-stat-grid" style={{ marginBottom: 20 }}>
        {[
          { label: "Conversazioni", value: client.conversations, Icon: MessageSquare },
          { label: "Operatori", value: client.operators, Icon: Users },
          { label: "Chunk KB", value: client.documents, Icon: FileText },
          { label: "Prodotti", value: client.products, Icon: Package },
        ].map((s) => (
          <div key={s.label} className="wpai-card wpai-stat-card">
            <div className="icon"><s.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{s.value}</div>
            <div className="label">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="wpai-card">
        <div className="wpai-card-title" style={{ marginBottom: 12 }}>API key</div>
        {newKey ? (
          <>
            <div className="wpai-key-row">
              <code className="wpai-key-value">{keyVisible ? newKey : "•".repeat(24) + newKey.slice(-4)}</code>
              <button className="wpai-icon-btn-outline" onClick={() => setKeyVisible((v) => !v)}>
                {keyVisible ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
              <button className="wpai-icon-btn-outline" onClick={copy}>
                {copied ? <Check size={15} color="var(--green)" /> : <Copy size={15} />}
              </button>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 10 }}>
              Nuova key generata — copiala ora, non sarà più recuperabile in chiaro dopo aver lasciato questa pagina.
            </p>
          </>
        ) : !confirmingRotate ? (
          <button className="wpai-btn ghost" onClick={() => setConfirmingRotate(true)}>
            <RefreshCw size={14} /> Rigenera API key
          </button>
        ) : (
          <div className="wpai-confirm">
            <p>La vecchia key smette di funzionare subito. Continuare?</p>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="wpai-btn danger" onClick={rotate}>Sì, rigenera</button>
              <button className="wpai-btn ghost" onClick={() => setConfirmingRotate(false)}>Annulla</button>
            </div>
          </div>
        )}
      </div>

      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title" style={{ marginBottom: 12 }}>Origin consentiti (CORS)</div>
        <div className="wpai-field">
          <input
            value={origins}
            onChange={(e) => setOrigins(e.target.value)}
            placeholder="https://sito-cliente.it (vuoto = nessuna restrizione)"
          />
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "6px 0 0" }}>
            Solo schema + dominio (es. <code>https://sito.it</code>), senza percorso. Eventuali path
            vengono rimossi automaticamente.
          </p>
        </div>
        <button className="wpai-btn" onClick={saveOrigins} disabled={savingOrigins}>
          {savingOrigins ? "Salvataggio…" : "Salva"}
        </button>
      </div>

      <PlanPicker client={client} plans={plans} onChanged={onChanged} />
      <CommercialActions client={client} />
      <OperatorsPanel clientId={client.id} />
    </div>
  );
}

function PlansView({ plans, onChanged }) {
  const [form, setForm] = useState({ name: "", price_cents: 0, chat_rate_limit: 30, ingest_rate_limit: 60, monthly_message_limit: 0 });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await adminApi.createPlan(form);
      setForm({ name: "", price_cents: 0, chat_rate_limit: 30, ingest_rate_limit: 60, monthly_message_limit: 0 });
      onChanged();
    } catch {
      setError("Nome piano già in uso.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Piani</h2>
      <div className="wpai-kb-list" style={{ marginBottom: 20 }}>
        {plans?.map((p) => (
          <div key={p.id} className="wpai-kb-row">
            <span className="wpai-kb-label">{p.name}</span>
            <span className="wpai-kb-count">{formatPrice(p.price_cents, p.currency)}/mese</span>
            <span className="wpai-kb-count">{p.chat_rate_limit} chat/min</span>
            <span className="wpai-kb-count">{p.monthly_message_limit ? `${p.monthly_message_limit} msg/mese` : "msg illimitati"}</span>
          </div>
        ))}
      </div>

      <div className="wpai-card">
        <div className="wpai-card-title" style={{ marginBottom: 12 }}>Nuovo piano</div>
        <form onSubmit={submit}>
          {error && <div className="wpai-error">{error}</div>}
          <div className="wpai-field">
            <label>Nome</label>
            <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} required />
          </div>
          <div className="wpai-field">
            <label>Prezzo (centesimi/mese, 0 = gratis)</label>
            <input
              type="number" min={0} value={form.price_cents}
              onChange={(e) => setForm((f) => ({ ...f, price_cents: Number(e.target.value) }))}
            />
          </div>
          <div className="wpai-field">
            <label>Limite chat (msg/min)</label>
            <input
              type="number" min={1} value={form.chat_rate_limit}
              onChange={(e) => setForm((f) => ({ ...f, chat_rate_limit: Number(e.target.value) }))}
            />
          </div>
          <div className="wpai-field">
            <label>Limite ingest (richieste/min)</label>
            <input
              type="number" min={1} value={form.ingest_rate_limit}
              onChange={(e) => setForm((f) => ({ ...f, ingest_rate_limit: Number(e.target.value) }))}
            />
          </div>
          <div className="wpai-field">
            <label>Quota mensile messaggi (0 = illimitato)</label>
            <input
              type="number" min={0} value={form.monthly_message_limit}
              onChange={(e) => setForm((f) => ({ ...f, monthly_message_limit: Number(e.target.value) }))}
            />
          </div>
          <button className="wpai-btn" type="submit" disabled={saving}>{saving ? "Creazione…" : "Crea piano"}</button>
        </form>
      </div>
    </div>
  );
}

function pct(x) {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
}

function OverviewView() {
  const [s, setS] = useState(null);
  useEffect(() => { adminApi.stats().then(setS); }, []);
  if (!s) return <Loading />;

  const cards = [
    { label: "Clienti", value: s.clients.total, Icon: Building2 },
    { label: "Conversazioni", value: s.conversations.total, Icon: MessageSquare },
    { label: "Risolte da AI", value: pct(s.ai.resolution_rate), Icon: Check },
    { label: "Latenza media", value: s.ai.avg_latency_ms ? `${s.ai.avg_latency_ms} ms` : "—", Icon: Activity },
    {
      label: "Feedback",
      value: (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 10, fontSize: 20 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <ThumbsUp size={16} strokeWidth={2.25} /> {s.feedback?.positive ?? 0}
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <ThumbsDown size={16} strokeWidth={2.25} /> {s.feedback?.negative ?? 0}
          </span>
        </span>
      ),
      Icon: Check,
    },
  ];
  const esc = s.escalations_by_trigger;
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Panoramica</h2>
      <div className="wpai-stat-grid">
        {cards.map((c) => (
          <div key={c.label} className="wpai-card wpai-stat-card">
            <div className="icon"><c.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{c.value}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>
      <div className="wpai-two-col">
        <div className="wpai-card">
          <div className="wpai-card-title">Conversazioni (ultimi 14 giorni)</div>
          <MiniBars data={s.volume_daily} xKey="date" yKey="conversations" />
        </div>
        <div className="wpai-card">
          <div className="wpai-card-title">Motivi di escalation</div>
          <Breakdown items={[
            { label: "Parola chiave", value: esc.keyword },
            { label: "Decisione AI", value: esc.model },
            { label: "AI non disponibile", value: esc.llm_down },
          ]} />
        </div>
      </div>
      <div className="wpai-two-col">
        <div className="wpai-card">
          <div className="wpai-card-title">Clienti per piano</div>
          <Breakdown items={Object.entries(s.clients.by_plan).map(([label, value]) => ({ label, value }))} />
        </div>
        <div className="wpai-card">
          <div className="wpai-card-title">Top clienti per volume</div>
          <table className="wpai-table">
            <tbody>
              {s.top_clients.map((t) => (
                <tr key={t.client_id}><td>{t.name}</td><td style={{ textAlign: "right" }}>{t.conversations}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function RevenueView() {
  const [data, setData] = useState(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    adminApi.revenue(days).then(setData).catch(() => setError("Impossibile caricare i ricavi."));
  }, [days]);

  if (error) return <div><h2 style={{ marginTop: 0 }}>Ricavi</h2><p className="wpai-error">{error}</p></div>;
  if (!data) return <Loading />;

  // with more than one currency in play no single total is meaningful, so amounts are shown
  // unformatted rather than labelled with a currency that would be wrong for some of them
  const money = (cents) => (data.mixed_currencies ? (cents / 100).toFixed(2) : formatPrice(cents, data.currency));
  const day = (value) => (value ? new Date(value).toLocaleDateString("it-IT") : "—");

  const cards = [
    { label: "MRR", value: money(data.mrr_cents), Icon: CreditCard },
    { label: "ARR", value: money(data.arr_cents), Icon: TrendingUp },
    { label: "Clienti paganti", value: data.paying_clients, Icon: Building2 },
    { label: "Ricavo medio", value: money(data.arpa_cents), Icon: Users },
    { label: "A rischio", value: money(data.at_risk_cents), Icon: AlertTriangle },
    { label: "In prova", value: money(data.trial_cents), Icon: Sparkles },
  ];

  const tables = [
    { key: "past_due", title: "Insoluti", rows: data.past_due, date: null,
      empty: "Nessun pagamento in sospeso." },
    { key: "trials_ending", title: "Prove in scadenza (7 giorni)", rows: data.trials_ending, date: "ends_at",
      empty: "Nessuna prova in scadenza." },
    { key: "scheduled_cancellations", title: "Disdette programmate", rows: data.scheduled_cancellations, date: "ends_at",
      empty: "Nessuna disdetta programmata." },
    { key: "recent_cancellations", title: `Disdette (${data.window_days} giorni)`, rows: data.recent_cancellations, date: "canceled_at",
      empty: "Nessuna disdetta nel periodo." },
  ];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ marginTop: 0, marginBottom: 0 }}>Ricavi</h2>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
          Periodo
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Periodo delle disdette">
            <option value={30}>30 giorni</option>
            <option value={90}>90 giorni</option>
            <option value={180}>180 giorni</option>
            <option value={365}>365 giorni</option>
          </select>
        </label>
      </div>

      {data.mixed_currencies && (
        <div className="wpai-callout warn" role="status" style={{ marginTop: 12 }}>
          <div>
            I piani usano valute diverse: gli importi sono sommati senza conversione e vanno letti
            come un ordine di grandezza, non come un totale contabile.
          </div>
        </div>
      )}

      <div className="wpai-stat-grid" style={{ marginTop: 12 }}>
        {cards.map((c) => (
          <div key={c.label} className="wpai-card wpai-stat-card">
            <div className="icon"><c.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{c.value}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "10px 0 0" }}>
        L'MRR conta solo gli abbonamenti attivi. Gli insoluti e le prove restano separati perché
        non sono ancora incassati. Le disdette sono un conteggio del periodo: senza uno storico
        della base clienti un tasso di churn sarebbe inventato.
      </p>

      <div className="wpai-two-col" style={{ marginTop: 16 }}>
        <div className="wpai-card">
          <div className="wpai-card-title">MRR per piano</div>
          <Breakdown items={Object.entries(data.by_plan).map(([label, v]) => ({ label, value: v.mrr_cents / 100 }))} />
        </div>
        <div className="wpai-card">
          <div className="wpai-card-title">Clienti paganti per piano</div>
          <Breakdown items={Object.entries(data.by_plan).map(([label, v]) => ({ label, value: v.clients }))} />
        </div>
      </div>

      {tables.map((t) => (
        <div className="wpai-card" style={{ marginTop: 16 }} key={t.key}>
          <div className="wpai-card-title">{t.title} <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>({t.rows.length})</span></div>
          {t.rows.length === 0 ? (
            <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>{t.empty}</p>
          ) : (
            <table className="wpai-table">
              <thead><tr><th>Cliente</th><th>Piano</th>{t.date && <th>Data</th>}<th style={{ textAlign: "right" }}>Valore/mese</th></tr></thead>
              <tbody>
                {t.rows.map((r) => (
                  <tr key={r.client_id}>
                    <td>{r.name}</td>
                    <td>{r.plan || "—"}</td>
                    {t.date && <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>{day(r[t.date])}</td>}
                    <td style={{ textAlign: "right" }}>{money(r.monthly_value_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}

function ModelPriceEditor({ prices, onChanged }) {
  const blank = { model: "", input_price_per_million: "", output_price_per_million: "", currency: "usd" };
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await adminApi.setModelPrice({
        model: form.model.trim(),
        input_price_per_million: Number(form.input_price_per_million) || 0,
        output_price_per_million: Number(form.output_price_per_million) || 0,
        currency: form.currency,
      });
      setForm(blank);
      onChanged();
    } catch (e) {
      // say which failure it was: a rejected value and a request the browser never sent are
      // very different problems, and "controlla i valori" sends you looking in the wrong place
      setError(
        e?.status === 400
          ? "Prezzo rifiutato: controlla il nome del modello e che i valori non siano negativi."
          : e?.status
            ? `Prezzo non salvato (errore ${e.status}).`
            : "Prezzo non salvato: il server non è raggiungibile dal browser.",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id) => {
    setError("");
    try {
      await adminApi.deleteModelPrice(id);
      onChanged();
    } catch {
      setError("Prezzo non rimosso. Riprova.");
    }
  };

  return (
    <div className="wpai-card" style={{ marginTop: 16 }}>
      <div className="wpai-card-title">Listino modelli</div>
      <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "4px 0 10px" }}>
        Prezzo <strong>per milione di token</strong>, esattamente come lo pubblica il provider
        (es. <code>0.152</code>). I decimali sono conservati. Un modello senza prezzo non viene
        considerato gratis: resta escluso dal totale e segnalato.
      </p>
      {error && <p className="wpai-error">{error}</p>}
      <form onSubmit={save} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "2 1 200px" }}>
          Modello
          <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })}
                 placeholder="@cf/meta/llama-3.1-8b-instruct" required />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "1 1 110px" }}>
          Input / M token
          <input type="number" min="0" step="any" value={form.input_price_per_million}
                 onChange={(e) => setForm({ ...form, input_price_per_million: e.target.value })} placeholder="0.152" />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "1 1 110px" }}>
          Output / M token
          <input type="number" min="0" step="any" value={form.output_price_per_million}
                 onChange={(e) => setForm({ ...form, output_price_per_million: e.target.value })} placeholder="0.287" />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: 12.5, flex: "0 1 90px" }}>
          Valuta
          <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
            <option value="usd">USD</option>
            <option value="eur">EUR</option>
          </select>
        </label>
        <button className="wpai-btn" type="submit" disabled={busy}>{busy ? "Salvataggio…" : "Salva"}</button>
      </form>

      {prices.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "10px 0 0" }}>
          Nessun prezzo impostato: finché il listino è vuoto i costi restano a zero e ogni modello
          usato compare fra quelli senza prezzo.
        </p>
      ) : (
        <table className="wpai-table" style={{ marginTop: 12 }}>
          <thead><tr><th>Modello</th><th style={{ textAlign: "right" }}>Input / M</th><th style={{ textAlign: "right" }}>Output / M</th><th>Valuta</th><th /></tr></thead>
          <tbody>
            {prices.map((p) => (
              <tr key={p.id}>
                <td>{p.model}</td>
                <td style={{ textAlign: "right" }}>{p.input_price_per_million}</td>
                <td style={{ textAlign: "right" }}>{p.output_price_per_million}</td>
                <td style={{ textTransform: "uppercase" }}>{p.currency}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="wpai-icon-btn" onClick={() => remove(p.id)} title={`Rimuovi ${p.model}`}>
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function CostsView() {
  const [data, setData] = useState(null);
  const [prices, setPrices] = useState([]);
  const [days, setDays] = useState(30);
  const [error, setError] = useState("");

  const loadPrices = useCallback(() => adminApi.modelPrices().then(setPrices).catch(() => setPrices([])), []);
  const load = useCallback(() => {
    setError("");
    adminApi.costs(days).then(setData).catch(() => setError("Impossibile caricare i costi."));
  }, [days]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadPrices(); }, [loadPrices]);

  const reload = () => { load(); loadPrices(); };

  if (error) return <div><h2 style={{ marginTop: 0 }}>Costi e margine</h2><p className="wpai-error">{error}</p></div>;
  if (!data) return <Loading />;

  // with a price list in one currency and plans in another, no symbol is right: show bare
  // numbers rather than label dollars as euros
  const money = (cents) => (data.mixed_currencies ? (cents / 100).toFixed(2) : formatPrice(Math.round(cents), data.currency));
  const tokens = (n) => new Intl.NumberFormat("it-IT").format(n);
  const gb = (bytes) => (bytes / 1024 ** 3).toFixed(2);

  const cards = [
    { label: "Costo AI / mese", value: money(data.monthly_cost_cents), Icon: Sparkles },
    { label: "Ricavo / mese", value: money(data.monthly_revenue_cents), Icon: CreditCard },
    { label: "Margine lordo", value: money(data.monthly_margin_cents), Icon: TrendingUp },
    { label: "Margine %", value: data.margin_pct === null ? "—" : `${data.margin_pct}%`, Icon: Activity },
  ];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ marginTop: 0, marginBottom: 0 }}>Costi e margine</h2>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
          Periodo
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Periodo di calcolo">
            <option value={7}>7 giorni</option>
            <option value={30}>30 giorni</option>
            <option value={90}>90 giorni</option>
          </select>
        </label>
      </div>

      {data.mixed_currencies && (
        <div className="wpai-callout warn" role="alert" style={{ marginTop: 12 }}>
          <div>
            Costi e ricavi sono in valute diverse ({data.currencies.join(", ").toUpperCase()}):
            gli importi non sono convertiti, quindi il margine non è un dato contabile finché il
            listino non usa la stessa valuta dei piani.
          </div>
        </div>
      )}

      {!data.storage_priced && data.storage_bytes > 0 && (
        <div className="wpai-callout warn" role="status" style={{ marginTop: 12 }}>
          <div>
            Storage non prezzato: {gb(data.storage_bytes)} GB archiviati non entrano nel totale.
            Imposta <code>STORAGE_PRICE_PER_GB_MONTH_MILLICENTS</code> per includerli.
          </div>
        </div>
      )}

      {data.embedding_estimated && (
        <div className="wpai-callout" role="status" style={{ marginTop: 12 }}>
          <div>
            Il costo degli embedding è <strong>stimato</strong>: il provider non riporta i token,
            quindi sono derivati dai caratteri inviati a {data.chars_per_token} caratteri per token.
          </div>
        </div>
      )}

      {data.unpriced_models.length > 0 && (
        <div className="wpai-callout warn" role="alert" style={{ marginTop: 12 }}>
          <div>
            Modelli senza prezzo, esclusi dai totali: <strong>{data.unpriced_models.join(", ")}</strong>.
            Finché mancano, il costo mostrato è più basso di quello reale.
          </div>
        </div>
      )}

      <div className="wpai-stat-grid" style={{ marginTop: 12 }}>
        {cards.map((c) => (
          <div key={c.label} className="wpai-card wpai-stat-card">
            <div className="icon"><c.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{c.value}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "10px 0 0" }}>
        Comprende inferenza, embedding (ingest e domande) e storage degli allegati. Restano fuori
        email e canali, quindi il margine è ancora un <strong>tetto</strong>. Il costo del periodo è
        riportato al mese per essere confrontabile con il ricavo; lo storage è già mensile e non
        viene riscalato.
      </p>

      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title">Per cliente <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>({data.clients.length})</span></div>
        {data.clients.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>
            Nessun consumo AI nel periodo.
          </p>
        ) : (
          <table className="wpai-table">
            <thead>
              <tr>
                <th>Cliente</th><th>Piano</th>
                <th style={{ textAlign: "right" }}>Turni</th>
                <th style={{ textAlign: "right" }}>Token in/out</th>
                <th style={{ textAlign: "right" }}>Storage</th>
                <th style={{ textAlign: "right" }}>Costo/mese</th>
                <th style={{ textAlign: "right" }}>Ricavo/mese</th>
                <th style={{ textAlign: "right" }}>Margine</th>
              </tr>
            </thead>
            <tbody>
              {data.clients.map((r) => (
                <tr key={r.client_id}>
                  <td>
                    {r.name}
                    {!r.fully_priced && (
                      <span className="wpai-badge warn" style={{ marginLeft: 6 }} title="Usa modelli senza prezzo">parziale</span>
                    )}
                  </td>
                  <td>{r.plan || "—"}</td>
                  <td style={{ textAlign: "right" }}>{tokens(r.turns)}</td>
                  <td style={{ textAlign: "right", color: "var(--text-muted)" }}>{tokens(r.tokens_in)} / {tokens(r.tokens_out)}</td>
                  <td style={{ textAlign: "right", color: "var(--text-muted)" }}>
                    {r.storage_bytes ? `${gb(r.storage_bytes)} GB` : "—"}
                  </td>
                  <td style={{ textAlign: "right" }} title={`Inferenza ${money(r.inference_cost_cents)} + embedding ${money(r.embedding_cost_cents)}`}>
                    {money(r.monthly_cost_cents)}
                  </td>
                  <td style={{ textAlign: "right" }}>{money(r.monthly_revenue_cents)}</td>
                  <td style={{ textAlign: "right", color: r.monthly_margin_cents < 0 ? "var(--red)" : "inherit" }}>
                    {money(r.monthly_margin_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <ModelPriceEditor prices={prices} onChanged={reload} />
    </div>
  );
}

function GrowthView({ onOpenClient }) {
  const [funnel, setFunnel] = useState(null);
  const [risk, setRisk] = useState(null);
  const [days, setDays] = useState(90);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    adminApi.activation(days).then(setFunnel).catch(() => setError("Impossibile caricare l'attivazione."));
  }, [days]);
  useEffect(() => { adminApi.atRisk(14).then(setRisk).catch(() => setRisk(null)); }, []);

  if (error) return <div><h2 style={{ marginTop: 0 }}>Crescita</h2><p className="wpai-error">{error}</p></div>;
  if (!funnel) return <Loading />;

  const day = (v) => (v ? new Date(v).toLocaleDateString("it-IT") : "—");
  const reachedLabel = { created: "Solo registrato", installed: "Plugin collegato", chatted: "Ha chattato" };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 style={{ marginTop: 0, marginBottom: 0 }}>Crescita</h2>
        <label style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
          Coorte
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Periodo della coorte">
            <option value={30}>30 giorni</option>
            <option value={90}>90 giorni</option>
            <option value={365}>365 giorni</option>
          </select>
        </label>
      </div>

      {funnel.undated_clients > 0 && (
        <div className="wpai-callout" role="status" style={{ marginTop: 12 }}>
          <div>
            {funnel.undated_clients} client{funnel.undated_clients === 1 ? "e" : "i"} senza data di
            registrazione (creati prima che il campo esistesse): esclusi dalla coorte invece di
            essere contati come mancate attivazioni.
          </div>
        </div>
      )}

      <div className="wpai-card" style={{ marginTop: 12 }}>
        <div className="wpai-card-title">
          Funnel di attivazione
          <span style={{ color: "var(--text-muted)", fontWeight: 500 }}> — {funnel.cohort} account</span>
        </div>
        {funnel.cohort === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>
            Nessun account registrato nel periodo.
          </p>
        ) : (
          <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
            {funnel.steps.map((s) => (
              <div key={s.key}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span>{s.label}</span>
                  <span><b>{s.clients}</b> <span style={{ color: "var(--text-muted)" }}>({s.pct}%)</span></span>
                </div>
                <div className="wpai-breakdown-track">
                  <div className="wpai-breakdown-fill" style={{ width: `${s.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
        {funnel.median_hours_to_activation !== null && (
          <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "12px 0 0" }}>
            Tempo mediano dalla registrazione alla prima risposta utile:{" "}
            <b>{funnel.median_hours_to_activation} ore</b>. Una conversazione a cui l'AI non ha mai
            risposto non conta come attivazione.
          </p>
        )}
      </div>

      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title">
          Bloccati nel funnel <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>({funnel.stuck.length})</span>
        </div>
        {funnel.stuck.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>Nessuno: tutti attivati.</p>
        ) : (
          <table className="wpai-table">
            <thead><tr><th>Cliente</th><th>Registrato</th><th>È arrivato a</th></tr></thead>
            <tbody>
              {funnel.stuck.map((r) => (
                <tr key={r.client_id}>
                  <td>
                    <button className="wpai-link-btn" onClick={() => onOpenClient(r.client_id)}>{r.name}</button>
                  </td>
                  <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>{day(r.created_at)}</td>
                  <td>{reachedLabel[r.reached] || r.reached}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title">
          Clienti a rischio
          <span style={{ color: "var(--text-muted)", fontWeight: 500 }}> — ultimi {risk?.window_days ?? 14} giorni ({risk?.clients?.length ?? 0})</span>
        </div>
        {!risk ? (
          <Loading inline />
        ) : risk.clients.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>Nessun segnale di rischio.</p>
        ) : (
          <table className="wpai-table">
            <thead><tr><th>Cliente</th><th>Piano</th><th>Conv. (prima → ora)</th><th>Ultima attività</th><th>Motivi</th></tr></thead>
            <tbody>
              {risk.clients.map((r) => (
                <tr key={r.client_id}>
                  <td>
                    <button className="wpai-link-btn" onClick={() => onOpenClient(r.client_id)}>{r.name}</button>
                  </td>
                  <td>{r.plan || "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{r.conversations_before} → {r.conversations_now}</td>
                  <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>{day(r.last_seen)}</td>
                  <td>
                    {r.reasons.map((reason) => (
                      <span key={reason} className="wpai-badge warn" style={{ marginRight: 4, display: "inline-block" }}>{reason}</span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p style={{ color: "var(--text-muted)", fontSize: 12, margin: "10px 0 0" }}>
          I motivi sono espliciti e non un punteggio: il calo d'uso è misurato sul periodo
          precedente <em>dello stesso cliente</em>, non rispetto agli altri.
        </p>
      </div>
    </div>
  );
}

function HealthView() {
  const [h, setH] = useState(null);
  const [emailResult, setEmailResult] = useState(null);
  const load = () => adminApi.health().then(setH);
  useEffect(() => { load(); }, []);
  if (!h) return <Loading />;

  const email = h.email || {};
  const rows = [
    ["Stato generale", h.status],
    ["Database", h.db],
    ["Worker ingest", h.worker_enabled ? "attivo" : "disattivo"],
    ["Coda ingest", `queued ${h.ingest_queue.queued} · processing ${h.ingest_queue.processing} · error ${h.ingest_queue.error}`],
    ["Migrazione", h.migration || "—"],
    ["Modello chat", h.models.chat],
    ["Modello embed", h.models.embed],
    ["Email", email.configured ? `configurato · ${email.provider} · from ${email.from}` : "NON configurato"],
    ["Versione", h.version],
  ];
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h2 style={{ marginTop: 0 }}>Stato del sistema</h2>
        <span className={"wpai-badge " + (h.status === "ok" ? "ok" : "warn")}>{h.status}</span>
        <button className="wpai-icon-btn" onClick={load} title="Aggiorna"><RefreshCw size={15} /></button>
      </div>
      <div className="wpai-card">
        <table className="wpai-table">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}><td style={{ color: "var(--text-muted)" }}>{k}</td><td>{v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="wpai-card" style={{ marginTop: 16 }}>
        <div className="wpai-card-title" style={{ marginBottom: 10 }}>Verifica email SMTP</div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const to = new FormData(e.target).get("to");
            setEmailResult({ pending: true });
            try {
              const r = await adminApi.testEmail(to);
              setEmailResult({ ok: r.sent, text: r.sent ? `${r.detail} a ${to}` : r.detail });
            } catch {
              setEmailResult({ ok: false, text: "Errore nella richiesta." });
            }
          }}
          style={{ display: "flex", gap: 10, alignItems: "flex-end" }}
        >
          <div className="wpai-field" style={{ flex: 1, margin: 0 }}>
            <label>Invia un'email di test a</label>
            <input name="to" type="email" placeholder="tua@email.it" required />
          </div>
          <button className="wpai-btn" type="submit" disabled={!email.configured} title={email.configured ? "" : "Configura prima SMTP su Railway"}>
            Invia test
          </button>
        </form>
        {emailResult && (
          <p style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0 0" }}>
            {emailResult.pending ? null : emailResult.ok ? (
              <Check size={14} color="var(--green)" />
            ) : (
              <X size={14} color="var(--red)" />
            )}
            {emailResult.pending ? "Invio in corso…" : emailResult.text}
          </p>
        )}
      </div>
    </div>
  );
}

function AuditView() {
  const [rows, setRows] = useState(null);
  useEffect(() => { adminApi.audit().then(setRows); }, []);
  if (!rows) return <Loading />;
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Log azioni</h2>
      <div className="wpai-card">
        <table className="wpai-table">
          <thead><tr><th>Quando</th><th>Chi</th><th>Azione</th><th>Target</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>{new Date(r.created_at).toLocaleString("it-IT")}</td>
                <td>{r.actor_type}: {r.actor_id}</td>
                <td>{r.action}</td>
                <td>{r.target}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>Nessuna azione registrata.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ProblematicView({ onOpenDebug }) {
  const [rows, setRows] = useState(null);
  const [ungrounded, setUngrounded] = useState(false);
  const load = (u) => adminApi.problematic(u).then(setRows);
  useEffect(() => { load(ungrounded); }, [ungrounded]);

  const KIND_LABEL = {
    escalated_model: "AI non ha trovato risposta nel contesto",
    escalated_llm_down: "AI non disponibile",
    answered_no_context: "Risposta senza contesto",
  };
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <h2 style={{ marginTop: 0 }}>Risposte problematiche</h2>
        <label style={{ fontSize: 12.5, color: "var(--text-muted)", display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={ungrounded} onChange={(e) => setUngrounded(e.target.checked)} />
          includi risposte senza contesto
        </label>
      </div>
      <div className="wpai-card">
        <table className="wpai-table">
          <thead><tr><th>Quando</th><th>Tipo</th><th>Chunk</th><th>Miglior distanza</th><th></th></tr></thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.id}>
                <td style={{ whiteSpace: "nowrap", color: "var(--text-muted)" }}>{new Date(r.created_at).toLocaleString("it-IT")}</td>
                <td>{KIND_LABEL[r.kind] || r.kind}</td>
                <td>{r.retrieved_count}</td>
                <td>{r.best_distance ?? "—"}</td>
                <td><button className="wpai-btn ghost" onClick={() => onOpenDebug(r.conversation_id)}><Search size={13} /> Debug</button></td>
              </tr>
            ))}
            {rows?.length === 0 && <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>Nessuna risposta problematica.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DebugView({ initialId }) {
  const [id, setId] = useState(initialId || "");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = async (convId) => {
    setError(""); setData(null);
    try {
      setData(await adminApi.conversationDebug(convId));
    } catch {
      setError("Conversazione non trovata.");
    }
  };
  useEffect(() => { if (initialId) load(initialId); }, [initialId]);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Debug conversazione</h2>
      <form
        onSubmit={(e) => { e.preventDefault(); if (id) load(id); }}
        className="wpai-card"
        style={{ display: "flex", gap: 10, alignItems: "flex-end" }}
      >
        <div className="wpai-field" style={{ flex: 1, margin: 0 }}>
          <label>ID conversazione</label>
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder="es. 42" />
        </div>
        <button className="wpai-btn" type="submit"><Search size={14} /> Apri</button>
      </form>

      {error && <div className="wpai-error" style={{ marginTop: 14 }}>{error}</div>}

      {data && (
        <div style={{ marginTop: 18 }}>
          <div className="wpai-card">
            <div className="wpai-card-title">
              Conversazione #{data.conversation.id} · stato {data.conversation.status} · cliente {data.conversation.client_id}
            </div>
            <div className="wpai-thread">
              {data.messages.map((m) => (
                <div key={m.id} className={"wpai-msg wpai-msg-" + m.role}>
                  <span className="wpai-msg-role">{m.role}</span>
                  <span>{m.content}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="wpai-card" style={{ marginTop: 16 }}>
            <div className="wpai-card-title">Turni AI</div>
            {data.ai_turns.length === 0 && <p style={{ color: "var(--text-muted)" }}>Nessun turno AI.</p>}
            {data.ai_turns.map((t) => (
              <div key={t.id} className="wpai-ai-turn">
                <div className="wpai-ai-turn-head">
                  <span className={"wpai-badge " + (t.outcome === "answered" ? "ok" : "warn")}>{t.outcome}</span>
                  <span className="dim">{t.model || "—"}</span>
                  <span className="dim">{t.latency_ms} ms</span>
                  <span className="dim">{t.tokens_prompt}+{t.tokens_completion} token</span>
                </div>
                {t.retrieved.length > 0 ? (
                  <table className="wpai-table" style={{ marginTop: 8 }}>
                    <thead><tr><th>Fonte</th><th>Riferimento</th><th>Distanza</th><th>Usato</th></tr></thead>
                    <tbody>
                      {t.retrieved.map((c, i) => (
                        <tr key={i} style={{ opacity: c.selected ? 1 : 0.5 }}>
                          <td>{c.source}</td>
                          <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.source_ref}</td>
                          <td>{c.distance}</td>
                          <td>{c.selected ? <Check size={14} color="var(--green)" /> : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p style={{ color: "var(--text-muted)", fontSize: 12.5, marginTop: 6 }}>Nessun contesto recuperato.</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ClientsView({ clients, plans, selected, onSelect, onReload, onReloadPlans }) {
  const [search, setSearch] = useState("");
  const [planFilter, setPlanFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [showNew, setShowNew] = useState(false);

  // a selected client takes over the whole view (detail + back)
  if (selected) {
    return (
      <div>
        <button className="wpai-btn ghost" onClick={() => onSelect(null)} style={{ marginBottom: 16 }}>
          ← Torna alla lista
        </button>
        <ClientDetail client={selected} plans={plans} onChanged={() => { onReload(); onReloadPlans(); }} />
      </div>
    );
  }

  if (!clients) return <Loading />;

  const q = search.trim().toLowerCase();
  const filtered = clients.filter((c) => {
    if (q && !(`${c.name} ${c.allowed_origins || ""}`.toLowerCase().includes(q))) return false;
    if (planFilter !== "all" && String(c.plan_id) !== planFilter) return false;
    if (statusFilter !== "all" && c.billing_status !== statusFilter) return false;
    return true;
  });
  const statuses = [...new Set(clients.map((c) => c.billing_status).filter(Boolean))];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Clienti <span style={{ color: "var(--text-muted)", fontWeight: 500 }}>({filtered.length})</span></h2>
        <button className="wpai-btn" onClick={() => setShowNew((v) => !v)}>
          <Plus size={15} /> Nuovo cliente
        </button>
      </div>

      {showNew && <NewClientForm onCreated={() => { onReload(); setShowNew(false); }} />}

      <div className="wpai-filters">
        <div className="wpai-search">
          <Search size={15} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Cerca per nome o sito…"
          />
        </div>
        <select value={planFilter} onChange={(e) => setPlanFilter(e.target.value)}>
          <option value="all">Tutti i piani</option>
          {plans?.map((p) => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
        </select>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">Tutti gli stati</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <div className="wpai-card" style={{ marginTop: 14, padding: 0, overflow: "hidden" }}>
        <table className="wpai-table wpai-table-rows">
          <thead>
            <tr><th>Nome</th><th>Piano</th><th>Stato</th><th>Sito / Origin</th><th style={{ textAlign: "right" }}>Conv.</th></tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.id} className="wpai-row-click" onClick={() => onSelect(c)}>
                <td style={{ fontWeight: 600 }}>{c.name}</td>
                <td>{c.plan_name || "—"}</td>
                <td><span className={"wpai-badge " + (c.billing_status === "active" || c.billing_status === "trialing" ? "ok" : "warn")}>{c.billing_status}</span></td>
                <td style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--text-muted)" }}>{c.allowed_origins || "—"}</td>
                <td style={{ textAlign: "right" }}>{c.conversations}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={5} style={{ color: "var(--text-muted)", textAlign: "center", padding: 24 }}>Nessun cliente trovato.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Dashboard() {
  const [clients, setClients] = useState(null);
  const [plans, setPlans] = useState(null);
  const [selected, setSelected] = useState(null);
  const [view, setView] = useState("overview"); // overview | revenue | growth | costs | clients | plans | health | audit | problematic | debug
  const [debugId, setDebugId] = useState(null);
  const [reembedResult, setReembedResult] = useState(null);

  const openDebug = (convId) => { setDebugId(convId); setView("debug"); };
  // the growth tables are worklists: clicking a name has to land on that client's detail
  const openClient = (clientId) => {
    const found = (clients || []).find((c) => c.id === clientId);
    if (found) { setSelected(found); setView("clients"); }
  };

  const load = useCallback(() => adminApi.clients().then((list) => {
    setClients(list);
    setSelected((current) => {
      if (!current) return current;
      return list.find((c) => c.id === current.id) || current;
    });
  }), []);
  const loadPlans = useCallback(() => adminApi.plans().then(setPlans), []);

  useEffect(() => { load(); loadPlans(); }, [load, loadPlans]);

  const runReembed = async () => {
    setReembedResult("in corso…");
    const r = await adminApi.reembed();
    setReembedResult(`Ri-embeddati ${r.reembedded.chunks} chunk e ${r.reembedded.products} prodotti. Rimanenti: ${r.remaining.chunks + r.remaining.products}.`);
  };

  return (
    <div className="wpai-app">
      <nav className="wpai-sidebar">
        <div className="wpai-brand">
          <div className="wpai-brand-mark" style={{ background: "var(--brand-mark)" }} />
          <div className="wpai-brand-name"><Shield size={13} style={{ verticalAlign: -2, marginRight: 4 }} />Superadmin</div>
        </div>
        <div className="wpai-nav">
          <button className={"wpai-nav-item" + (view === "overview" ? " active" : "")} onClick={() => setView("overview")}>
            <LayoutDashboard size={16} strokeWidth={2.25} /> Panoramica
          </button>
          <button className={"wpai-nav-item" + (view === "clients" ? " active" : "")} onClick={() => setView("clients")}>
            <Building2 size={16} strokeWidth={2.25} /> Clienti
          </button>
          <button className={"wpai-nav-item" + (view === "revenue" ? " active" : "")} onClick={() => setView("revenue")}>
            <TrendingUp size={16} strokeWidth={2.25} /> Ricavi
          </button>
          <button className={"wpai-nav-item" + (view === "growth" ? " active" : "")} onClick={() => setView("growth")}>
            <Users size={16} strokeWidth={2.25} /> Crescita
          </button>
          <button className={"wpai-nav-item" + (view === "costs" ? " active" : "")} onClick={() => setView("costs")}>
            <Sparkles size={16} strokeWidth={2.25} /> Costi e margine
          </button>
          <button className={"wpai-nav-item" + (view === "plans" ? " active" : "")} onClick={() => setView("plans")}>
            <CreditCard size={16} strokeWidth={2.25} /> Piani
          </button>
          <button className={"wpai-nav-item" + (view === "problematic" ? " active" : "")} onClick={() => setView("problematic")}>
            <AlertTriangle size={16} strokeWidth={2.25} /> Problematiche
          </button>
          <button className={"wpai-nav-item" + (view === "debug" ? " active" : "")} onClick={() => setView("debug")}>
            <Search size={16} strokeWidth={2.25} /> Debug
          </button>
          <button className={"wpai-nav-item" + (view === "audit" ? " active" : "")} onClick={() => setView("audit")}>
            <ScrollText size={16} strokeWidth={2.25} /> Log azioni
          </button>
          <button className={"wpai-nav-item" + (view === "health" ? " active" : "")} onClick={() => setView("health")}>
            <Activity size={16} strokeWidth={2.25} /> Sistema
          </button>
        </div>
        <div style={{ marginTop: "auto" }}>
          <div style={{ marginBottom: 12 }}><ThemeToggle /></div>
          <button
            className="wpai-btn ghost"
            style={{ marginBottom: 10 }}
            onClick={runReembed}
            title="Ricalcola gli embedding mancanti (dopo un cambio modello)"
          >
            <Sparkles size={14} /> Ri-embedding
          </button>
          {reembedResult && <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "0 0 10px" }}>{reembedResult}</p>}
          <button className="wpai-icon-btn" onClick={() => { clearAdminKey(); window.location.reload(); }} style={{ alignSelf: "flex-start" }}>
            Esci
          </button>
        </div>
      </nav>
      <main className="wpai-main">
        {view === "overview" && <OverviewView />}
        {view === "clients" && (
          <ClientsView
            clients={clients}
            plans={plans}
            selected={selected}
            onSelect={setSelected}
            onReload={load}
            onReloadPlans={loadPlans}
          />
        )}
        {view === "revenue" && <RevenueView />}
        {view === "growth" && <GrowthView onOpenClient={openClient} />}
        {view === "costs" && <CostsView />}
        {view === "plans" && <PlansView plans={plans} onChanged={loadPlans} />}
        {view === "problematic" && <ProblematicView onOpenDebug={openDebug} />}
        {view === "debug" && <DebugView initialId={debugId} />}
        {view === "audit" && <AuditView />}
        {view === "health" && <HealthView />}
      </main>
    </div>
  );
}

export default function Admin() {
  const [key, setKey] = useState(getAdminKey());
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  if (!key) {
    return (
      <div className="wpai-login">
        <div className="wpai-login-card">
          <div className="wpai-brand"><div className="wpai-brand-mark" /><div className="wpai-brand-name">Superadmin</div></div>
          <h1>Accesso amministratore</h1>
          <p className="sub">Gestione client, operatori e chiavi API.</p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const value = new FormData(e.target).get("admin_key");
              setChecking(true);
              setError("");
              try {
                setAdminKey(value);
                await adminApi.ping();
                setKey(value);
              } catch {
                clearAdminKey();
                setError("Chiave non valida.");
              } finally {
                setChecking(false);
              }
            }}
          >
            {error && <div className="wpai-error">{error}</div>}
            <div className="wpai-field">
              <label htmlFor="wpai-admin-key">Admin API key</label>
              <input id="wpai-admin-key" name="admin_key" type="password" autoFocus required />
            </div>
            <button className="wpai-btn full" type="submit" disabled={checking}>
              {checking ? "Verifica…" : "Entra"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return <Dashboard />;
}

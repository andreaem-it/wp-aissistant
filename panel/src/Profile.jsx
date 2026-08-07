import { useEffect, useState } from "react";
import { Eye, EyeOff, Copy, Check, Circle, RefreshCw, KeyRound, CreditCard, User, Bell } from "lucide-react";
import { api } from "./api.js";
import Loading from "./Loading.jsx";

function NameCard({ me }) {
  const [name, setName] = useState(me.name || "");
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setStatus(null);
    try {
      await api.setName(name.trim());
      setStatus("saved");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="wpai-card" style={{ marginBottom: 16 }}>
      <div className="wpai-card-head">
        <div className="wpai-card-icon"><User size={16} strokeWidth={2.25} /></div>
        <div>
          <div className="wpai-card-title">Nome operatore</div>
          <div className="wpai-card-sub">Mostrato ai visitatori (es. "{name || "Mario"} sta scrivendo…"). Se vuoto si usa l'email.</div>
        </div>
      </div>
      <form onSubmit={submit} style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <input value={name} onChange={(e) => { setName(e.target.value); setStatus(null); }} placeholder="Es. Giulia" style={{ flex: 1 }} />
        <button className="wpai-btn" type="submit" disabled={saving}>{saving ? "Salvataggio…" : "Salva"}</button>
      </form>
      {status === "saved" && <div className="wpai-success" style={{ marginTop: 10, marginBottom: 0 }}>Nome aggiornato.</div>}
    </div>
  );
}

function OnboardingCard() {
  const [status, setStatus] = useState(null);
  useEffect(() => { api.onboardingStatus().then(setStatus).catch(() => setStatus(null)); }, []);
  if (!status || status.complete) return null;
  return (
    <div className="wpai-card" style={{ marginBottom: 16 }}>
      <div className="wpai-card-title">Completa l'attivazione — {status.completed_steps}/{status.total_steps}</div>
      <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "6px 0 12px" }}>
        Collega il plugin, sincronizza i contenuti e prova una conversazione prima di pubblicare il widget.
      </p>
      <div style={{ display: "grid", gap: 8 }}>
        {status.steps.map((step) => (
          <div key={step.key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
            {step.complete ? <Check size={16} color="var(--green)" /> : <Circle size={16} color="var(--text-faint)" />}
            <span style={{ color: step.complete ? "var(--text-muted)" : "var(--text)" }}>{step.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const formatDate = (value) => (value ? new Date(value).toLocaleDateString("it-IT") : "");

/** What the customer needs to know and do about their subscription, or null when all is well. */
function billingNotice(status, usage) {
  const on = formatDate(usage?.subscription_expires_at);
  if (status === "past_due") {
    return {
      tone: "danger",
      text: "Non siamo riusciti ad addebitare l'ultimo pagamento. Il servizio resta attivo mentre riproviamo: aggiorna il metodo di pagamento per non perderlo.",
    };
  }
  if (status === "canceled") {
    return { tone: "warn", text: "L'abbonamento è terminato: l'account usa ora i limiti del piano Free." };
  }
  if (usage?.cancel_at_period_end) {
    return {
      tone: "warn",
      text: on
        ? `Disdetta registrata: il piano resta attivo fino al ${on}, poi l'account passa al piano Free.`
        : "Disdetta registrata: alla fine del periodo pagato l'account passa al piano Free.",
    };
  }
  if (status === "trialing") {
    return { tone: "", text: on ? `Prova gratuita attiva fino al ${on}.` : "Prova gratuita attiva." };
  }
  return null;
}

function BillingCard({ me }) {
  const [plans, setPlans] = useState([]);
  const [busy, setBusy] = useState(null);
  const [usage, setUsage] = useState(null);
  const [billingInterval, setBillingInterval] = useState("month");
  const [error, setError] = useState("");

  useEffect(() => {
    api.plans().then(setPlans).catch(() => setPlans([]));
    api.usage().then(setUsage).catch(() => setUsage(null));
  }, []);

  const upgrade = async (planId) => {
    setBusy(planId);
    setError("");
    try {
      const { checkout_url } = await api.checkout(planId, billingInterval);
      window.location.href = checkout_url;
    } catch {
      setBusy(null);
      setError("Il pagamento non è al momento disponibile. Riprova più tardi.");
    }
  };

  const openPortal = async () => {
    setBusy("portal");
    setError("");
    try {
      const { portal_url } = await api.billingPortal();
      window.location.href = portal_url;
    } catch (e) {
      setBusy(null);
      // 409 = this tenant never checked out, so Stripe has nothing to show them
      setError(
        e?.status === 409
          ? "Non hai ancora un abbonamento da gestire. Attiva prima un piano."
          : "Il portale di fatturazione non è raggiungibile. Riprova più tardi.",
      );
    }
  };

  const status = usage?.billing_status || me.billing_status || "";
  const notice = billingNotice(status, usage);
  const others = plans.filter((p) => p.id !== me.plan_id && p.purchasable);

  return (
    <div className="wpai-card" style={{ marginTop: 16 }}>
      <div className="wpai-card-head">
        <div className="wpai-card-icon"><CreditCard size={16} strokeWidth={2.25} /></div>
        <div>
          <div className="wpai-card-title">Piano — {me.plan_name || "—"}</div>
          <div className="wpai-card-sub">Stato abbonamento: {status || "—"}</div>
        </div>
      </div>

      {notice && (
        <div
          className={"wpai-callout" + (notice.tone ? ` ${notice.tone}` : "")}
          role={notice.tone === "danger" ? "alert" : "status"}
          style={{ marginTop: 12 }}
        >
          <div>{notice.text}</div>
        </div>
      )}

      {error && <p className="wpai-error" style={{ marginTop: 12 }}>{error}</p>}

      <div style={{ marginTop: 12 }}>
        <button className="wpai-btn" onClick={openPortal} disabled={busy === "portal"}>
          {busy === "portal" ? "Apertura…" : "Gestisci abbonamento e fatture"}
        </button>
        <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "6px 0 0" }}>
          Metodo di pagamento, fatture, cambio piano e disdetta sul portale sicuro di Stripe.
        </p>
      </div>

      {usage && (
        <div style={{ marginTop: 12 }}>
          {usage.limit ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                <span>Messaggi questo mese</span>
                <span><b>{usage.used}</b> / {usage.limit} <span style={{ color: "var(--text-muted)" }}>({usage.remaining} rimasti)</span></span>
              </div>
              <div className="wpai-breakdown-track">
                <div className="wpai-breakdown-fill" style={{ width: `${Math.min(100, (usage.used / usage.limit) * 100)}%`, background: usage.used >= usage.limit ? "var(--amber)" : "var(--primary)" }} />
              </div>
            </>
          ) : (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Messaggi questo mese: <b>{usage.used}</b> (nessun limite)</div>
          )}
        </div>
      )}

      {others.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginTop: 6 }}>
          Nessun altro piano disponibile al momento.
        </p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
          <select value={billingInterval} onChange={(e) => setBillingInterval(e.target.value)} aria-label="Periodicità fatturazione">
            <option value="month">Mensile</option>
            <option value="year">Annuale — 2 mesi gratis</option>
          </select>
          {others.map((p) => (
            <div key={p.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span>
                <strong>{p.name}</strong> — {billingInterval === "year"
                  ? `${(p.yearly_price_cents / 100).toFixed(2)} ${p.currency.toUpperCase()}/anno`
                  : `${(p.price_cents / 100).toFixed(2)} ${p.currency.toUpperCase()}/mese`}
              </span>
              <button className="wpai-btn" onClick={() => upgrade(p.id)} disabled={busy === p.id}>
                {busy === p.id ? "Reindirizzamento…" : "Passa a questo piano"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ApiKeyCard({ me, onRotated }) {
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [rotating, setRotating] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(me.api_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const rotate = async () => {
    setRotating(true);
    try {
      const { api_key } = await api.rotateKey();
      onRotated(api_key);
      setConfirming(false);
      setVisible(true);
    } finally {
      setRotating(false);
    }
  };

  const masked = "•".repeat(24) + me.api_key.slice(-4);

  return (
    <div className="wpai-card" style={{ marginBottom: 16 }}>
      <div className="wpai-card-head">
        <div className="wpai-card-icon"><KeyRound size={16} strokeWidth={2.25} /></div>
        <div>
          <div className="wpai-card-title">API Key — {me.client_name}</div>
          <div className="wpai-card-sub">Usala nelle impostazioni del plugin WordPress per collegare il tuo sito.</div>
        </div>
      </div>

      <div className="wpai-key-row">
        <code className="wpai-key-value">{visible ? me.api_key : masked}</code>
        <button className="wpai-icon-btn-outline" onClick={() => setVisible((v) => !v)} title={visible ? "Nascondi" : "Mostra"}>
          {visible ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
        <button className="wpai-icon-btn-outline" onClick={copy} title="Copia">
          {copied ? <Check size={15} color="var(--green)" /> : <Copy size={15} />}
        </button>
      </div>

      {!confirming ? (
        <button className="wpai-btn ghost" style={{ marginTop: 14 }} onClick={() => setConfirming(true)}>
          <RefreshCw size={14} /> Rigenera API key
        </button>
      ) : (
        <div className="wpai-confirm">
          <p>
            La vecchia key smetterà di funzionare subito — il widget sul sito dovrà essere
            riconfigurato con quella nuova. Continuare?
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="wpai-btn danger" onClick={rotate} disabled={rotating}>
              {rotating ? "Rigenerazione…" : "Sì, rigenera"}
            </button>
            <button className="wpai-btn ghost" onClick={() => setConfirming(false)}>Annulla</button>
          </div>
        </div>
      )}
    </div>
  );
}

function PasswordCard() {
  const [form, setForm] = useState({ current_password: "", new_password: "", confirm: "" });
  const [status, setStatus] = useState(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setStatus(null);
    if (form.new_password.length < 8) {
      setStatus({ kind: "error", text: "La nuova password deve avere almeno 8 caratteri." });
      return;
    }
    if (form.new_password !== form.confirm) {
      setStatus({ kind: "error", text: "Le password non coincidono." });
      return;
    }
    setSaving(true);
    try {
      await api.changePassword(form.current_password, form.new_password);
      setStatus({ kind: "success", text: "Password aggiornata." });
      setForm({ current_password: "", new_password: "", confirm: "" });
    } catch {
      setStatus({ kind: "error", text: "Password attuale non corretta." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title" style={{ marginBottom: 14 }}>Cambia password</div>
      <form onSubmit={submit}>
        {status && <div className={status.kind === "error" ? "wpai-error" : "wpai-success"}>{status.text}</div>}
        <div className="wpai-field">
          <label>Password attuale</label>
          <input
            type="password"
            value={form.current_password}
            onChange={(e) => setForm((f) => ({ ...f, current_password: e.target.value }))}
            required
          />
        </div>
        <div className="wpai-field">
          <label>Nuova password</label>
          <input
            type="password"
            value={form.new_password}
            onChange={(e) => setForm((f) => ({ ...f, new_password: e.target.value }))}
            minLength={8}
            required
          />
        </div>
        <div className="wpai-field">
          <label>Conferma nuova password</label>
          <input
            type="password"
            value={form.confirm}
            onChange={(e) => setForm((f) => ({ ...f, confirm: e.target.value }))}
            minLength={8}
            required
          />
        </div>
        <button className="wpai-btn" type="submit" disabled={saving}>
          {saving ? "Salvataggio…" : "Aggiorna password"}
        </button>
      </form>
    </div>
  );
}

function base64Key(value) {
  const raw = atob((value + "=".repeat((4 - value.length % 4) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

function PushCard() {
  const [config, setConfig] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [deviceEnabled, setDeviceEnabled] = useState(false);
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  useEffect(() => { api.pushConfig().then(setConfig).catch(() => setConfig(null)); }, []);
  useEffect(() => {
    if (supported) navigator.serviceWorker.ready.then((registration) => registration.pushManager.getSubscription()).then((subscription) => setDeviceEnabled(Boolean(subscription))).catch(() => {});
  }, [supported]);
  const enable = async () => {
    setBusy(true); setMessage("");
    try {
      if (await Notification.requestPermission() !== "granted") { setMessage("Permesso notifiche non concesso."); return; }
      const registration = await navigator.serviceWorker.ready;
      const current = await registration.pushManager.getSubscription();
      const subscription = current || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64Key(config.public_key) });
      await api.savePushSubscription({ ...subscription.toJSON(), preferences: config.preferences });
      setConfig((value) => ({ ...value, subscriptions: 1 }));
      setDeviceEnabled(true);
      setMessage("Notifiche attivate su questo dispositivo.");
    } catch { setMessage("Impossibile attivare le notifiche su questo dispositivo."); }
    finally { setBusy(false); }
  };
  const disable = async () => {
    setBusy(true); setMessage("");
    try {
      const subscription = await (await navigator.serviceWorker.ready).pushManager.getSubscription();
      if (subscription) { await api.deletePushSubscription(subscription.endpoint); await subscription.unsubscribe(); }
      setConfig((value) => ({ ...value, subscriptions: 0 }));
      setDeviceEnabled(false);
      setMessage("Notifiche disattivate su questo dispositivo.");
    } finally { setBusy(false); }
  };
  const preference = async (name, checked) => {
    const preferences = { ...config.preferences, [name]: checked };
    setConfig((value) => ({ ...value, preferences }));
    await api.updatePushPreferences(preferences).catch(() => {});
  };
  if (!config) return null;
  const labels = { escalations: "Nuove escalation", assignments: "Conversazioni assegnate", mentions: "Menzioni nelle note", sla_breaches: "Violazioni SLA" };
  return <div className="wpai-card" style={{ marginBottom: 16 }}>
    <div className="wpai-card-head"><div className="wpai-card-icon"><Bell size={16} /></div><div><div className="wpai-card-title">Notifiche push</div><div className="wpai-card-sub">Ricevi avvisi anche quando il panel non è aperto.</div></div></div>
    {!supported && <p className="wpai-error">Questo browser non supporta le notifiche push.</p>}
    {supported && !config.configured && <p className="wpai-error">Le notifiche non sono ancora configurate sul server.</p>}
    {supported && config.configured && <><div style={{ display: "grid", gap: 8, margin: "14px 0" }}>{Object.entries(labels).map(([key, label]) => <label key={key} style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={config.preferences[key]} onChange={(e) => preference(key, e.target.checked)} /> {label}</label>)}</div><button className="wpai-btn" onClick={deviceEnabled ? disable : enable} disabled={busy}>{busy ? "Attendi…" : deviceEnabled ? "Disattiva su questo dispositivo" : "Attiva notifiche"}</button></>}
    {message && <div className="wpai-success" style={{ marginTop: 10, marginBottom: 0 }}>{message}</div>}
  </div>;
}

export default function Profile() {
  const [me, setMe] = useState(null);

  useEffect(() => {
    api.me().then(setMe);
  }, []);

  if (!me) return <Loading />;

  return (
    <div style={{ maxWidth: 720 }}>
      <h1 className="wpai-page-title">Profilo</h1>
      <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginTop: -14, marginBottom: 20 }}>{me.email}</p>
      <OnboardingCard />
      <NameCard me={me} />
      <PushCard />
      <ApiKeyCard me={me} onRotated={(api_key) => setMe((m) => ({ ...m, api_key }))} />
      <BillingCard me={me} />
      <PasswordCard />
    </div>
  );
}

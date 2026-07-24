import { useEffect, useState } from "react";
import { Eye, EyeOff, Copy, Check, RefreshCw, KeyRound } from "lucide-react";
import { api } from "./api.js";

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

export default function Profile() {
  const [me, setMe] = useState(null);

  useEffect(() => {
    api.me().then(setMe);
  }, []);

  if (!me) return <p style={{ color: "var(--text-muted)" }}>Caricamento…</p>;

  return (
    <div>
      <h1 className="wpai-page-title">Profilo</h1>
      <p style={{ color: "var(--text-muted)", fontSize: 13.5, marginTop: -14, marginBottom: 20 }}>{me.email}</p>
      <ApiKeyCard me={me} onRotated={(api_key) => setMe((m) => ({ ...m, api_key }))} />
      <PasswordCard />
    </div>
  );
}

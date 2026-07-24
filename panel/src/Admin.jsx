import { useEffect, useState } from "react";
import {
  Shield, Building2, Plus, Eye, EyeOff, Copy, Check, RefreshCw,
  Trash2, MessageSquare, Users, FileText, Package, Sparkles,
} from "lucide-react";
import { getAdminKey, setAdminKey, clearAdminKey, adminApi } from "./adminApi.js";

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

  const load = () => adminApi.operators(clientId).then(setOperators);
  useEffect(() => { load(); }, [clientId]);

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

function ClientDetail({ client, onChanged }) {
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
  }, [client.id]);

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
        </div>
        <button className="wpai-btn" onClick={saveOrigins} disabled={savingOrigins}>
          {savingOrigins ? "Salvataggio…" : "Salva"}
        </button>
      </div>

      <OperatorsPanel clientId={client.id} />
    </div>
  );
}

function Dashboard() {
  const [clients, setClients] = useState(null);
  const [selected, setSelected] = useState(null);
  const [reembedResult, setReembedResult] = useState(null);

  const load = () => adminApi.clients().then((list) => {
    setClients(list);
    if (selected) {
      const fresh = list.find((c) => c.id === selected.id);
      if (fresh) setSelected(fresh);
    }
  });

  useEffect(() => { load(); }, []);

  const runReembed = async () => {
    setReembedResult("in corso…");
    const r = await adminApi.reembed();
    setReembedResult(`Ri-embeddati ${r.reembedded.chunks} chunk e ${r.reembedded.products} prodotti. Rimanenti: ${r.remaining.chunks + r.remaining.products}.`);
  };

  return (
    <div className="wpai-app">
      <nav className="wpai-sidebar">
        <div className="wpai-brand">
          <div className="wpai-brand-mark" style={{ background: "linear-gradient(135deg, #16161f, #4a4a5a)" }} />
          <div className="wpai-brand-name"><Shield size={13} style={{ verticalAlign: -2, marginRight: 4 }} />Superadmin</div>
        </div>
        <div className="wpai-nav" style={{ flex: 1, overflowY: "auto" }}>
          {clients?.map((c) => (
            <button
              key={c.id}
              className={"wpai-nav-item" + (selected?.id === c.id ? " active" : "")}
              onClick={() => setSelected(c)}
            >
              <Building2 size={16} strokeWidth={2.25} />
              {c.name}
            </button>
          ))}
        </div>
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
      </nav>
      <main className="wpai-main">
        <NewClientForm onCreated={load} />
        <div style={{ marginTop: 20 }}>
          {selected ? (
            <ClientDetail client={selected} onChanged={load} />
          ) : (
            <div className="wpai-empty">
              <Building2 size={28} strokeWidth={1.5} />
              <p>Seleziona un cliente dalla sidebar, o creane uno nuovo.</p>
            </div>
          )}
        </div>
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

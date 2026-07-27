import { useEffect, useState } from "react";
import { Plus, Trash2, MessageSquareText, ListChecks, ShieldX } from "lucide-react";
import { api } from "./api.js";

function GdprCard() {
  const [email, setEmail] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const erase = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    if (!window.confirm(`Eliminare definitivamente TUTTE le conversazioni lasciate da ${email}? Non è reversibile.`)) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api.gdprErase(email.trim());
      setResult(`Eliminate ${r.deleted} conversazioni per ${email}.`);
      setEmail("");
    } catch {
      setResult("Errore durante la cancellazione.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><ShieldX size={15} /> Cancellazione dati (GDPR)</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Diritto all'oblio: elimina tutte le conversazioni collegate a un'email (quella lasciata
        dal visitatore all'escalation). Operazione irreversibile.
      </p>
      <form onSubmit={erase} style={{ display: "flex", gap: 8 }}>
        <input type="email" value={email} onChange={(e) => { setEmail(e.target.value); setResult(null); }} placeholder="email@visitatore.it" style={{ flex: 1 }} />
        <button className="wpai-btn danger" type="submit" disabled={busy}>{busy ? "Cancellazione…" : "Elimina"}</button>
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

export default function Settings() {
  return (
    <div>
      <h1 className="wpai-page-title">Configurazione</h1>
      <div className="wpai-two-col">
        <InfoFieldsManager />
        <CannedManager />
      </div>
      <div style={{ marginTop: 16, maxWidth: 520 }}>
        <GdprCard />
      </div>
    </div>
  );
}

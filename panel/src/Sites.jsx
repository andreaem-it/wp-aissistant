import { useCallback, useEffect, useState } from "react";
import { Globe, Trash2, Plus, TriangleAlert, CircleCheck, FlaskConical } from "lucide-react";
import { api } from "./api.js";
import Loading from "./Loading.jsx";
import {
  KIND_LABELS, SOURCE_LABELS, canAddStaging, errorMessage, formatDate, isCovered, liveAction,
  liveSlotsLabel, pendingObserved,
} from "./licence.js";

/**
 * I siti coperti dalla licenza.
 *
 * Non è una schermata di impostazioni avanzate: **il widget parte solo su un dominio
 * registrato**, quindi finché questa pagina non dice qualcosa un dominio sbagliato si manifesta
 * come "il widget non c'è", che è il modo peggiore di scoprirlo.
 */
export default function Sites() {
  const [data, setData] = useState(null);
  const [state, setState] = useState({ loading: true, error: "" });
  const [form, setForm] = useState({ origin: "", kind: "live" });
  const [feedback, setFeedback] = useState({ error: "", ok: "" });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setState({ loading: true, error: "" });
    api.origins()
      .then((payload) => {
        setData(payload);
        setState({ loading: false, error: "" });
      })
      .catch((error) => setState({
        loading: false,
        error: errorMessage(error, "Non è stato possibile caricare i siti registrati."),
      }));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (state.loading) return <Loading label="Caricamento dei siti…" />;
  if (state.error) {
    return (
      <div className="wpai-card">
        <div className="wpai-card-title"><Globe size={15} /> Siti e licenza</div>
        <p role="alert" style={{ color: "var(--red)", fontSize: 13 }}>{state.error}</p>
        <button className="wpai-btn" type="button" onClick={load}>Riprova</button>
      </div>
    );
  }

  const origins = data?.origins || [];
  const slots = data?.slots;
  const action = liveAction(slots);
  const covered = isCovered(origins);
  const observed = pendingObserved(data?.observed, origins);
  const stagingAllowed = canAddStaging(slots);
  const liveBlocked = form.kind === "live" && action.kind === "blocked";
  const stagingBlocked = form.kind === "staging" && !stagingAllowed;

  const submit = async (event) => {
    event.preventDefault();
    const value = form.origin.trim();
    if (!value || busy) return;
    // Sostituire il dominio di produzione toglie il widget dal sito precedente: va chiesto, non
    // dedotto dal fatto che il modulo è stato inviato.
    if (form.kind === "live" && action.replaces) {
      const current = origins.find((o) => o.kind === "live");
      const confirmed = window.confirm(
        `Il widget smetterà di funzionare su ${current?.host || "il dominio attuale"} e passerà a `
        + `${value}. Vuoi procedere?`
      );
      if (!confirmed) return;
    }
    setBusy(true);
    setFeedback({ error: "", ok: "" });
    try {
      await api.addOrigin(value, form.kind);
      setForm({ origin: "", kind: form.kind });
      setFeedback({ error: "", ok: "Dominio registrato. Ricarica la pagina del sito per vedere il widget." });
      load();
    } catch (error) {
      setFeedback({ error: errorMessage(error), ok: "" });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row) => {
    const isLast = row.kind === "live" && origins.filter((o) => o.kind === "live").length === 1;
    const warning = isLast
      ? `Rimuovendo ${row.host} il widget smetterà di funzionare su quel sito. Continuare?`
      : `Rimuovere ${row.host} dalla licenza?`;
    if (!window.confirm(warning)) return;
    setFeedback({ error: "", ok: "" });
    try {
      await api.deleteOrigin(row.id);
      load();
    } catch (error) {
      setFeedback({ error: errorMessage(error), ok: "" });
    }
  };

  return (
    <>
      <div className="wpai-card">
        <div className="wpai-card-title"><Globe size={15} /> Siti coperti dalla licenza</div>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
          Il widget funziona <strong>solo</strong> sui domini registrati qui. Gli indirizzi di
          sviluppo locale (<code>localhost</code>, <code>.local</code>, <code>.test</code>) sono
          sempre ammessi e non occupano uno slot.
        </p>

        {!covered && (
          <p role="alert" className="wpai-error" style={{ marginBottom: 12 }}>
            <TriangleAlert size={14} aria-hidden="true" /> Nessun dominio registrato: il widget
            non parte su nessun sito. Aggiungi qui il dominio del tuo sito.
          </p>
        )}

        <table className="wpai-table" style={{ marginBottom: 12 }}>
          <thead>
            <tr><th>Dominio</th><th>Tipo</th><th>Origine</th><th aria-label="Azioni" /></tr>
          </thead>
          <tbody>
            {origins.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.kind === "live"
                    ? <CircleCheck size={13} aria-hidden="true" />
                    : <FlaskConical size={13} aria-hidden="true" />}{" "}
                  <code>{row.host}</code>
                </td>
                <td>{KIND_LABELS[row.kind] || row.kind}</td>
                <td style={{ color: "var(--text-muted)", fontSize: 12.5 }}>
                  {SOURCE_LABELS[row.source] || row.source}
                  {row.confirmed_at ? ` · ${formatDate(row.confirmed_at)}` : ""}
                </td>
                <td style={{ textAlign: "right" }}>
                  <button className="wpai-icon-btn" title={`Rimuovi ${row.host}`}
                          aria-label={`Rimuovi ${row.host}`} onClick={() => remove(row)}>
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {origins.length === 0 && (
              <tr><td colSpan={4} style={{ color: "var(--text-muted)" }}>Nessun dominio registrato.</td></tr>
            )}
          </tbody>
        </table>

        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "0 0 12px" }}>
          {liveSlotsLabel(slots)}
          {slots ? ` · Staging: ${slots.staging_used} di ${slots.staging_limit}` : ""}
        </p>

        <form onSubmit={submit} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label className="wpai-sr-only" htmlFor="wpai-origin-value">Dominio da registrare</label>
          <input
            id="wpai-origin-value"
            type="text"
            value={form.origin}
            onChange={(e) => setForm({ ...form, origin: e.target.value })}
            placeholder="https://esempio.it"
            style={{ flex: 1, minWidth: 220 }}
          />
          <label className="wpai-sr-only" htmlFor="wpai-origin-kind">Tipo di dominio</label>
          <select
            id="wpai-origin-kind"
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value })}
          >
            <option value="live">Produzione</option>
            <option value="staging">Staging</option>
          </select>
          <button className="wpai-btn" type="submit" disabled={busy || liveBlocked || stagingBlocked}>
            <Plus size={14} /> {busy ? "Salvataggio…" : (form.kind === "live" ? action.label : "Aggiungi")}
          </button>
        </form>

        {form.kind === "staging" && (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0 0" }}>
            Il dominio di staging dev'essere un sottodominio del sito di produzione con una parola
            che lo identifichi — <code>staging.</code>, <code>dev.</code>, <code>demo.</code> — oppure
            stare su una piattaforma di sviluppo riconosciuta (WP Engine, Vercel, DDEV…).
          </p>
        )}
        {liveBlocked && (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0 0" }}>
            Hai usato tutti i domini di produzione del tuo piano. Rimuovine uno oppure passa a un
            piano superiore.
          </p>
        )}
        {stagingBlocked && (
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "10px 0 0" }}>
            Hai già un dominio di staging. Rimuovilo per registrarne un altro.
          </p>
        )}
        {feedback.error && (
          <p role="alert" style={{ color: "var(--red)", fontSize: 13, margin: "10px 0 0" }}>
            {feedback.error}
          </p>
        )}
        {feedback.ok && (
          <p role="status" style={{ color: "var(--text-muted)", fontSize: 13, margin: "10px 0 0" }}>
            {feedback.ok}
          </p>
        )}
      </div>

      {observed.length > 0 && (
        <div className="wpai-card">
          <div className="wpai-card-title"><TriangleAlert size={15} /> Domini visti in uso</div>
          <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
            Abbiamo visto traffico da questi domini, che non sono coperti dalla licenza: il widget
            lì non funziona. Registrali se sono tuoi.
          </p>
          <table className="wpai-table">
            <tbody>
              {observed.map((row) => (
                <tr key={row.id}>
                  <td><code>{row.host}</code></td>
                  <td style={{ color: "var(--text-muted)", fontSize: 12.5 }}>
                    Ultima volta: {formatDate(row.last_seen_at) || "—"}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      className="wpai-btn"
                      type="button"
                      onClick={() => setForm({ origin: row.origin, kind: "live" })}
                    >
                      Usa questo
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

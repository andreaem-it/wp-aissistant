import { useCallback, useEffect, useState } from "react";
import { SearchX, GraduationCap, EyeOff } from "lucide-react";
import { api } from "./api.js";
import { formatMoment } from "./activity.js";

/** Domande a cui la knowledge base non ha saputo rispondere, con il flusso "insegna la risposta". */
export default function KnowledgeGaps({ days = 30 }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [teaching, setTeaching] = useState(null); // {question, answer}
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const load = useCallback(
    () =>
      api
        .knowledgeGaps(days)
        .then((data) => { setPayload(data); setError(""); })
        .catch(() => setError("Impossibile caricare le domande senza risposta.")),
    [days],
  );
  useEffect(() => { load(); }, [load]);

  const ignore = async (gap) => {
    setBusy(true);
    setNotice("");
    try {
      await api.reviewKnowledgeGap(gap.question, "ignored", gap.questions);
      await load();
    } catch {
      setError("Operazione non riuscita.");
    } finally {
      setBusy(false);
    }
  };

  const teach = async (e) => {
    e.preventDefault();
    if (!teaching?.answer.trim()) return;
    setBusy(true);
    setNotice("");
    try {
      await api.teachKnowledge(teaching.question, teaching.answer.trim());
      await api.reviewKnowledgeGap(teaching.question, "taught", teaching.questions);
      setTeaching(null);
      setNotice("Risposta aggiunta alla knowledge base: sarà usata dalle prossime chat.");
      await load();
    } catch {
      setError("Salvataggio della risposta non riuscito: la domanda resta in elenco.");
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>;
  if (!payload) return <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>;

  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><SearchX size={15} /> Domande senza risposta</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
        Domande in cui l'assistente non ha trovato nulla di utile nella knowledge base, o la cui
        risposta è stata giudicata inutile dal visitatore. Rispondi una volta e sparisce
        dall'elenco.
      </p>

      {notice && <p role="status" style={{ fontSize: 12.5, color: "var(--green)" }}>{notice}</p>}

      {payload.gaps.length === 0 && (
        <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          Nessuna lacuna rilevata nel periodo.
        </p>
      )}

      <div style={{ display: "grid", gap: 10 }}>
        {payload.gaps.map((gap) => (
          <div key={gap.question_hash} style={{ borderBottom: "1px solid var(--border)", paddingBottom: 10 }}>
            <div className="wpai-canned-row">
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>«{gap.question}»</div>
                <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 3 }}>
                  {gap.occurrences} {gap.occurrences === 1 ? "volta" : "volte"}
                  {gap.cluster_size > 1 && ` · ${gap.cluster_size} formulazioni simili`}
                  {gap.negative_feedback > 0 && ` · ${gap.negative_feedback} 👎`}
                  {gap.last_seen && ` · ultima ${formatMoment(gap.last_seen)}`}
                  {" · conversazioni "}
                  {gap.conversation_ids.map((id) => `#${id}`).join(", ")}
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  className="wpai-btn ghost"
                  disabled={busy}
                  onClick={() => { setTeaching({ question: gap.question, questions: gap.questions, answer: "" }); setNotice(""); }}
                >
                  <GraduationCap size={13} /> Insegna
                </button>
                <button className="wpai-btn ghost" disabled={busy} onClick={() => ignore(gap)}>
                  <EyeOff size={13} /> Ignora
                </button>
              </div>
            </div>

            {teaching?.question === gap.question && (
              <form onSubmit={teach} style={{ display: "grid", gap: 6, marginTop: 8 }}>
                <textarea
                  rows={3}
                  autoFocus
                  value={teaching.answer}
                  onChange={(e) => setTeaching((t) => ({ ...t, answer: e.target.value }))}
                  placeholder="Scrivi qui la risposta corretta: verrà aggiunta alla knowledge base."
                  aria-label="Risposta da insegnare"
                />
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="wpai-btn" type="submit" disabled={busy || !teaching.answer.trim()}>
                    {busy ? "Salvataggio…" : "Salva risposta"}
                  </button>
                  <button className="wpai-btn ghost" type="button" onClick={() => setTeaching(null)}>
                    Annulla
                  </button>
                </div>
              </form>
            )}
          </div>
        ))}
      </div>

      {payload.by_topic.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 6 }}>
            Temi aperti più frequenti
          </div>
          <div className="wpai-tag-row">
            {payload.by_topic.map((row) => (
              <span key={row.topic} className="wpai-tag ai">{row.topic} · {row.conversations}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

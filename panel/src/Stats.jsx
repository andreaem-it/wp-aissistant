import { useEffect, useState } from "react";
import {
  MessagesSquare, UserCheck, CheckCircle2, Bot, Timer, Percent, ThumbsUp, ThumbsDown, ShieldCheck,
  Tag as TagIcon, Sparkles, Star, Languages,
} from "lucide-react";
import { api } from "./api.js";
import { MiniBars, Breakdown } from "./Charts.jsx";
import { INTENT_LABELS, LANGUAGE_LABELS } from "./inboxFilters.js";
import AnalyticsOverview from "./AnalyticsOverview.jsx";
import KnowledgeGaps from "./KnowledgeGaps.jsx";

function pct(x) {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
}

function CsatSection() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api.csat(days).then(setReport).catch(() => setError("Impossibile caricare il report CSAT."));
  }, [days]);

  const summary = report?.summary;
  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>Soddisfazione (CSAT)</h2>
        <select aria-label="Periodo del report CSAT" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Ultimi 7 giorni</option>
          <option value={30}>Ultimi 30 giorni</option>
          <option value={90}>Ultimi 90 giorni</option>
        </select>
      </div>

      {error && <p style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>}
      {!report && !error && <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>}

      {report && summary.responses === 0 && (
        <div className="wpai-card" style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
          Nessuna valutazione nel periodo. Il widget la chiede al visitatore quando la
          conversazione viene chiusa.
        </div>
      )}

      {report && summary.responses > 0 && (
        <>
          <div className="wpai-stat-grid">
            <div className="wpai-card wpai-stat-card">
              <div className="icon"><Star size={18} strokeWidth={2.25} /></div>
              <div className="value">{summary.average}</div>
              <div className="label">Voto medio (1–5)</div>
            </div>
            <div className="wpai-card wpai-stat-card">
              <div className="icon"><Percent size={18} strokeWidth={2.25} /></div>
              <div className="value">{pct(summary.satisfied_rate)}</div>
              <div className="label">Voti 4–5</div>
            </div>
            <div className="wpai-card wpai-stat-card">
              <div className="icon"><MessagesSquare size={18} strokeWidth={2.25} /></div>
              <div className="value">{summary.responses}</div>
              <div className="label">Valutazioni ricevute</div>
            </div>
          </div>

          <div className="wpai-two-col">
            <div className="wpai-card">
              <div className="wpai-card-title">Distribuzione dei voti</div>
              <Breakdown
                items={[5, 4, 3, 2, 1].map((score) => ({
                  label: `${score} ★`,
                  value: summary.distribution[String(score)] || 0,
                }))}
              />
            </div>
            <div className="wpai-card">
              <div className="wpai-card-title">Chi ha risolto</div>
              <Breakdown
                items={report.by_resolution.map((row) => ({
                  label: `${row.resolved_by === "ai" ? "AI" : "Operatore"} — media ${row.average}`,
                  value: row.responses,
                }))}
              />
            </div>
          </div>

          <div className="wpai-two-col">
            <div className="wpai-card">
              <div className="wpai-card-title">Per operatore</div>
              <table className="wpai-table">
                <tbody>
                  {report.by_operator.map((row) => (
                    <tr key={row.operator_id ?? "none"}>
                      <td>{row.name}</td>
                      <td>{row.responses} valutazioni</td>
                      <td style={{ textAlign: "right", fontWeight: 700 }}>{row.average}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="wpai-card">
              <div className="wpai-card-title">Per reparto</div>
              <table className="wpai-table">
                <tbody>
                  {report.by_department.map((row) => (
                    <tr key={row.department_id ?? "none"}>
                      <td>{row.name}</td>
                      <td>{row.responses} valutazioni</td>
                      <td style={{ textAlign: "right", fontWeight: 700 }}>{row.average}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {report.comments.length > 0 && (
            <div className="wpai-card" style={{ marginTop: 16 }}>
              <div className="wpai-card-title">Ultimi commenti</div>
              <ul className="wpai-activity">
                {report.comments.map((c) => (
                  <li key={c.conversation_id}>
                    <span>{"★".repeat(c.score)} — {c.comment}</span>
                    <span className="dim">#{c.conversation_id}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function AdvancedSection() {
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api.analyticsOverview(days).then(setOverview).catch(() => setError("Impossibile caricare le metriche."));
  }, [days]);

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 16, margin: 0 }}>Efficacia del supporto</h2>
        <select aria-label="Periodo delle metriche" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Ultimi 7 giorni</option>
          <option value={30}>Ultimi 30 giorni</option>
          <option value={90}>Ultimi 90 giorni</option>
        </select>
      </div>
      {error ? (
        <p role="alert" style={{ fontSize: 12.5, color: "var(--red)" }}>{error}</p>
      ) : (
        <AnalyticsOverview data={overview} />
      )}
      <div style={{ marginTop: 16 }}>
        <KnowledgeGaps days={days} />
      </div>
    </div>
  );
}

export default function Stats() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats().then(setStats);
  }, []);

  if (!stats) return <p style={{ color: "var(--text-muted)" }}>Caricamento…</p>;

  const c = stats.conversations;
  const ai = stats.ai;
  const cards = [
    { label: "Conversazioni totali", value: c.total, Icon: MessagesSquare },
    { label: "In attesa di operatore", value: c.escalated, Icon: UserCheck },
    { label: "Chiuse", value: c.closed, Icon: CheckCircle2 },
    { label: "Risposte AI", value: ai.answered, Icon: Bot },
    { label: "Risolte da AI", value: pct(ai.resolution_rate), Icon: Percent },
    { label: "Latenza media", value: ai.avg_latency_ms ? `${ai.avg_latency_ms} ms` : "—", Icon: Timer },
    { label: "Feedback positivi", value: stats.feedback?.positive ?? 0, Icon: ThumbsUp },
    { label: "Feedback negativi", value: stats.feedback?.negative ?? 0, Icon: ThumbsDown },
  ];

  const esc = stats.escalations_by_trigger;
  const breakdown = [
    { label: "Parola chiave", value: esc.keyword },
    { label: "Decisione AI", value: esc.model },
    { label: "AI non disponibile", value: esc.llm_down },
  ];

  const intentBreakdown = Object.entries(stats.classification?.by_intent || {}).map(([intent, value]) => ({
    label: INTENT_LABELS[intent] || intent,
    value,
  }));

  const languageBreakdown = Object.entries(stats.languages || {})
    .map(([code, value]) => ({ label: LANGUAGE_LABELS[code] || code, value }))
    .sort((a, b) => b.value - a.value);

  const sla = stats.sla;
  const slaBreakdown = sla
    ? [
        { label: "Nei tempi", value: sla.met },
        { label: "In scadenza", value: sla.at_risk },
        { label: "Violati", value: sla.breached },
      ]
    : [];

  return (
    <div>
      <h1 className="wpai-page-title">Statistiche</h1>
      <div className="wpai-stat-grid">
        {cards.map((card) => (
          <div key={card.label} className="wpai-card wpai-stat-card">
            <div className="icon"><card.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{card.value}</div>
            <div className="label">{card.label}</div>
          </div>
        ))}
      </div>

      <div className="wpai-two-col">
        <div className="wpai-card">
          <div className="wpai-card-title">Conversazioni (ultimi 14 giorni)</div>
          <MiniBars data={stats.volume_daily} xKey="date" yKey="conversations" />
        </div>
        <div className="wpai-card">
          <div className="wpai-card-title">Motivi di escalation</div>
          <Breakdown items={breakdown} />
        </div>
      </div>

      {(stats.tags?.length > 0 || intentBreakdown.length > 0) && (
        <div className="wpai-two-col">
          <div className="wpai-card">
            <div className="wpai-card-title"><TagIcon size={15} /> Tag più usati</div>
            {stats.tags?.length > 0 ? (
              <Breakdown items={stats.tags.map((t) => ({ label: t.source === "ai" ? `${t.name} (AI)` : t.name, value: t.conversations }))} />
            ) : (
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 0" }}>Nessun tag usato finora.</p>
            )}
          </div>
          <div className="wpai-card">
            <div className="wpai-card-title"><Languages size={15} /> Lingue dei visitatori</div>
            {languageBreakdown.length > 0 ? (
              <Breakdown items={languageBreakdown} />
            ) : (
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 0" }}>Nessun dato.</p>
            )}
          </div>
          <div className="wpai-card">
            <div className="wpai-card-title"><Sparkles size={15} /> Intenti rilevati</div>
            {intentBreakdown.length > 0 ? (
              <Breakdown items={intentBreakdown} />
            ) : (
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 0" }}>
                Nessuna conversazione classificata.
              </p>
            )}
          </div>
        </div>
      )}

      <AdvancedSection />

      <CsatSection />

      {sla && (
        <div className="wpai-two-col">
          <div className="wpai-card">
            <div className="wpai-card-title"><ShieldCheck size={15} /> SLA</div>
            {sla.tracked === 0 ? (
              <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 0" }}>
                Nessuna conversazione con SLA attivo. Configura le regole in <b>Configurazione</b>.
              </p>
            ) : (
              <Breakdown items={slaBreakdown} />
            )}
          </div>
          <div className="wpai-stat-grid">
            <div className="wpai-card wpai-stat-card">
              <div className="icon"><Percent size={18} strokeWidth={2.25} /></div>
              <div className="value">{pct(sla.compliance_rate)}</div>
              <div className="label">SLA rispettati</div>
            </div>
            <div className="wpai-card wpai-stat-card">
              <div className="icon"><Timer size={18} strokeWidth={2.25} /></div>
              <div className="value">
                {sla.avg_first_response_minutes === null || sla.avg_first_response_minutes === undefined
                  ? "—"
                  : `${sla.avg_first_response_minutes} min`}
              </div>
              <div className="label">Prima risposta media</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

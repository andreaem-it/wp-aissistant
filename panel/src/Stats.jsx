import { useEffect, useState } from "react";
import { MessagesSquare, UserCheck, CheckCircle2, Bot, Timer, Percent, ThumbsUp, ThumbsDown, ShieldCheck } from "lucide-react";
import { api } from "./api.js";
import { MiniBars, Breakdown } from "./Charts.jsx";

function pct(x) {
  return x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`;
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

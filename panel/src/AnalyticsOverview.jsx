import { Bot, Clock, CheckCircle2, UserCheck } from "lucide-react";
import { MiniBars, Breakdown } from "./Charts.jsx";

function minutes(value) {
  if (value === null || value === undefined) return "—";
  if (value < 60) return `${value} min`;
  const hours = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

function pct(value) {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)}%`;
}

/** Metriche di esito sul periodo: deflection, tempi e volumi. */
export default function AnalyticsOverview({ data }) {
  if (!data) return <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>Caricamento…</p>;
  if (data.conversations === 0) {
    return (
      <div className="wpai-card" style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
        Nessuna conversazione nel periodo selezionato.
      </div>
    );
  }

  const cards = [
    { label: "Risolte senza operatore", value: pct(data.deflection_rate), Icon: Bot },
    { label: "Passate a un operatore", value: data.escalated, Icon: UserCheck },
    { label: "Prima risposta (mediana)", value: minutes(data.first_response.median_minutes), Icon: Clock },
    { label: "Risoluzione (mediana)", value: minutes(data.resolution.median_minutes), Icon: CheckCircle2 },
  ];

  return (
    <>
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
          <div className="wpai-card-title">Conversazioni al giorno</div>
          <MiniBars data={data.trend} xKey="date" yKey="conversations" />
        </div>
        <div className="wpai-card">
          <div className="wpai-card-title">Esito nel periodo</div>
          <Breakdown
            items={[
              { label: "Gestite solo dall'AI", value: data.handled_by_ai },
              { label: "Con operatore", value: data.escalated },
              { label: "Chiuse", value: data.closed },
            ]}
          />
          <p style={{ fontSize: 11.5, color: "var(--text-muted)", margin: "10px 0 0" }}>
            Prima risposta media {minutes(data.first_response.average_minutes)} su{" "}
            {data.first_response.count} conversazioni · risoluzione media{" "}
            {minutes(data.resolution.average_minutes)}
          </p>
        </div>
      </div>
    </>
  );
}

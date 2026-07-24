import { useEffect, useState } from "react";
import { MessagesSquare, UserCheck, CheckCircle2 } from "lucide-react";
import { api } from "./api.js";

export default function Stats() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats().then(setStats);
  }, []);

  if (!stats) return <p style={{ color: "var(--text-muted)" }}>Caricamento…</p>;

  const cards = [
    { label: "Conversazioni totali", value: stats.total_conversations, Icon: MessagesSquare },
    { label: "In attesa di operatore", value: stats.escalated, Icon: UserCheck },
    { label: "Chiuse", value: stats.closed, Icon: CheckCircle2 },
  ];

  return (
    <div>
      <h1 className="wpai-page-title">Statistiche</h1>
      <div className="wpai-stat-grid">
        {cards.map((c) => (
          <div key={c.label} className="wpai-card wpai-stat-card">
            <div className="icon"><c.Icon size={18} strokeWidth={2.25} /></div>
            <div className="value">{c.value}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

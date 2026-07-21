import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function Stats() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats().then(setStats);
  }, []);

  if (!stats) return <p>caricamento...</p>;

  const cards = [
    { label: "Conversazioni totali", value: stats.total_conversations },
    { label: "In attesa di operatore", value: stats.escalated },
    { label: "Chiuse", value: stats.closed },
  ];

  return (
    <div>
      <h1>Statistiche</h1>
      <div className="wpai-stat-grid">
        {cards.map((c) => (
          <div key={c.label} className="wpai-card wpai-stat-card">
            <div className="value">{c.value}</div>
            <div className="label">{c.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

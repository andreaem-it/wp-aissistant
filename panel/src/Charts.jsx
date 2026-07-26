// Minimal, dependency-free viz for the internal ops panels. Single accent hue, labelled,
// accessible (title + aria-label). Not meant as a general charting lib — just enough to make
// the stats legible.

export function MiniBars({ data, xKey, yKey, height = 120, label }) {
  const max = Math.max(1, ...data.map((d) => d[yKey]));
  return (
    <div>
      {label && <div className="wpai-chart-label">{label}</div>}
      <div className="wpai-bars" style={{ height }} role="img" aria-label={label || "grafico a barre"}>
        {data.length === 0 && <div className="wpai-chart-empty">Nessun dato</div>}
        {data.map((d, i) => {
          const h = Math.round((d[yKey] / max) * 100);
          return (
            <div key={i} className="wpai-bar-col" title={`${d[xKey]}: ${d[yKey]}`}>
              <div className="wpai-bar" style={{ height: `${h}%` }}>
                <span className="wpai-bar-value">{d[yKey] || ""}</span>
              </div>
              <div className="wpai-bar-x">{String(d[xKey]).slice(5)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Horizontal breakdown (e.g. escalations by trigger) as labelled proportion bars.
export function Breakdown({ items }) {
  const total = Math.max(1, items.reduce((s, it) => s + it.value, 0));
  return (
    <div className="wpai-breakdown">
      {items.map((it) => (
        <div key={it.label} className="wpai-breakdown-row">
          <div className="wpai-breakdown-head">
            <span>{it.label}</span>
            <span className="wpai-breakdown-val">{it.value}</span>
          </div>
          <div className="wpai-breakdown-track">
            <div className="wpai-breakdown-fill" style={{ width: `${(it.value / total) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

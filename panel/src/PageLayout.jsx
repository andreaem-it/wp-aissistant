export function PageHeader({ eyebrow, title, description, actions }) {
  return (
    <header className="wpai-page-header">
      <div>
        {eyebrow && <div className="wpai-page-eyebrow">{eyebrow}</div>}
        <h1 className="wpai-page-title">{title}</h1>
        {description && <p className="wpai-page-description">{description}</p>}
      </div>
      {actions && <div className="wpai-page-actions">{actions}</div>}
    </header>
  );
}

export function SectionTabs({ items, active, onChange, label = "Sezioni della pagina" }) {
  return (
    <div className="wpai-section-tabs" role="tablist" aria-label={label}>
      {items.map((item) => {
        const selected = item.key === active;
        const Icon = item.Icon;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={selected}
            className={selected ? "active" : ""}
            onClick={() => onChange(item.key)}
          >
            {Icon && <Icon size={16} strokeWidth={2.2} />}
            <span>
              <strong>{item.label}</strong>
              {item.description && <small>{item.description}</small>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ active, name, children, className = "" }) {
  if (active !== name) return null;
  return (
    <section className={`wpai-tab-panel ${className}`.trim()} role="tabpanel">
      {children}
    </section>
  );
}

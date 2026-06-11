export default function InstanceBrowser({ info, hovered, onSelect, onHover, trees = [] }) {
  const TREES = trees;
  return (
    <div
      className="panel"
      style={{
        top: 24,
        right: 24,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        maxHeight: "calc(100vh - 48px)",
        overflowY: "auto",
        paddingRight: 4,
      }}
    >
      {TREES.map((t) => (
        <div key={t.id}>
          <div className="panel-label" style={{ marginBottom: 4 }}>
            {t.subtitle}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {t.branches.map((b) => (
              <button
                key={b.id}
                onClick={() => onSelect(info === b.id ? null : b.id)}
                onMouseEnter={() => onHover(b.id)}
                onMouseLeave={() => onHover(null)}
                style={{
                  background: info === b.id ? "#111" : hovered === b.id ? "#f4f4f4" : "#ffffff",
                  color: info === b.id ? "#fff" : "#333",
                  border: "1px solid #cccccc",
                  padding: "5px 11px",
                  fontFamily: "inherit",
                  fontSize: 12,
                  cursor: "pointer",
                  textAlign: "left",
                  letterSpacing: "0.01em",
                  transition: "background 0.12s",
                }}
              >
                {b.name}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

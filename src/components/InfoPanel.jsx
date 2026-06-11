export default function InfoPanel({ selected, inboundLinks, onSelect, onClose, branchIndex = {} }) {
  const BRANCH_INDEX = branchIndex;
  if (!selected) return null;

  return (
    <div
      className="panel"
      style={{
        top: 24,
        left: 24,
        background: "rgba(255,255,255,0.96)",
        border: "1px solid #d8d8d8",
        boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
        padding: 20,
        maxWidth: 340,
        color: "#333",
        fontSize: 13,
        lineHeight: "19px",
        letterSpacing: "0.01em",
      }}
    >
      <div className="panel-label" style={{ marginBottom: 4 }}>
        {selected.tree.subtitle} / {selected.tree.label.replace(" TREE", "")}
      </div>
      <div style={{ color: "#111", fontSize: 20, marginBottom: 4, fontWeight: 600 }}>
        {selected.branch.name}
      </div>
      <div style={{ color: "#aaa", fontSize: 10, fontFamily: "monospace", marginBottom: 14 }}>
        {selected.branch.id}
      </div>

      <div className="panel-label" style={{ marginBottom: 6 }}>Properties</div>
      <div style={{ color: "#333", marginBottom: 14 }}>
        {selected.branch.leaves.map((l, i) => (
          <div key={i} style={{ marginBottom: 3, paddingLeft: 2 }}>
            {"· "}{l}
          </div>
        ))}
      </div>

      {(selected.branch.links || []).length > 0 && (
        <>
          <div className="panel-label" style={{ marginBottom: 6 }}>Outbound links</div>
          <div style={{ marginBottom: 12 }}>
            {selected.branch.links.map((link) => {
              const t = BRANCH_INDEX[link.id];
              return (
                <div key={link.id}>
                  <button onClick={() => onSelect(link.id)} className="link-button">
                    {"→ "}
                    <span style={{ textDecoration: "underline" }}>{t ? t.branch.name : link.id}</span>
                    {t && <span style={{ color: "#999", fontSize: 10 }}> · {t.tree.subtitle}</span>}
                  </button>
                  {link.why && <div style={{ color: "#aaa", fontSize: 10, paddingLeft: 14, marginBottom: 4 }}>{link.why}</div>}
                </div>
              );
            })}
          </div>
        </>
      )}

      {(inboundLinks[selected.branch.id] || []).length > 0 && (
        <>
          <div className="panel-label" style={{ marginBottom: 6 }}>Inbound links</div>
          <div style={{ marginBottom: 12 }}>
            {inboundLinks[selected.branch.id].map((id) => {
              const t = BRANCH_INDEX[id];
              const why = t?.branch.links?.find((l) => l.id === selected.branch.id)?.why;
              return (
                <div key={id}>
                  <button onClick={() => onSelect(id)} className="link-button">
                    {"← "}
                    <span style={{ textDecoration: "underline" }}>{t ? t.branch.name : id}</span>
                    {t && <span style={{ color: "#999", fontSize: 10 }}> · {t.tree.subtitle}</span>}
                  </button>
                  {why && <div style={{ color: "#aaa", fontSize: 10, paddingLeft: 14, marginBottom: 4 }}>{why}</div>}
                </div>
              );
            })}
          </div>
        </>
      )}

      <button
        onClick={onClose}
        style={{
          marginTop: 4,
          background: "#ffffff",
          border: "1px solid #cccccc",
          color: "#555",
          padding: "5px 12px",
          fontFamily: "inherit",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        close
      </button>
    </div>
  );
}

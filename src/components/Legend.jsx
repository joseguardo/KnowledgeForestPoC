export default function Legend({ autoRotate, onToggleAutoRotate }) {
  return (
    <div className="panel" style={{ bottom: 24, left: 24, color: "#555", fontSize: 12, lineHeight: "20px", letterSpacing: "0.02em" }}>
      <div style={{ color: "#333", marginBottom: 8, fontSize: 13, fontWeight: 600 }}>Node types</div>
      <div style={{ display: "flex", gap: 16, alignItems: "center", marginBottom: 14 }}>
        <span>&#9675; Entity</span>
        <span>&#9651; System</span>
        <span>&#9196; House</span>
        <span style={{ borderBottom: "1px dashed #888", paddingBottom: 1 }}>--- Cross-link</span>
      </div>
      <div style={{ color: "#333", marginBottom: 6, fontSize: 13, fontWeight: 600 }}>Controls</div>
      <div style={{ color: "#777", fontSize: 11, lineHeight: "17px" }}>
        <div>Drag — orbit · Shift+drag — pan · Scroll — zoom</div>
        <div>Hover a tree to highlight · Click to open details</div>
      </div>
      <button
        onClick={onToggleAutoRotate}
        style={{
          marginTop: 10,
          background: autoRotate ? "#111" : "#ffffff",
          color: autoRotate ? "#fff" : "#333",
          border: "1px solid #cccccc",
          padding: "5px 12px",
          fontFamily: "inherit",
          fontSize: 11,
          cursor: "pointer",
        }}
      >
        {autoRotate ? "◐ Auto-rotate: on" : "◑ Auto-rotate: off"}
      </button>
    </div>
  );
}

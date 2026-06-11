import { HOUSE_INDEX, TREES } from "../data/trees";

export default function HousePanel({ houseId, onClose }) {
  if (!houseId) return null;
  const house = HOUSE_INDEX[houseId];
  if (!house) return null;

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
        Static Table
      </div>
      <div style={{ color: "#111", fontSize: 20, marginBottom: 4, fontWeight: 600 }}>
        {house.name}
      </div>
      <div style={{ color: "#777", fontSize: 12, marginBottom: 14 }}>
        {house.description}
      </div>

      <div className="panel-label" style={{ marginBottom: 6 }}>Records</div>
      <div style={{ color: "#333", marginBottom: 14, fontSize: 16, fontWeight: 600 }}>
        {house.records}
      </div>

      <div className="panel-label" style={{ marginBottom: 6 }}>Fields</div>
      <div style={{ color: "#333", marginBottom: 14, fontFamily: "monospace", fontSize: 11 }}>
        {house.fields.map((f, i) => (
          <span key={f}>
            {f}{i < house.fields.length - 1 ? ", " : ""}
          </span>
        ))}
      </div>

      <div className="panel-label" style={{ marginBottom: 6 }}>Related trees</div>
      <div style={{ marginBottom: 12 }}>
        {house.relatedTrees.map((treeId) => {
          const tree = TREES.find((t) => t.id === treeId);
          return (
            <div key={treeId} style={{ marginBottom: 3, paddingLeft: 2 }}>
              {"· "}{tree ? tree.subtitle : treeId}
            </div>
          );
        })}
      </div>

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

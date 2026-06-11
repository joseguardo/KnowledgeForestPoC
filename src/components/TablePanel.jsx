import { useState, useMemo } from "react";
import { DB_TABLES, HOUSE_INDEX } from "../data/trees";

export default function TablePanel({ open, onClose, onSelectHouse }) {
  const [activeTab, setActiveTab] = useState(0);
  const [highlightId, setHighlightId] = useState(null);

  const idToTable = useMemo(() => {
    const map = {};
    DB_TABLES.tables.forEach((t, ti) => {
      if (t.columns.includes("id")) {
        t.rows.forEach((row) => { map[String(row.id)] = ti; });
      }
    });
    return map;
  }, []);

  if (!open) return null;

  const table = DB_TABLES.tables[activeTab];

  const navigateTo = (value) => {
    const v = String(value);
    if (v.startsWith("house:") && HOUSE_INDEX[v] && onSelectHouse) {
      onSelectHouse(v);
      return;
    }
    if (v in idToTable) {
      setActiveTab(idToTable[v]);
      setHighlightId(v);
    }
  };

  const switchTab = (i) => {
    setActiveTab(i);
    setHighlightId(null);
  };

  return (
    <div
      className="panel"
      style={{
        top: 24,
        left: 24,
        background: "rgba(255,255,255,0.97)",
        border: "1px solid #d8d8d8",
        boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
        padding: 20,
        maxWidth: 520,
        color: "#333",
        fontSize: 13,
        lineHeight: "19px",
        letterSpacing: "0.01em",
      }}
    >
      <div className="panel-label" style={{ marginBottom: 4 }}>
        Database
      </div>
      <div style={{ color: "#111", fontSize: 20, marginBottom: 12, fontWeight: 600 }}>
        {DB_TABLES.name}
      </div>

      <div style={{ display: "flex", gap: 0, marginBottom: 12, borderBottom: "1px solid #e0e0e0" }}>
        {DB_TABLES.tables.map((t, i) => (
          <button
            key={t.name}
            onClick={() => switchTab(i)}
            style={{
              padding: "6px 14px",
              background: i === activeTab ? "#111" : "transparent",
              color: i === activeTab ? "#fff" : "#666",
              border: "none",
              borderBottom: i === activeTab ? "2px solid #111" : "2px solid transparent",
              fontFamily: "monospace",
              fontSize: 12,
              cursor: "pointer",
              fontWeight: i === activeTab ? 600 : 400,
            }}
          >
            {t.name}
          </button>
        ))}
      </div>

      <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: 260 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11, fontFamily: "monospace" }}>
          <thead>
            <tr>
              {table.columns.map((col) => (
                <th
                  key={col}
                  style={{
                    textAlign: "left",
                    padding: "4px 8px",
                    borderBottom: "1px solid #ddd",
                    color: "#888",
                    fontWeight: 600,
                    fontSize: 10,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    whiteSpace: "nowrap",
                    position: "sticky",
                    top: 0,
                    background: "rgba(255,255,255,0.97)",
                  }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, ri) => {
              const isHighlighted = highlightId && String(row.id) === highlightId;
              return (
                <tr
                  key={ri}
                  style={{
                    background: isHighlighted ? "#eef2ff" : ri % 2 === 0 ? "#fafafa" : "#fff",
                    transition: "background 0.15s",
                  }}
                >
                  {table.columns.map((col) => {
                    const val = row[col];
                    const strVal = String(val);
                    const isHouseLink = strVal.startsWith("house:") && !!HOUSE_INDEX[strVal];
                    const canNavigate = isHouseLink || (strVal in idToTable && idToTable[strVal] !== activeTab);
                    return (
                      <td
                        key={col}
                        title={strVal}
                        style={{
                          padding: "4px 8px",
                          borderBottom: "1px solid #f0f0f0",
                          whiteSpace: "nowrap",
                          maxWidth: 200,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {canNavigate ? (
                          <button
                            onClick={() => navigateTo(strVal)}
                            style={{
                              background: "none",
                              border: "none",
                              padding: 0,
                              color: "#2563eb",
                              cursor: "pointer",
                              fontFamily: "inherit",
                              fontSize: "inherit",
                              textDecoration: "underline",
                              textDecorationColor: "#93c5fd",
                            }}
                          >
                            {strVal}
                          </button>
                        ) : (
                          strVal
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 10, color: "#999", fontSize: 11 }}>
        {table.rows.length} rows · click blue IDs to navigate
      </div>

      <button
        onClick={onClose}
        style={{
          marginTop: 8,
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

import { useState, useEffect, useRef } from "react";
import useKnowledgeSearch from "../hooks/useKnowledgeSearch";
import MatchDetails from "./MatchDetails";

const panelStyle = {
  bottom: 24,
  right: 24,
  background: "rgba(255,255,255,0.97)",
  border: "1px solid #d8d8d8",
  boxShadow: "0 2px 16px rgba(0,0,0,0.05)",
  padding: 16,
  width: 340,
  color: "#333",
  fontSize: 13,
  maxHeight: "calc(100vh - 120px)",
  overflowY: "auto",
};

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  border: "1px solid #ccc",
  fontFamily: "inherit",
  fontSize: 12,
  boxSizing: "border-box",
  marginBottom: 8,
};

export default function SearchPanel({ open, onClose, onSelect }) {
  const [query, setQuery] = useState("");
  const timerRef = useRef(null);
  const skipNextQuickRef = useRef(false);

  const {
    quickSearch, deepSearch, clear,
    results, answer, suggestions,
    isSearching, mode, error,
  } = useKnowledgeSearch();

  // Quick search on typing (debounced 300ms)
  useEffect(() => {
    // Skip quick search if a deep search was explicitly triggered
    // (e.g., suggestion click sets query + calls deepSearch)
    if (skipNextQuickRef.current) {
      skipNextQuickRef.current = false;
      return;
    }

    if (!query.trim()) {
      clear();
      return;
    }

    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      quickSearch(query);
    }, 300);

    return () => clearTimeout(timerRef.current);
  }, [query, quickSearch, clear]);

  // Deep search on Enter
  const handleKeyDown = (e) => {
    if (e.key === "Enter" && query.trim()) {
      clearTimeout(timerRef.current);
      deepSearch(query, "answer");
    }
  };

  if (!open) return null;

  return (
    <div className="panel" style={panelStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div className="panel-label">Search Knowledge</div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "#999", cursor: "pointer", fontSize: 16 }}
        >
          x
        </button>
      </div>

      <input
        style={inputStyle}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Type to search, Enter to ask..."
        autoFocus
      />

      <div style={{ fontSize: 9, color: "#aaa", marginBottom: 6, marginTop: -4 }}>
        {mode === "quick" ? "Quick search (type to filter)" : "Deep search (LLM + graph traversal)"}
      </div>

      {isSearching && (
        <div style={{ color: "#999", fontSize: 11, marginBottom: 4 }}>
          {mode === "deep" ? "Thinking..." : "Searching..."}
        </div>
      )}

      {error && (
        <div style={{ color: "#c44", fontSize: 11, marginBottom: 6, padding: "4px 8px", background: "#fff0f0", border: "1px solid #fcc" }}>
          {error}
        </div>
      )}

      {/* Answer (deep search mode) */}
      {answer && (
        <div style={{
          padding: "10px 12px",
          marginBottom: 10,
          background: "#f0f7ff",
          border: "1px solid #d0e0f0",
          fontSize: 12,
          lineHeight: "18px",
          color: "#333",
        }}>
          {answer}
        </div>
      )}

      {/* Results */}
      {results.length === 0 && query.trim() && !isSearching && (
        <div style={{ color: "#999", fontSize: 11 }}>No results</div>
      )}

      {results.map((r, i) => {
        const id = r.pointer_id || r.pointer?.id || r.id;
        const label = r.label || r.pointer?.label || "Unknown";
        const type = r.type || r.pointer?.type || "";
        const score = r.combined_score || r.relevance_score || r.score;
        const source = r.source; // 'search', 'coaccess', 'graph'
        const via = r.via_pointer || r.via || r.via_edge_type;
        const why = r.why || r.via_edge_why;
        const coWeight = r.coaccess_weight;

        const sourceColors = {
          search: { bg: "#e8f4e8", color: "#3a7a3a", label: "Search" },
          coaccess: { bg: "#fff3e0", color: "#c07000", label: "Behavioral" },
          graph: { bg: "#e0f0ff", color: "#2070c0", label: "Graph" },
        };
        const srcStyle = sourceColors[source];

        return (
          <button
            key={id || i}
            onClick={() => id && onSelect(id)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              background: source === "coaccess" ? "#fffaf0" : "#fff",
              border: `1px solid ${source === "coaccess" ? "#f0e0c0" : "#eee"}`,
              padding: "7px 10px",
              marginBottom: 3,
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontWeight: 500 }}>{label}</span>
              <span style={{ color: "#999", fontSize: 10 }}>{type}</span>
              {srcStyle && (
                <span style={{ background: srcStyle.bg, color: srcStyle.color, padding: "1px 5px", borderRadius: 8, fontSize: 8 }}>
                  {srcStyle.label}
                </span>
              )}
            </div>
            {/* Match traceability */}
            <MatchDetails details={r.match_details} />
            {via && (
              <div style={{ fontSize: 10, color: "#888", marginTop: 2 }}>
                {via}{why ? ` — ${why}` : ""}
              </div>
            )}
            {/* Show attributes if enriched */}
            {r.attributes?.length > 0 && (
              <div style={{ fontSize: 10, color: "#666", marginTop: 2 }}>
                {r.attributes.slice(0, 3).map((a) => `${a.key}: ${typeof a.value === "string" ? a.value : JSON.stringify(a.value)}`).join(" | ")}
              </div>
            )}
          </button>
        );
      })}

      {/* Suggestions (explore mode) */}
      {suggestions.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="panel-label" style={{ marginBottom: 4 }}>Related queries</div>
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => { skipNextQuickRef.current = true; setQuery(s); deepSearch(s, "answer"); }}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: "#fafafa",
                border: "1px solid #eee",
                padding: "5px 10px",
                marginBottom: 2,
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 11,
                color: "#555",
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

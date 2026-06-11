import { useState, useRef, useEffect } from "react";
import useKnowledgeSearch from "../hooks/useKnowledgeSearch";
import MatchDetails from "./MatchDetails";

const panelStyle = {
  top: 0,
  right: 0,
  width: 400,
  height: "100vh",
  background: "rgba(255,255,255,0.98)",
  borderLeft: "1px solid #d8d8d8",
  boxShadow: "-4px 0 24px rgba(0,0,0,0.06)",
  display: "flex",
  flexDirection: "column",
  zIndex: 80,
  fontFamily: "inherit",
};

const inputBarStyle = {
  padding: "12px 16px",
  borderTop: "1px solid #eee",
  display: "flex",
  gap: 8,
};

const inputStyle = {
  flex: 1,
  padding: "8px 12px",
  border: "1px solid #ccc",
  borderRadius: 4,
  fontFamily: "inherit",
  fontSize: 13,
  outline: "none",
};

const sendBtnStyle = {
  background: "#111",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  padding: "8px 16px",
  fontFamily: "inherit",
  fontSize: 12,
  cursor: "pointer",
  letterSpacing: "0.02em",
};

function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <div style={{ marginBottom: 16, display: "flex", flexDirection: "column", alignItems: isUser ? "flex-end" : "flex-start" }}>
      <div style={{
        maxWidth: "85%",
        padding: "10px 14px",
        borderRadius: isUser ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
        background: isUser ? "#111" : "#f4f4f4",
        color: isUser ? "#fff" : "#333",
        fontSize: 13,
        lineHeight: "20px",
      }}>
        {message.text}
      </div>

      {/* Answer from LLM */}
      {message.answer && (
        <div style={{
          maxWidth: "85%",
          marginTop: 6,
          padding: "10px 14px",
          borderRadius: "14px 14px 14px 4px",
          background: "#f0f7ff",
          border: "1px solid #d0e0f0",
          fontSize: 12,
          lineHeight: "18px",
          color: "#333",
        }}>
          {message.answer}
        </div>
      )}

      {/* Results */}
      {message.results?.length > 0 && (
        <div style={{ maxWidth: "85%", marginTop: 6 }}>
          {message.results.map((r, i) => {
            const label = r.label || r.pointer?.label || "Unknown";
            const type = r.type || r.pointer?.type || "";
            const score = r.combined_score || r.score;
            const via = r.via || r.via_edge_type;
            const why = r.why || r.via_edge_why;
            const attrs = r.attributes;

            return (
              <div key={i} style={{
                padding: "6px 10px",
                marginBottom: 2,
                background: "#fafafa",
                border: "1px solid #eee",
                borderRadius: 6,
                fontSize: 11,
                cursor: r.pointer_id || r.pointer?.id ? "pointer" : "default",
              }}
                onClick={() => {
                  const id = r.pointer_id || r.pointer?.id;
                  if (id && message.onSelect) message.onSelect(id);
                }}
              >
                <span style={{ fontWeight: 600 }}>{label}</span>
                <span style={{ color: "#999", marginLeft: 6 }}>{type}</span>
                {score != null && <span style={{ color: "#aaa", marginLeft: 6 }}>{(score * 100).toFixed(0)}%</span>}
                <MatchDetails details={r.match_details} />
                {via && <div style={{ color: "#888", marginTop: 2 }}>via {via}{why ? `: ${why}` : ""}</div>}
                {attrs?.length > 0 && (
                  <div style={{ color: "#666", marginTop: 2 }}>
                    {attrs.slice(0, 4).map((a) => `${a.key}: ${typeof a.value === "string" ? a.value : JSON.stringify(a.value)}`).join(" | ")}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Execution plan (collapsible) */}
      {message.plan && (
        <PlanDetail plan={message.plan} />
      )}

      {/* Suggestions */}
      {message.suggestions?.length > 0 && (
        <div style={{ maxWidth: "85%", marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {message.suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => message.onSuggestion?.(s)}
              style={{
                background: "#fff",
                border: "1px solid #ddd",
                borderRadius: 12,
                padding: "4px 10px",
                fontSize: 10,
                cursor: "pointer",
                fontFamily: "inherit",
                color: "#555",
              }}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Timestamp + mode badge */}
      <div style={{ fontSize: 9, color: "#bbb", marginTop: 4, display: "flex", gap: 6, alignItems: "center" }}>
        {message.time}
        {message.mode && (
          <span style={{
            background: message.mode === "deep" ? "#e8e0ff" : "#e8f4e8",
            color: message.mode === "deep" ? "#6b4edd" : "#4a8a4a",
            padding: "1px 6px",
            borderRadius: 8,
            fontSize: 9,
          }}>
            {message.mode === "deep" ? "LLM + Graph" : "Hybrid Search"}
          </span>
        )}
        {message.resultCount != null && (
          <span style={{ color: "#aaa" }}>{message.resultCount} result{message.resultCount !== 1 ? "s" : ""}</span>
        )}
      </div>
    </div>
  );
}

function PlanDetail({ plan }) {
  const [open, setOpen] = useState(false);
  if (!plan?.steps) return null;

  return (
    <div style={{ maxWidth: "85%", marginTop: 4 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{ background: "none", border: "none", color: "#999", fontSize: 10, cursor: "pointer", fontFamily: "inherit", padding: 0 }}
      >
        {open ? "Hide" : "Show"} execution plan ({plan.steps.length} steps)
      </button>
      {open && (
        <div style={{ marginTop: 4, padding: "6px 10px", background: "#fafafa", border: "1px solid #eee", borderRadius: 6, fontSize: 10, fontFamily: "monospace", lineHeight: "16px" }}>
          {plan.steps.map((step, i) => (
            <div key={i} style={{ marginBottom: 2 }}>
              <span style={{ color: "#999" }}>{i + 1}.</span>{" "}
              <span style={{ fontWeight: 600 }}>{step.action}</span>
              {step.query && <span> "{step.query}"</span>}
              {step.type_filter && <span style={{ color: "#888" }}> type={step.type_filter}</span>}
              {step.edge_types && <span style={{ color: "#888" }}> edges=[{step.edge_types.join(",")}]</span>}
              {step.direction && <span style={{ color: "#888" }}> {step.direction}</span>}
              {step.target_type && <span style={{ color: "#888" }}> target={step.target_type}</span>}
              {step.from && <span style={{ color: "#6b4edd" }}> from={step.from}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel({ open, onClose, onSelect }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const scrollRef = useRef(null);

  const {
    quickSearch, deepSearch, clear,
    results, answer, plan, suggestions,
    isSearching, mode, error,
  } = useKnowledgeSearch();

  // Pending response tracker
  const pendingRef = useRef(null);

  // When search completes, append the response as a message
  useEffect(() => {
    if (isSearching || !pendingRef.current) return;

    const query = pendingRef.current;
    pendingRef.current = null;

    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        text: answer || (results.length > 0 ? `Found ${results.length} result${results.length !== 1 ? "s" : ""}.` : "No results found."),
        answer: answer || null,
        results,
        plan,
        suggestions,
        mode,
        time: now,
        resultCount: results.length,
        onSelect,
        onSuggestion: handleSuggestion,
      },
    ]);
  }, [isSearching, results, answer, plan, suggestions, mode, onSelect]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isSearching]);

  const handleSuggestion = (text) => {
    sendMessage(text);
  };

  const sendMessage = (text) => {
    const trimmed = (text || input).trim();
    if (!trimmed) return;

    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    setMessages((prev) => [...prev, { role: "user", text: trimmed, time: now }]);
    setInput("");

    pendingRef.current = trimmed;
    deepSearch(trimmed, "answer");
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleQuickSearch = () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    setMessages((prev) => [...prev, { role: "user", text: `[quick] ${trimmed}`, time: now }]);

    pendingRef.current = trimmed;
    quickSearch(trimmed);
    setInput("");
  };

  if (!open) return null;

  return (
    <div className="panel" style={panelStyle}>
      {/* Header */}
      <div style={{ padding: "14px 16px", borderBottom: "1px solid #eee", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>Knowledge Chat</div>
          <div style={{ fontSize: 10, color: "#888" }}>Ask questions about the knowledge graph</div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#999", cursor: "pointer", fontSize: 18 }}>x</button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "16px" }}>
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "#bbb", fontSize: 12, marginTop: 40 }}>
            <div style={{ marginBottom: 8 }}>Ask anything about the knowledge graph.</div>
            <div style={{ fontSize: 11, color: "#ccc" }}>
              Try: "Who leads NVIDIA?" or "Companies in cybersecurity" or "European regulations"
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {isSearching && (
          <div style={{ color: "#999", fontSize: 12, padding: "8px 0" }}>
            {mode === "deep" ? "Thinking..." : "Searching..."}
          </div>
        )}

        {error && (
          <div style={{ color: "#c44", fontSize: 11, padding: "6px 10px", background: "#fff0f0", border: "1px solid #fcc", borderRadius: 6, marginBottom: 8 }}>
            {error}
          </div>
        )}
      </div>

      {/* Input bar */}
      <div style={inputBarStyle}>
        <input
          style={inputStyle}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question..."
          disabled={isSearching}
        />
        <button
          onClick={() => sendMessage()}
          disabled={isSearching || !input.trim()}
          style={{ ...sendBtnStyle, opacity: isSearching || !input.trim() ? 0.5 : 1 }}
        >
          Ask
        </button>
        <button
          onClick={handleQuickSearch}
          disabled={isSearching || !input.trim()}
          style={{ ...sendBtnStyle, background: "#fff", color: "#333", border: "1px solid #ccc", opacity: isSearching || !input.trim() ? 0.5 : 1 }}
          title="Quick search (no LLM, just hybrid matching)"
        >
          Quick
        </button>
      </div>
    </div>
  );
}
